"""In-memory O(1) tool lookup shared by Issuance, Retrieval and Tagging scans.

[CONCURRENCY] DESIGN (the panel will ask):

  What it is      Two dicts, ``tag_id -> ToolRecord`` and ``tool_id -> ToolRecord``. A scan resolves a tag in O(1)
                  without a SQL round trip, so the cart and the "tool card" appear instantly.
  What it is NOT  The source of truth. Records are immutable snapshots for DISPLAY and fast lookup only. Condition and
                  stock are always re-read from MySQL under ``SELECT ... FOR UPDATE`` at commit time
                  (services/stock_ledger.lock_inventory), so a stale cache can make a screen briefly out of date but can
                  never cause a wrong issuance.
  Multi-terminal  Every terminal runs its own cache. ``tool.updated_at`` and ``inventory.updated_at`` are
                  TIMESTAMP(3) ... ON UPDATE CURRENT_TIMESTAMP(3), so any change made by ANY terminal moves the clock.
                  A daemon thread polls every few seconds for rows whose updated_at is newer than the last one seen and
                  refreshes only those rows.
  Late commits    updated_at is stamped when the statement runs, but becomes visible when the transaction commits. A
                  transaction that commits after the poll has moved past its timestamp would be missed, so each poll
                  re-reads a small overlap window (OVERLAP_SECONDS) and a full reload runs every FULL_RELOAD_SECONDS.
  Deletes         Tools are soft-deleted (is_archived), which is an UPDATE and therefore propagates. A hard delete is
                  caught by the periodic full reload.
  Threads         Readers never block: they read the current dict references, and writers publish new dicts under a
                  lock. Listeners are called from the poller thread; a Tk view must hop to the main thread with
                  ``widget.after(0, ...)``.
"""
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from db import db as default_db

OVERLAP_SECONDS = 3
FULL_RELOAD_SECONDS = 60
DEFAULT_POLL_SECONDS = 4

_SELECT = """
    SELECT t.tool_id, t.name, t.tag_id, t.category, t.`condition` AS tool_condition, t.location, t.item_type,
           t.unit_of_measure, t.price, t.is_archived,
           COALESCE(i.quantity_total, 0) AS quantity_total, COALESCE(i.quantity_available, 0) AS quantity_available,
           COALESCE(i.quantity_in_maintenance, 0) AS quantity_in_maintenance, COALESCE(i.quantity_lost, 0) AS quantity_lost,
           GREATEST(t.updated_at, COALESCE(i.updated_at, t.updated_at)) AS changed_at
    FROM tool t LEFT JOIN inventory i ON i.tool_id = t.tool_id
"""


@dataclass(frozen=True)
class ToolRecord:
    tool_id: int
    name: str
    tag_id: str
    category: str
    condition: str
    location: str
    item_type: str
    unit_of_measure: str
    price: Decimal
    is_archived: bool
    quantity_total: Decimal
    quantity_available: Decimal
    quantity_in_maintenance: Decimal
    quantity_lost: Decimal
    changed_at: datetime

    @property
    def issuable(self) -> bool:
        """Cheap pre-check for the scan toast. The real check is repeated under lock at commit time."""
        return (not self.is_archived and self.condition in (None, "", "Good", "Available")
                and self.quantity_available > 0)


def _record(r: dict) -> ToolRecord:
    return ToolRecord(
        tool_id=r["tool_id"], name=r["name"], tag_id=r["tag_id"], category=r["category"],
        condition=r["tool_condition"], location=r["location"], item_type=r["item_type"],
        unit_of_measure=r["unit_of_measure"], price=r["price"] or Decimal("0"), is_archived=bool(r["is_archived"]),
        quantity_total=r["quantity_total"], quantity_available=r["quantity_available"],
        quantity_in_maintenance=r["quantity_in_maintenance"], quantity_lost=r["quantity_lost"],
        changed_at=r["changed_at"])


def _key(tag) -> str:
    return (tag or "").strip().upper()


class ToolCache:
    def __init__(self, database=None, poll_seconds: float = DEFAULT_POLL_SECONDS):
        self._db = database or default_db
        self._poll = poll_seconds
        self._by_id = {}
        self._by_tag = {}
        self._lock = threading.Lock()
        self._high_water = None
        self._last_full = 0.0
        self._listeners = []
        self._stop = threading.Event()
        self._thread = None

    # ---- lookups (O(1), lock-free reads of immutable records) ---------------------------------------------------
    def by_tag(self, tag_id):
        return self._by_tag.get(_key(tag_id))

    def by_id(self, tool_id):
        return self._by_id.get(tool_id)

    def __len__(self):
        return len(self._by_id)

    # ---- refresh ------------------------------------------------------------------------------------------------
    def add_listener(self, callback):
        """callback(changed_tool_ids: list[int]); called from the poller thread."""
        self._listeners.append(callback)

    def refresh_full(self) -> int:
        with self._db.read() as cur:
            cur.execute(_SELECT)
            rows = cur.fetchall()
        by_id = {r["tool_id"]: _record(r) for r in rows}
        by_tag = {_key(rec.tag_id): rec for rec in by_id.values() if rec.tag_id}
        with self._lock:
            old = self._by_id
            self._by_id, self._by_tag = by_id, by_tag
            self._last_full = time.monotonic()
            self._high_water = max((rec.changed_at for rec in by_id.values()), default=None)
        changed = [i for i, rec in by_id.items() if old.get(i) != rec] + [i for i in old if i not in by_id]
        self._notify(changed)
        return len(by_id)

    def refresh_changed(self) -> list:
        """Reload only rows touched since the last poll (minus the overlap window). Returns the changed tool_ids."""
        if self._high_water is None or time.monotonic() - self._last_full > FULL_RELOAD_SECONDS:
            self.refresh_full()
            return []
        since = self._high_water - timedelta(seconds=OVERLAP_SECONDS)
        with self._db.read() as cur:
            cur.execute(_SELECT + " WHERE GREATEST(t.updated_at, COALESCE(i.updated_at, t.updated_at)) >= %s", (since,))
            rows = cur.fetchall()
        changed = []
        with self._lock:
            by_id, by_tag = dict(self._by_id), dict(self._by_tag)
            for r in rows:
                rec = _record(r)
                prev = by_id.get(rec.tool_id)
                if prev == rec:
                    continue
                if prev is not None and prev.tag_id and _key(prev.tag_id) != _key(rec.tag_id):
                    by_tag.pop(_key(prev.tag_id), None)     # tag was re-assigned
                by_id[rec.tool_id] = rec
                if rec.tag_id:
                    by_tag[_key(rec.tag_id)] = rec
                changed.append(rec.tool_id)
                if self._high_water is None or rec.changed_at > self._high_water:
                    self._high_water = rec.changed_at
            self._by_id, self._by_tag = by_id, by_tag
        self._notify(changed)
        return changed

    def _notify(self, changed):
        if changed:
            for cb in list(self._listeners):
                try:
                    cb(list(changed))
                except Exception:
                    pass

    # ---- background poller ----------------------------------------------------------------------------------------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tool-cache-poller", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._poll + 2)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.refresh_changed()
            except Exception:
                pass            # [UNHAPPY-PATH] database blip: keep serving the last known records and try again
            self._stop.wait(self._poll)


# Process-wide instance used by the views (started by the dashboard after login).
tool_cache = ToolCache()
