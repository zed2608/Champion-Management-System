"""Every module of the program imports in a FRESH interpreter, without a display and without reaching a real database.

Run in a subprocess so nothing the other tests did (patched modules, an already-open pool) can hide a missing import. The database
settings are pointed at a closed local port, so a module that connected at import time would fail here instead of touching real data.
scripts/check_clean_install.py repeats this inside a brand-new virtual environment built from requirements.txt."""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ("services", "views", "db", "utils")
TOP_LEVEL = ("main", "dashboard", "database", "seed_admin")

IMPORT_ALL = """
import importlib, sys
sys.path.insert(0, sys.argv[1])
bad = []
for name in sys.argv[2:]:
    try:
        importlib.import_module(name)
    except BaseException as exc:
        bad.append(name + ": " + type(exc).__name__ + ": " + str(exc))
print("\\n".join(bad))
sys.exit(1 if bad else 0)
"""


def module_names():
    names = list(TOP_LEVEL)
    for pkg in PACKAGES:
        for f in sorted((ROOT / pkg).glob("*.py")):
            names.append(pkg if f.stem == "__init__" else f"{pkg}.{f.stem}")
    return names


def test_the_module_list_is_not_empty():
    names = module_names()
    assert len(names) > 40 and "services.audit_chain" in names and "views.reports" in names


def test_every_module_imports_in_a_fresh_interpreter(tmp_path):
    env = dict(os.environ)
    env.update({"DB_HOST": "127.0.0.1", "DB_PORT": "9", "DB_USER": "nobody", "DB_PASS": "x", "DB_NAME": "test_never_used",
                "CHAMPION_LOG_DIR": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1"})
    proc = subprocess.run([sys.executable, "-c", IMPORT_ALL, str(ROOT), *module_names()],
                          capture_output=True, text=True, timeout=600, env=env, cwd=str(tmp_path))
    assert proc.returncode == 0, f"modules that do not import:\n{proc.stdout}\n{proc.stderr[-1500:]}"
