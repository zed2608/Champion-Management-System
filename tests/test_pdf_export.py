"""PDF export of every report, through the real Reports screen handler (export_pdf), to a temporary folder.

Also the unhappy paths: a folder that refuses the file, a missing folder and a full disk (simulated by making the write raise OSError
after some bytes are already on disk). The user must get a plain sentence and no half-written file may be left behind.
Skipped without a display / throwaway MySQL. Nothing is opened in a PDF viewer (os.startfile is replaced)."""
import errno
import os
import tempfile
import time

import pytest

pytestmark = pytest.mark.db

SEVEN = ["abc", "usage", "activity", "allocation", "damage", "lowstock", "overdue"]


def run(db, sql, params=()):
    with db.transaction() as cur:
        cur.execute(sql, params)
        return cur.lastrowid


def pump(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


@pytest.fixture
def reports(svc, monkeypatch, tmp_path):
    import customtkinter as ctk
    import views.reports as vr
    from conftest import make_window
    d = svc
    admin = run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('ADM-2026-001','Admin','Admin','Active')")
    run(d, "INSERT INTO `user` (employee_id, full_name, role, status) VALUES ('WKR-2026-001','Wally','Worker','Active')")
    tool = run(d, "INSERT INTO tool (name, tag_id, item_type, category, price) VALUES ('Caliper','CAL-001','Equipment','Measuring',900)")
    run(d, "INSERT INTO inventory (tool_id, quantity_total, quantity_available, minimum_stock) VALUES (%s,5,1,3)", (tool,))
    shown, opened = [], []
    for name in ("showinfo", "showerror", "showwarning"):
        monkeypatch.setattr(vr.messagebox, name, lambda title, msg, _n=name, **k: shown.append((_n, title, msg)))
    monkeypatch.setattr(vr.os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    root = make_window(ctk.CTk)
    root.geometry("1000x700+0+0")
    root.update()
    view = vr.ReportsView(root, user_info={"user_id": admin, "role": "Admin", "full_name": "Admin"})
    view.pack(fill="both", expand=True)
    pump(root, 0.8)
    yield view, shown, opened, tmp_path, root
    root.destroy()


def leftovers(folder):
    return sorted(p.name for p in folder.iterdir())


@pytest.mark.parametrize("kind", SEVEN + ["wear", "anomaly"])
def test_every_report_exports_a_real_pdf(reports, kind):
    view, shown, opened, folder, root = reports
    view.export_pdf(kind)
    assert not shown, shown
    assert len(opened) == 1 and opened[0].endswith(".pdf")
    data = open(opened[0], "rb").read()
    assert data.startswith(b"%PDF") and len(data) > 1000
    assert leftovers(folder) == [os.path.basename(opened[0])]       # no .part file left over


def _failing_save(exc, partial=b"%PDF-1.4 half"):
    """Stands in for Image.save: puts some bytes on disk, then fails (what a full disk or a revoked folder looks like)."""
    def save(self, fp, *a, **k):
        with open(fp, "wb") as f:
            f.write(partial)
        raise exc
    return save


@pytest.mark.parametrize("exc,words", [
    (OSError(errno.ENOSPC, "No space left on device"), "disk is full"),
    (PermissionError(errno.EACCES, "Permission denied"), "does not allow saving"),
])
def test_failed_write_shows_a_clear_message_and_leaves_no_file(reports, monkeypatch, exc, words):
    from PIL import Image
    view, shown, opened, folder, root = reports
    monkeypatch.setattr(Image.Image, "save", _failing_save(exc))
    view.export_pdf("usage")
    assert len(shown) == 1 and shown[0][0] == "showerror" and shown[0][1] == "Export Error", shown
    assert words in shown[0][2]
    assert "Errno" not in shown[0][2] and "Traceback" not in shown[0][2] and str(folder) not in shown[0][2]
    assert not opened
    assert leftovers(folder) == []                                   # not even the half-written side file


def test_a_failed_export_does_not_destroy_the_previous_good_file(reports, monkeypatch):
    """The new PDF is built beside the old one; a failure must not touch a good file that already has the real name."""
    from PIL import Image
    from utils.pdf_table import render_pdf
    view, shown, opened, folder, root = reports
    good = folder / "same.pdf"
    render_pdf("T", "c", [(None, ["a"], [["1"]])], str(good))
    before = good.read_bytes()
    monkeypatch.setattr(Image.Image, "save", _failing_save(OSError(errno.ENOSPC, "No space left on device")))
    with pytest.raises(OSError):
        render_pdf("T2", "c", [(None, ["a"], [["2"]])], str(good))
    assert good.read_bytes() == before and leftovers(folder) == ["same.pdf"]


def test_missing_folder_gets_a_plain_message(reports, monkeypatch, tmp_path):
    view, shown, opened, folder, root = reports
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "does" / "not" / "exist"))
    view.export_pdf("abc")
    assert len(shown) == 1 and "could not be found" in shown[0][2] and "Nothing was saved" in shown[0][2], shown
    assert not opened and leftovers(folder) == []


def test_no_viewer_installed_is_not_reported_as_a_failed_export(reports, monkeypatch):
    view, shown, opened, folder, root = reports

    def no_viewer(path):
        raise OSError("no association")
    monkeypatch.setattr("views.reports.os.startfile", no_viewer, raising=False)
    view.export_pdf("usage")
    assert len(shown) == 1 and shown[0][0] == "showinfo" and "was saved" in shown[0][2]
    assert len([n for n in leftovers(folder) if n.endswith(".pdf")]) == 1


def test_friendly_message_for_file_problems_has_no_raw_text():
    from services.errors import friendly_message
    for exc in (OSError(errno.ENOSPC, "No space left on device"), PermissionError(errno.EACCES, "denied"), FileNotFoundError(errno.ENOENT, "gone")):
        msg = friendly_message(exc)
        assert "Nothing was saved" in msg and "Errno" not in msg and "ERR-" not in msg
