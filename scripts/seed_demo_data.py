"""Create (or re-create) a DEMO database full of realistic data for the defense.

    python scripts/seed_demo_data.py                       # builds the database  champion_demo
    python scripts/seed_demo_data.py --database champion_demo --qr-folder demo_qr

Safety rules (enforced in code, not just in this text):
  * the target database name must be  champion_demo...  or  test_...  ; "champion_db" (the real one) is REFUSED, as is any Aiven host;
  * it DROPS and re-creates ONLY that database, so it can be run again to reset the demo;
  * passwords come from DEMO_ADMIN_PASSWORD / DEMO_STAFF_PASSWORD or are prompted (hidden); nothing is hard-coded or printed.

Connection settings (host, port, user, password) are read from --env-file (default .env.demo, else .env). The DB_NAME inside that file
is ignored: the target name is always the --database argument.

The data is written the way the application would have written it (same tables, same stock identity
available = total - deployed - in maintenance, snapshot dates, tickets), with dates spread over the last ~3 weeks, so every dashboard card,
the ABC report, the wear forecast and the anomaly list have something to show.
"""
import argparse
import getpass
import os
import random
import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ALLOWED_NAME = re.compile(r"^(champion_demo[a-z0-9_]*|test_[a-z0-9_]+)$")


def check_target(database, host):
    name = str(database or "").strip().lower()
    if name == "champion_db" or not ALLOWED_NAME.match(name):
        raise SystemExit(f"Refusing to use database {database!r}: only champion_demo... or test_... names are allowed (never champion_db).")
    h = str(host or "").lower()
    if "aiven" in h:
        raise SystemExit("Refusing to run against an Aiven host.")
    return name


# name, category, supplier, location, type, uom, price, total, min_stock, tagged, own service interval (hours)
TOOLS = [
    ("Rotary Hammer Drill", "Power Tools", "Bosch Philippines", "Rack A1", "Equipment", "pcs", 8500, 3, 1, True, 150),
    ("Angle Grinder 4in", "Power Tools", "Makita Trading", "Rack A1", "Equipment", "pcs", 3200, 2, 1, True, None),
    ("Cordless Drill Driver", "Power Tools", "Makita Trading", "Rack A2", "Equipment", "pcs", 4200, 6, 2, True, None),
    ("Circular Saw", "Power Tools", "DeWalt Supply", "Rack A2", "Equipment", "pcs", 5600, 2, 1, True, None),
    ("Jigsaw", "Power Tools", "Bosch Philippines", "Rack A3", "Equipment", "pcs", 3400, 2, 1, True, None),
    ("Bench Grinder", "Power Tools", "Stanley Hardware", "Rack A3", "Equipment", "pcs", 6800, 1, 1, True, None),
    ("Impact Wrench", "Power Tools", "DeWalt Supply", "Rack A3", "Equipment", "pcs", 7400, 3, 1, True, None),
    ("Orbital Sander", "Power Tools", "Makita Trading", "Rack A4", "Equipment", "pcs", 2900, 3, 1, True, None),
    ("Claw Hammer", "Hand Tools", "Stanley Hardware", "Shelf B1", "Equipment", "pcs", 450, 8, 2, True, None),
    ("Ball Peen Hammer", "Hand Tools", "Stanley Hardware", "Shelf B1", "Equipment", "pcs", 520, 4, 1, True, None),
    ("Pipe Wrench 14in", "Hand Tools", "Ridgid Trading", "Shelf B2", "Equipment", "pcs", 1100, 4, 1, True, None),
    ("Adjustable Wrench 10in", "Hand Tools", "Stanley Hardware", "Shelf B2", "Equipment", "pcs", 650, 6, 2, True, None),
    ("Combination Wrench Set", "Hand Tools", "Stanley Hardware", "Shelf B2", "Equipment", "set", 2400, 3, 1, True, None),
    ("Screwdriver Set", "Hand Tools", "Stanley Hardware", "Shelf B3", "Equipment", "set", 780, 6, 2, True, None),
    ("Lineman Pliers", "Hand Tools", "Stanley Hardware", "Shelf B3", "Equipment", "pcs", 520, 6, 2, True, None),
    ("Hacksaw", "Hand Tools", "Stanley Hardware", "Shelf B3", "Equipment", "pcs", 380, 5, 1, True, None),
    ("Bolt Cutter 24in", "Hand Tools", "Ridgid Trading", "Shelf B4", "Equipment", "pcs", 1800, 2, 1, False, None),
    ("Chisel Set", "Hand Tools", "Stanley Hardware", "Shelf B4", "Equipment", "set", 950, 3, 1, True, None),
    ("Socket Set 1/2in", "Hand Tools", "Stanley Hardware", "Shelf B4", "Equipment", "set", 3100, 3, 1, True, None),
    ("Allen Key Set", "Hand Tools", "Stanley Hardware", "Shelf B5", "Equipment", "set", 420, 5, 2, True, None),
    ("Vernier Caliper 150mm", "Measuring", "Mitutoyo Distributor", "Cabinet C1", "Equipment", "pcs", 1450, 4, 1, True, None),
    ("Micrometer 0-25mm", "Measuring", "Mitutoyo Distributor", "Cabinet C1", "Equipment", "pcs", 2800, 2, 1, True, None),
    ("Steel Tape 5m", "Measuring", "Stanley Hardware", "Cabinet C2", "Equipment", "pcs", 260, 8, 2, True, None),
    ("Spirit Level 24in", "Measuring", "Stanley Hardware", "Cabinet C2", "Equipment", "pcs", 580, 4, 1, True, None),
    ("Laser Distance Meter", "Measuring", "Bosch Philippines", "Cabinet C2", "Equipment", "pcs", 3900, 1, 1, True, None),
    ("Welding Machine 250A", "Welding", "Lincoln Electric PH", "Bay D1", "Equipment", "pcs", 14500, 2, 1, True, None),
    ("Welding Helmet", "Welding", "Lincoln Electric PH", "Bay D1", "Equipment", "pcs", 1800, 4, 1, True, None),
    ("Oxy-Acetylene Torch Set", "Welding", "Lincoln Electric PH", "Bay D2", "Equipment", "set", 9800, 2, 1, True, None),
    ("Safety Harness", "Safety", "3M Philippines", "Cage E1", "Equipment", "pcs", 2200, 6, 2, True, None),
    ("Hard Hat", "Safety", "3M Philippines", "Cage E1", "Equipment", "pcs", 380, 12, 4, False, None),
    ("Safety Goggles", "Safety", "3M Philippines", "Cage E1", "Equipment", "pcs", 190, 10, 4, True, None),
    ("Drill Bit Set HSS", "Machining", "Bosch Philippines", "Cabinet F1", "Equipment", "set", 1250, 6, 2, True, None),
    ("Tap and Die Set", "Machining", "Mitutoyo Distributor", "Cabinet F1", "Equipment", "set", 3600, 2, 1, True, None),
    ("Bench Vise 6in", "Machining", "Ridgid Trading", "Bay F2", "Equipment", "pcs", 2700, 3, 1, True, None),
    ("Welding Rod 6013", "Consumables", "Lincoln Electric PH", "Store G1", "Consumable", "kg", 180, Decimal("60.5"), 20, True, None),
    ("Cutting Disc 4in", "Consumables", "Makita Trading", "Store G1", "Consumable", "pcs", 35, 300, 100, True, None),
    ("Cutting Oil", "Consumables", "Shell Lubricants", "Store G2", "Consumable", "L", 220, Decimal("18.5"), 10, True, None),
    ("Bearing Grease", "Consumables", "Shell Lubricants", "Store G2", "Consumable", "kg", 310, Decimal("7.5"), 4, True, None),
    ("Sandpaper Sheets", "Consumables", "3M Philippines", "Store G3", "Consumable", "pcs", 12, 400, 100, True, None),
    ("Masking Tape", "Consumables", "3M Philippines", "Store G3", "Consumable", "rolls", 55, 60, 20, True, None),
]

WORKERS = ["Jun Bautista", "Elmer Cruz", "Rodel Garcia", "Nestor Villanueva", "Dennis Aquino", "Jomar Pascual"]


def _password(env_name, label):
    pw = os.getenv(env_name)
    if pw:
        return pw
    while True:
        a = getpass.getpass(f"New {label} password: ")
        b = getpass.getpass("Again: ")
        if a == b:
            return a
        print("They do not match, try again.")


def build(db, admin_pw, staff_pw, log=print):
    """Fill an empty, migrated database. ``db`` is the project's Database object for the demo database."""
    from services.validators import hash_password
    rnd = random.Random(2026)
    with db.read() as cur:
        cur.execute("SELECT NOW() AS n")
        now = cur.fetchone()["n"].replace(microsecond=0)
    year = now.year
    day = lambda off, hh=8, mm=0: (now + timedelta(days=off)).replace(hour=hh, minute=mm, second=0)

    with db.transaction() as cur:
        def ins(table, **cols):
            keys = ", ".join(f"`{k}`" for k in cols)
            cur.execute(f"INSERT INTO `{table}` ({keys}) VALUES ({', '.join(['%s'] * len(cols))})", tuple(cols.values()))
            return cur.lastrowid

        # ---------------- people
        admin = ins("user", employee_id=f"ADM-{year}-001", full_name="Rhea Santos", email="rhea.santos@demo.local", role="Admin",
                    password_hash=hash_password(admin_pw), status="Active")
        staff = ins("user", employee_id=f"STF-{year}-001", full_name="Miguel Ramos", email="miguel.ramos@demo.local", role="Staff",
                    password_hash=hash_password(staff_pw), status="Active")
        workers = []
        for i, name in enumerate(WORKERS, 1):
            workers.append(ins("user", employee_id=f"WKR-{year}-{i:03d}", full_name=name, role="Worker", status="Active"))
        for prefix, last in (("ADM", 1), ("STF", 1), ("WKR", len(WORKERS))):
            cur.execute("INSERT INTO id_sequences (prefix, yr, last_seq) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE last_seq=%s",
                        (prefix, year, last, last))
        wid = {i + 1: u for i, u in enumerate(workers)}                   # 1..6 -> user_id
        wcode = {i + 1: f"WKR-{year}-{i + 1:03d}" for i in range(len(workers))}

        # ---------------- tools (stock is recomputed at the end from the history)
        tools = {}
        for n, (name, cat, sup, loc, typ, uom, price, total, min_stock, tagged, interval) in enumerate(TOOLS, 1):
            tag = f"TAG-{n:03d}-{re.sub('[^A-Z]', '', cat.upper())[:3]}" if tagged else None
            tid = ins("tool", name=name, category=cat, supplier=sup, location=loc, item_type=typ, unit_of_measure=uom, price=price, tag_id=tag,
                      description=f"{name} ({cat})", date_acquired=day(-120), service_interval_hours=interval)
            tools[name] = {"id": tid, "total": Decimal(str(total)), "min": min_stock, "price": Decimal(price), "tag": tag, "type": typ,
                           "deployed": Decimal(0), "maint": Decimal(0), "lost": Decimal(0)}

        # ---------------- projects
        def project(name, client, loc, head, start, end, status, who, needs):
            pid = ins("projects", name=name, client=client, location=loc, project_head=head, start_date=start.date(), end_date=end.date(),
                      description=f"{name} for {client}", workers_assigned=",".join(wcode[w] for w in who), status="Approved",
                      approved_by=admin, manager_id=admin)
            for tool, q in needs:
                ins("project_requirements", project_id=pid, tool_id=tools[tool]["id"], quantity=q, status="Pending")
            return pid

        p1_needs = [("Angle Grinder 4in", 2), ("Cordless Drill Driver", 4), ("Impact Wrench", 2), ("Welding Machine 250A", 1),
                    ("Safety Harness", 4), ("Cutting Disc 4in", 120), ("Welding Rod 6013", Decimal("25")), ("Steel Tape 5m", 3),
                    ("Rotary Hammer Drill", 1), ("Claw Hammer", 4), ("Hard Hat", 6)]
        p2_needs = [("Rotary Hammer Drill", 2), ("Angle Grinder 4in", 2), ("Impact Wrench", 2), ("Welding Machine 250A", 1),
                    ("Oxy-Acetylene Torch Set", 1), ("Safety Harness", 4), ("Jigsaw", 1), ("Cutting Disc 4in", 60), ("Sandpaper Sheets", 80),
                    ("Pipe Wrench 14in", 3), ("Cutting Oil", Decimal("6.5"))]
        p3_needs = [("Welding Machine 250A", 2), ("Bench Grinder", 1), ("Circular Saw", 1), ("Vernier Caliper 150mm", 2), ("Safety Harness", 2),
                    ("Welding Helmet", 2), ("Welding Rod 6013", Decimal("20"))]
        p1 = project("Warehouse Roof Retrofit Phase 1", "Metro Steelworks Inc.", "Calamba, Laguna", "Engr. L. Mercado", day(-23), day(-9), "Completed",
                     [1, 2, 3], p1_needs)
        p2 = project("Riverside Plant Shutdown Maintenance", "AquaPure Industries", "Batangas City", "Engr. R. Villareal", day(-17), day(-2), "Ongoing",
                     [2, 3, 4, 5], p2_needs)
        p3 = project("Cavite Fabrication Bay Installation", "Sunrise Fabricators", "Dasmarinas, Cavite", "Engr. A. Tolentino", day(5), day(40), "Approved",
                     [1, 6], p3_needs)

        # ---------------- history: (project, worker no., tool, qty, issued offset, returned offset or None, condition)
        L = []                                                            # lines

        def line(pid, w, tool, qty, out, back, cond="Good", note=None):
            L.append(dict(pid=pid, w=w, tool=tool, qty=Decimal(str(qty)), out=out, back=back, cond=cond, note=note))

        # Project 1 (completed): everything is back
        for k, (out, back) in enumerate([(-22, -20), (-20, -18), (-18, -16), (-16, -14), (-14, -12), (-12, -10)]):
            line(p1, 1 + k % 2, "Angle Grinder 4in", 2, out, back, "Good")      # the busy tool: always out, often asked for
        line(p1, 3, "Angle Grinder 4in", 1, -21, -17, "Damaged", "Disc guard cracked after a fall from the scaffold")
        line(p1, 1, "Cordless Drill Driver", 3, -22, -11, "Good")
        line(p1, 3, "Cordless Drill Driver", 1, -22, -13, "Damaged", "Chuck does not grip, battery contact burnt")
        line(p1, 2, "Impact Wrench", 1, -21, -12, "Good")
        line(p1, 3, "Impact Wrench", 1, -21, -12, "Lost", "Not returned from the roof deck, searched twice")
        line(p1, 1, "Welding Machine 250A", 1, -22, -10, "Good")
        line(p1, 2, "Safety Harness", 4, -22, -10, "Good")
        line(p1, 1, "Cutting Disc 4in", 120, -22, -10, "Good")
        line(p1, 2, "Welding Rod 6013", Decimal("25"), -22, -10, "Good")
        line(p1, 1, "Steel Tape 5m", 3, -22, -10, "Good")
        line(p1, 3, "Rotary Hammer Drill", 1, -22, -10, "Good")
        line(p1, 1, "Claw Hammer", 4, -22, -10, "Good")
        line(p1, 2, "Hard Hat", 6, -22, -10, "Good")
        # Project 2 (ongoing, past its end date): some back, some still out = overdue
        for out, back in [(-16, -15), (-15, -13), (-13, -11), (-11, -9)]:
            line(p2, 2 + (out % 3), "Angle Grinder 4in", 2, out, back, "Good")
        line(p2, 3, "Rotary Hammer Drill", 1, -16, -12, "Damaged", "Bit seized in the chuck; motor smells burnt")
        line(p2, 4, "Rotary Hammer Drill", 2, -9, None)
        line(p2, 4, "Angle Grinder 4in", 1, -8, None)
        line(p2, 4, "Pipe Wrench 14in", 2, -8, None)
        line(p2, 5, "Welding Machine 250A", 1, -9, None)
        line(p2, 5, "Oxy-Acetylene Torch Set", 1, -9, None)
        line(p2, 5, "Safety Harness", 2, -9, None)
        line(p2, 2, "Impact Wrench", 2, -7, None)
        line(p2, 3, "Jigsaw", 1, -14, -9, "Damaged", "Blade holder bent")
        line(p2, 3, "Sandpaper Sheets", 80, -15, -9, "Good")
        line(p2, 5, "Cutting Disc 4in", 40, -13, None)
        line(p2, 2, "Cutting Oil", Decimal("4.5"), -12, -6, "Good")
        line(p2, 3, "Cutting Oil", Decimal("2"), -10, None)

        for ln in L:
            t = tools[ln["tool"]]
            issued = day(ln["out"], rnd.choice([7, 8, 9]), rnd.choice([0, 15, 30, 45]))
            due = None
            cur.execute("SELECT end_date FROM projects WHERE project_id=%s", (ln["pid"],))
            due = cur.fetchone()["end_date"]
            cur.execute("SELECT start_date FROM projects WHERE project_id=%s", (ln["pid"],))
            start = cur.fetchone()["start_date"]
            back = ln["back"]
            returned = day(back, rnd.choice([15, 16, 17]), rnd.choice([0, 20, 40])) if back is not None else None
            tid = ins("transaction", tool_id=t["id"], user_id=wid[ln["w"]], project_id=ln["pid"], type="Retrieval" if returned else "Issue",
                      purpose=None, quantity=ln["qty"], borrow_date=issued, return_date=returned, project_start_date=start, due_date=due,
                      status="Returned" if returned else "Active", condition_at_borrow="Good",
                      condition_at_return=ln["cond"] if returned else None, condition_return_notes=ln["note"], issued_by=staff,
                      received_by=staff if returned else None)
            if not returned:
                t["deployed"] += ln["qty"]
            elif ln["cond"] in ("Damaged", "Needs Repair"):
                t["maint"] += ln["qty"]
                ins("tool_issues", tool_id=t["id"], transaction_id=tid, reported_by="Miguel Ramos", reported_by_user_id=staff,
                    condition_flag=ln["cond"], notes=ln["note"], quantity=ln["qty"], flagged_at=returned)
            elif ln["cond"] == "Lost":
                t["lost"] += ln["qty"]
                ins("tool_issues", tool_id=t["id"], transaction_id=tid, reported_by="Miguel Ramos", reported_by_user_id=staff,
                    condition_flag="Lost", notes=ln["note"], quantity=ln["qty"], flagged_at=returned)

        # one repaired ticket (back in stock, resolved) so the Maintenance list shows both kinds
        sander = tools["Orbital Sander"]
        tid = ins("transaction", tool_id=sander["id"], user_id=wid[1], project_id=p1, type="Retrieval", quantity=1, borrow_date=day(-21),
                  return_date=day(-18, 16), project_start_date=day(-23).date(), due_date=day(-9).date(), status="Returned",
                  condition_at_borrow="Good", condition_at_return="Needs Repair", condition_return_notes="Worn pad, vibrates", issued_by=staff,
                  received_by=staff)
        ins("tool_issues", tool_id=sander["id"], transaction_id=tid, reported_by="Miguel Ramos", reported_by_user_id=staff,
            condition_flag="Needs Repair", notes="Worn pad, vibrates", quantity=1, flagged_at=day(-18, 16), status="Resolved",
            is_resolved=1, resolved_by=admin, resolved_at=day(-15, 10))
        cur.execute("UPDATE tool SET last_serviced_at=%s WHERE tool_id=%s", (day(-15, 10), sander["id"]))

        # the projects walk the legal status path now that their issuances exist (the database triggers allow only these edges)
        for pid in (p1, p2):
            cur.execute("UPDATE projects SET status='Ongoing' WHERE project_id=%s", (pid,))
            cur.execute("UPDATE project_requirements SET status='Fulfilled' WHERE project_id=%s", (pid,))
        cur.execute("UPDATE projects SET status='Completed' WHERE project_id=%s", (p1,))

        # ---------------- stock from the history (available = total - deployed - maintenance - lost)
        for t in tools.values():
            total = t["total"] - t["lost"]
            avail = total - t["deployed"] - t["maint"]
            assert avail >= 0, (t, "history needs more stock than exists")
            ins("inventory", tool_id=t["id"], quantity_total=total, quantity_available=avail, minimum_stock=t["min"],
                quantity_in_maintenance=t["maint"], quantity_lost=t["lost"])
            if t["maint"] > 0 or t["lost"] > 0:                      # tool.condition is the worst OPEN ticket (what the app shows)
                cur.execute("UPDATE tool SET `condition`=%s WHERE tool_id=%s", ("Lost" if t["lost"] > 0 else "Damaged", t["id"]))

        # ---------------- refused issuances (the demand the store turned away)
        grinder = tools["Angle Grinder 4in"]["id"]
        for off, q in [(-14, 1), (-12, 2), (-10, 1), (-8, 1), (-6, 2), (-4, 1), (-2, 1)]:
            ins("issuance_attempts", tool_id=grinder, project_id=p2, user_id=wid[2 + off % 3], actor_id=staff, quantity=q, available=0,
                reason="out_of_stock", detail="Out of stock at the counter", attempted_at=day(off, 10, 5))
        ins("issuance_attempts", tool_id=tools["Safety Harness"]["id"], project_id=p2, user_id=wid[4], actor_id=staff, quantity=3, available=2,
            reason="over_quota", detail="More than approved", attempted_at=day(-6, 11, 0))
        ins("issuance_attempts", tool_id=tools["Cordless Drill Driver"]["id"], project_id=p1, user_id=wid[1], actor_id=staff, quantity=1, available=2,
            reason="past_end", detail="Project ended", attempted_at=day(-7, 14, 20))

        # ---------------- a recent backup, a help ticket
        ins("backup_logs", filename="champion_demo_backup.sql", filepath="D:\\ChampionBackups\\champion_demo_backup.sql", file_size="1.2 MB",
            note="Weekly backup", created_by=admin, created_at=day(-3, 18), status="Success", type="Backup")
        ins("help_tickets", user_id=staff, subject="Scanner is slow in the morning", message="The webcam takes a few seconds to start.",
            status="Open", created_at=day(-1, 9))
    # ---------------- audit trail through the real chain
    import database
    for uid, action, module, detail in [
            (admin, "Login", "Auth", "Admin logged in"), (staff, "Login", "Auth", "Staff logged in"),
            (admin, "Created", "Projects", "Approved project 'Riverside Plant Shutdown Maintenance'"),
            (staff, "Issued", "Issuance", "Issued tools to WKR-%d-004 for Riverside Plant Shutdown Maintenance" % year),
            (staff, "Retrieved", "Issuance", "Retrieved Angle Grinder 4in from WKR-%d-002" % year),
            (admin, "Edited", "Inventory", "Set service interval of 'Rotary Hammer Drill' to 150 hours"),
            (admin, "Created", "Maintenance", "Backup created: champion_demo_backup.sql")]:
        database.log_action(uid, action, module, detail)
    return {"admin": admin, "staff": staff, "workers": workers, "projects": [p1, p2, p3]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Create the champion_demo database with demo data.")
    ap.add_argument("--database", default="champion_demo")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--qr-folder", default=None, help="also write QR badge / tag pictures here (for the webcam demo)")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv
    env_file = Path(args.env_file) if args.env_file else (ROOT / ".env.demo" if (ROOT / ".env.demo").exists() else ROOT / ".env")
    if env_file.exists():
        load_dotenv(env_file, override=False)
    target = check_target(args.database, os.getenv("DB_HOST", "localhost"))
    os.environ["DB_NAME"] = target                                    # BEFORE the project's global pool is created

    admin_pw = _password("DEMO_ADMIN_PASSWORD", "Admin")
    staff_pw = _password("DEMO_STAFF_PASSWORD", "Staff")

    import mysql.connector
    from db import migrate
    from db.pool import Database, config_from_env
    cfg = config_from_env()
    assert cfg["database"] == target
    root = mysql.connector.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"], password=cfg["password"], autocommit=True)
    cur = root.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{target}`")                # target already validated: champion_demo... / test_... only
    cur.execute(f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4")
    cur.close()
    root.close()
    print(f"Created empty database {target}. Running the normal migration ...")

    from db import db
    if target.startswith("test"):
        migrate.run(db, require_backup=False, log=lambda *_: None)
    else:
        migrate.run(db, make_backup_now=True, log=lambda *_: None)    # the migration insists on a backup (of the empty database)
    print("Filling demo data ...")
    build(db, admin_pw, staff_pw)

    if args.qr_folder:
        from database import generate_id_badge
        out = Path(args.qr_folder)
        out.mkdir(parents=True, exist_ok=True)
        year = datetime.now().year
        for i, name in enumerate(WORKERS, 1):
            generate_id_badge(f"WKR-{year}-{i:03d}", name, "Worker", output_dir=str(out))
        print(f"QR badges written to {out}")
    print(f"Done. Database {target} is ready. Admin: ADM-{datetime.now().year}-001, Staff: STF-{datetime.now().year}-001.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
