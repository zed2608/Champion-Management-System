"""Every third-party module the application imports must be declared in requirements.txt (tkcalendar was installed by hand in the old
environment and missing from the file, so a fresh environment broke both date pickers)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
# import name -> distribution name (normalised with underscores)
KNOWN = {"pil": "pillow", "cv2": "opencv_python", "dotenv": "python_dotenv", "mysql": "mysql_connector_python", "pyzbar": "pyzbar",
         "tkcalendar": "tkcalendar", "matplotlib": "matplotlib", "bcrypt": "bcrypt", "customtkinter": "customtkinter",
         "qrcode": "qrcode", "numpy": "numpy"}


def declared():
    names = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").split():
        if line.strip() and not line.startswith("#"):
            names.add(re.split(r"[=<>~!]", line)[0].strip().lower().replace("-", "_"))
    return names


def imported():
    files = [ROOT / f for f in ("main.py", "dashboard.py", "database.py")]
    for folder in ("views", "services", "db", "utils"):
        files += list((ROOT / folder).glob("*.py"))
    found = set()
    for f in files:
        for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_0-9]+)", f.read_text(encoding="utf-8"), re.M):
            found.add(m.group(1).lower())
    return found


def test_every_third_party_import_is_declared():
    missing = sorted(i for i in imported() if i in KNOWN and KNOWN[i] not in declared())
    assert not missing, f"imported but missing from requirements.txt: {missing}"


def test_tkcalendar_is_pinned_and_importable():
    assert "tkcalendar" in declared()
    import tkcalendar                                    # the Projects and Reports date pickers need it
    assert hasattr(tkcalendar, "Calendar")
