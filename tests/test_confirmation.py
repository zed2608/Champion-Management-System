"""A confirmation must be visible over topmost edit panels and default to No."""

from ui import components as C


class Panel:
    def __init__(self):
        self.topmost = True
        self.events = []

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
