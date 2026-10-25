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
