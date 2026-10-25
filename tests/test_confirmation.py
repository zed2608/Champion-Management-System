"""A confirmation must be visible over topmost edit panels and default to No."""

from ui import components as C


class Panel:
    def __init__(self, master=None):
        self.topmost = True
        self.events = []
        self.master = master

    def attributes(self, flag, value=None):
        assert flag == "-topmost"
        if value is None:
            return self.topmost
        self.topmost = value
        self.events.append(("topmost", value))

    def lift(self):
        self.events.append(("lift",))

    def winfo_exists(self):
        return True


def test_confirm_lowers_topmost_panel_for_question_and_restores_it(monkeypatch):
    panel = Panel()

    def question(title, body, **options):
        assert (title, body) == ("Save item", "Save 2.5 kg?")
        assert options == {"parent": panel, "default": "no", "icon": "question"}
        assert panel.topmost is False
        return False

    monkeypatch.setattr(C.messagebox, "askyesno", question)
    assert C.confirm("Save item", "Save 2.5 kg?", parent=panel) is False
    assert panel.topmost is True
    assert panel.events == [("topmost", False), ("lift",), ("topmost", True), ("lift",)]


def test_nested_catalog_lowers_topmost_project_parent(monkeypatch):
    project = Panel()
    catalog = Panel(master=project)

    def question(*_args, **_kwargs):
        assert project.topmost is False
        assert catalog.topmost is False
        return True

    monkeypatch.setattr(C.messagebox, "askyesno", question)
    assert C.confirm("Add", "Add 2.5 kg?", parent=catalog) is True
    assert project.topmost is True
    assert catalog.topmost is True
    assert project.events[-1] == ("lift",)
    assert catalog.events[-1] == ("lift",)


def test_real_window_uses_foreground_confirmation(monkeypatch):
    panel = Panel()
    panel.tk = object()
    calls = []
    monkeypatch.setattr(C, "_confirm_window", lambda *args: calls.append(args) or False)
    assert C.confirm("Add item", "Add 2.5 kg?", parent=panel) is False
    assert calls == [("Add item", "Add 2.5 kg?", panel)]


def test_notices_use_foreground_window_for_tk_parent(monkeypatch):
    panel = Panel()
    panel.tk = object()
    calls = []
    monkeypatch.setattr(C, "_notice_window", lambda *args: calls.append(args) or "ok")
    assert C.messagebox.showwarning("Check quantity", "Use whole pieces", parent=panel) == "ok"
    assert calls == [("Check quantity", "Use whole pieces", panel, "showwarning")]


def test_new_popup_is_transient_and_restores_previous_grab():
    owner = Panel()

    class Popup(Panel):
        def __init__(self):
            super().__init__(owner)
            self.handlers = {}

        def grab_current(self):
            return owner

        def winfo_toplevel(self):
            return self

        def transient(self, parent):
            assert parent is owner

        def focus_force(self):
            self.events.append(("focus",))

        def after_idle(self, callback):
            self.handlers["idle"] = callback

        def bind(self, event, callback, add=None):
            self.handlers[event] = callback

    owner.winfo_toplevel = lambda: owner
    owner.grab_set = lambda: owner.events.append(("grab",))
    owner.focus_force = lambda: owner.events.append(("focus",))
    popup = Popup()
    C.keep_above(popup)
    popup.handlers["idle"]()
    popup.handlers["<Destroy>"](type("Event", (), {"widget": popup})())
    assert popup.events[:2] == [("topmost", True), ("lift",)]
    assert owner.events == [("grab",), ("lift",), ("focus",)]
