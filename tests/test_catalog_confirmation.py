"""Project requirements need approval and never change the warehouse stock."""
from types import SimpleNamespace
import sys
import types


class Entry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *_args):
        self.value = ""


class Status:
    def configure(self, **kwargs):
        self.text = kwargs["text"]


def test_decimal_requirement_requires_confirmation_and_leaves_stock_unchanged(monkeypatch):
    # This headless test exercises staging; QR decoding needs a native zbar
    # library only when the actual camera is used.
    scanner = types.ModuleType("pyzbar.pyzbar")
    scanner.decode = lambda *_args, **_kwargs: []
    scanner.ZBarSymbol = SimpleNamespace(QRCODE=64)
    monkeypatch.setitem(sys.modules, "pyzbar.pyzbar", scanner)
    from views import projects
    row = {"tool_id": 17, "name": "Nails", "type": "Consumable", "uom": "kg",
           "avail": "25.5", "total": "25.5"}
    status = Status()
    modal = SimpleNamespace(catalog_status=status)
    view = SimpleNamespace(req_cart=[], refresh_req_cart=lambda: None,
                           _catalog_added=projects.ProjectsView._catalog_added)
    entry = Entry("2.5")
    prompts = []

    def reject(title, message, *, parent):
        prompts.append((title, message, parent))
        return False

    monkeypatch.setattr(projects.C, "confirm", reject)
    projects.ProjectsView.add_from_catalog(view, row, entry, modal)
    assert view.req_cart == []
    assert entry.get() == "2.5"
    assert "stock count changes when the item is issued" in prompts[0][1]

    monkeypatch.setattr(projects.C, "confirm", lambda *args, **kwargs: True)
    projects.ProjectsView.add_from_catalog(view, row, entry, modal)
    assert str(view.req_cart[0]["qty"]) == "2.50"
    assert row["avail"] == row["total"] == "25.5"
    assert "Stock is unchanged" in status.text
    assert entry.get() == ""
