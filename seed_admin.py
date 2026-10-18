"""Create the first Admin account on an empty database, or unlock/reset the existing one.

    python seed_admin.py

The password is NEVER hard-coded: set ADMIN_INITIAL_PASSWORD, or you are prompted (twice, hidden). It must meet the same
strength rules as the registration screen. Run `python -m db.migrate --make-backup` first so the tables exist.
"""
import datetime
import getpass
import os
import sys

from db import db, user_message
from services.validators import ValidationError, hash_password, validate_email, validate_new_password


def _password() -> str:
    pw = os.getenv("ADMIN_INITIAL_PASSWORD")
    if pw:
        return validate_new_password(pw)
    while True:
        a = getpass.getpass("New Admin password: ")
        try:
            validate_new_password(a)
        except ValidationError as exc:
            print(f"  {exc}")
            continue
        if a != getpass.getpass("Repeat password: "):
            print("  Passwords do not match.")
            continue
        return a


def seed_admin() -> int:
    year = datetime.datetime.now().year
    emp_id = f"ADM-{year}-001"
    try:
        email = validate_email(os.getenv("ADMIN_EMAIL", ""), required=False)
        hashed = hash_password(_password())
    except ValidationError as exc:
        print(f"ERROR: {exc}")
        return 2
    try:
        with db.transaction() as cur:
            cur.execute("SELECT user_id FROM `user` WHERE employee_id = %s", (emp_id,))
            if cur.fetchone():
                cur.execute("UPDATE `user` SET password_hash = %s, status = 'Active', failed_attempts = 0, "
                            "reset_requested = 0 WHERE employee_id = %s", (hashed, emp_id))
                print(f"Account {emp_id} existed: password reset and account unlocked.")
            else:
                cur.execute("INSERT INTO `user` (employee_id, full_name, email, role, password_hash, status) "
                            "VALUES (%s, 'System Admin', %s, 'Admin', %s, 'Active')", (emp_id, email, hashed))
                cur.execute("INSERT INTO id_sequences (prefix, yr, last_seq) VALUES ('ADM', %s, 1) "
                            "ON DUPLICATE KEY UPDATE last_seq = GREATEST(last_seq, 1)", (year,))
                print(f"Account {emp_id} created.")
    except Exception as exc:
        print("ERROR: " + user_message(exc))
        return 1
    print(f"Log in with Employee ID {emp_id} and the password you just set.")
    return 0


if __name__ == "__main__":
    sys.exit(seed_admin())
