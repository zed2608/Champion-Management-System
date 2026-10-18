import threading
import time

import pytest

from services.tool_cache import ToolCache

pytestmark = pytest.mark.db


@pytest.fixture
def cached(fresh_db):
    d = fresh_db
    with d.transaction() as cur:
        cur.execute("INSERT INTO tool (name, tag_id, `condition`, price) VALUES "
                    "('Caliper','CAL-001','Good',4500), ('Drill','DRL-001','Good',6200), ('Old','OLD-001','Good',1)")
        cur.execute("INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (1,10,10),(2,5,5),(3,1,1)")
    cache = ToolCache(d, poll_seconds=0.2)
    assert cache.refresh_full() == 3
    return d, cache


def test_lookup_by_tag_and_id_is_case_insensitive(cached):
    _, c = cached
    assert c.by_tag("cal-001").name == "Caliper"
    assert c.by_tag("  CAL-001 ").tool_id == 1
    assert c.by_id(2).tag_id == "DRL-001"
    assert c.by_tag("NOPE-001") is None and len(c) == 3


def test_issuable_precheck(cached):
    d, c = cached
    assert c.by_tag("CAL-001").issuable
    with d.transaction() as cur:
        cur.execute("UPDATE inventory SET quantity_available = 0 WHERE tool_id = 1")
        cur.execute("UPDATE tool SET `condition` = 'Damaged' WHERE tool_id = 2")
        cur.execute("UPDATE tool SET is_archived = 1 WHERE tool_id = 3")
    c.refresh_changed()
    assert not c.by_id(1).issuable            # no stock
    assert c.by_id(2).issuable                # condition is only a display flag: other units stay issuable
    assert not c.by_id(3).issuable            # archived


def test_refresh_changed_picks_up_another_terminals_changes_only(cached):
    d, c = cached
    time.sleep(0.01)
    with d.transaction() as cur:                                  # "terminal B" takes 4 caliper units
        cur.execute("UPDATE inventory SET quantity_available = quantity_available - 4 WHERE tool_id = 1")
    changed = c.refresh_changed()
    assert changed == [1]
    assert c.by_tag("CAL-001").quantity_available == 6
    assert c.by_id(2).quantity_available == 5                     # untouched row unchanged
    assert c.refresh_changed() == []                              # nothing new: nothing reloaded


def test_tag_reassignment_and_new_tool_propagate(cached):
    d, c = cached
    time.sleep(0.01)
    with d.transaction() as cur:
        cur.execute("UPDATE tool SET tag_id = 'CAL-777' WHERE tool_id = 1")
        cur.execute("INSERT INTO tool (name, tag_id) VALUES ('New','NEW-001')")
        cur.execute("INSERT INTO inventory (tool_id, quantity_total, quantity_available) VALUES (LAST_INSERT_ID(), 2, 2)")
    c.refresh_changed()
    assert c.by_tag("CAL-001") is None and c.by_tag("CAL-777").tool_id == 1      # old tag no longer resolves
    assert c.by_tag("NEW-001").name == "New" and len(c) == 4


def test_late_commit_inside_overlap_window_is_not_missed(cached):
    """A transaction stamps updated_at when its statement runs but is only visible when it commits."""
    d, c = cached
    started, release = threading.Event(), threading.Event()

    def slow_terminal():
        with d.transaction() as cur:
            cur.execute("UPDATE inventory SET quantity_available = 1 WHERE tool_id = 2")   # stamped now, visible later
            started.set()
            release.wait(10)

    t = threading.Thread(target=slow_terminal)
    t.start()
    started.wait(10)
    with d.transaction() as cur:                                 # a faster terminal commits a newer change meanwhile
        cur.execute("UPDATE inventory SET quantity_available = 9 WHERE tool_id = 1")
    c.refresh_changed()                                          # high-water mark moves past the slow row's stamp
    release.set()
    t.join(10)
    c.refresh_changed()                                          # overlap window re-reads it
    assert c.by_id(2).quantity_available == 1 and c.by_id(1).quantity_available == 9


def test_background_poller_notifies_listeners_and_survives_db_errors(cached):
    d, c = cached
    events = []
    c.add_listener(events.append)
    c.start()
    try:
        time.sleep(0.05)
        with d.transaction() as cur:
            cur.execute("UPDATE tool SET location = 'Shelf 9' WHERE tool_id = 3")
        deadline = time.time() + 5
        while not events and time.time() < deadline:
            time.sleep(0.05)
        assert events and 3 in events[0]
        assert c.by_id(3).location == "Shelf 9"
    finally:
        c.stop()


def test_poller_keeps_serving_last_known_data_when_database_is_unreachable(cached):
    d, c = cached
    d.close()
    d.config["host"], d.config["port"], d.config["connection_timeout"], d.config["pool_wait"] = "127.0.0.1", 1, 1, 0.1
    c.start()
    time.sleep(1.5)                                              # poller hits errors and must not die
    try:
        assert c.by_tag("CAL-001").name == "Caliper"             # still answers from memory
        assert c._thread.is_alive()
    finally:
        c.stop()
