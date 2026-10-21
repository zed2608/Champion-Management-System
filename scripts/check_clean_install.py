"""Prove that requirements.txt alone is enough: build a brand-new virtual environment, install ONLY requirements.txt, then import every module.

    python scripts/check_clean_install.py [path\\to\\python3.11.exe]

Needs internet (pip downloads the packages) and a few minutes. It only IMPORTS modules; it never connects to a database (the database
settings are pointed at a closed port) and never starts the program. The temporary environment is deleted afterwards.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from test_imports import IMPORT_ALL, module_names           # noqa: E402  (same module list and same import script as the test)


def main():
    base_python = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    work = Path(tempfile.mkdtemp(prefix="champion_clean_"))
    try:
        venv = work / "venv"
        subprocess.run([base_python, "-m", "venv", str(venv)], check=True)
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")], check=True)
        env = dict(os.environ, DB_HOST="127.0.0.1", DB_PORT="9", DB_USER="nobody", DB_PASS="x", DB_NAME="test_never_used",
                   CHAMPION_LOG_DIR=str(work / "logs"), PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([str(py), "-c", IMPORT_ALL, str(ROOT), *module_names()], env=env, cwd=str(work), text=True, capture_output=True)
        print(proc.stdout.strip() or "(no import errors)")
        print(proc.stderr.strip()[-1500:])
        print("CLEAN INSTALL OK" if proc.returncode == 0 else "CLEAN INSTALL FAILED")
        return proc.returncode
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
