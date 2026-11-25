# Compatibility entry point; no hardcoded password.
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from seed_admin import seed_admin
if __name__ == '__main__':
    seed_admin()
