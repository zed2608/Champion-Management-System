"""Built-in Help updates must preserve changes made by an Admin."""
import hashlib

from services.help_service import _untouched_default


def test_untouched_builtin_can_be_refreshed_but_admin_edit_cannot():
    old = "Step one|||Step two"
    digest = hashlib.sha256(old.encode("utf-8")).hexdigest()
    row = {"title": "Projects", "steps": old}
    assert _untouched_default(row, "Projects", digest, "title", "steps")
    assert not _untouched_default({**row, "steps": "My custom guide"}, "Projects", digest, "title", "steps")
    assert not _untouched_default({**row, "title": "Our projects"}, "Projects", digest, "title", "steps")
