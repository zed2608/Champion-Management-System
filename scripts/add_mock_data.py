"""Add a small, repeatable sample to the database configured in .env.

    python scripts/add_mock_data.py           # preview, no database writes
    python scripts/add_mock_data.py --apply   # add missing Demo records

Unlike seed_demo_data.py, this never drops tables or changes existing records.
It uses the application's services, so project and inventory rules still apply.
"""
import argparse
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# name, category, supplier, location, type, unit, price, stock, minimum, tag
TOOLS = (
    ("Demo Rotary Hammer", "Power Tools", "Bosch Philippines", "Rack A1", "Equipment", "pcs", 8500, 4, 2, "DEMO-HAM-001"),
    ("Demo Cordless Drill", "Power Tools", "Makita Trading", "Rack A1", "Equipment", "pcs", 4200, 6, 2, "DEMO-DRL-001"),
    ("Demo Angle Grinder", "Power Tools", "Makita Trading", "Rack A2", "Equipment", "pcs", 3200, 3, 1, "DEMO-GRD-001"),
    ("Demo Circular Saw", "Power Tools", "DeWalt Supply", "Rack A2", "Equipment", "pcs", 5600, 2, 1, "DEMO-SAW-001"),
    ("Demo Claw Hammer", "Hand Tools", "Stanley Hardware", "Shelf B1", "Equipment", "pcs", 450, 8, 2, "DEMO-CLW-001"),
    ("Demo Pipe Wrench", "Hand Tools", "Ridgid Trading", "Shelf B2", "Equipment", "pcs", 1100, 4, 1, "DEMO-WRN-001"),
    ("Demo Vernier Caliper", "Measuring", "Mitutoyo Distributor", "Cabinet C1", "Equipment", "pcs", 1450, 3, 1, "DEMO-CAL-001"),
    ("Demo Welding Helmet", "Safety", "Lincoln Electric PH", "Cage D1", "Equipment", "pcs", 1800, 5, 2, "DEMO-HEL-001"),
    ("Demo Safety Harness", "Safety", "3M Philippines", "Cage D2", "Equipment", "pcs", 2200, 5, 2, "DEMO-HAR-001"),
    ("Demo Hard Hat", "Safety", "3M Philippines", "Cage D2", "Equipment", "pcs", 380, 10, 3, None),
    ("Demo Welding Rods", "Consumables", "Lincoln Electric PH", "Store E1", "Consumable", "kg", 180, "25.50", 8, "DEMO-ROD-001"),
    ("Demo Cutting Discs", "Consumables", "Makita Trading", "Store E1", "Consumable", "pcs", 35, 60, 20, None),
)
WORKERS = ("Demo Ana Santos", "Demo Ben Cruz")
# name, client, site, head, start offset, end offset, worker index, (tool name, quantity)
PROJECTS = (
    ("Demo - Workshop Renovation", "Champion Fine Tooling", "Workshop A", "Ana Mercado", -2, 21, 0,
     (("Demo Rotary Hammer", 2), ("Demo Claw Hammer", 3), ("Demo Hard Hat", 3))),
    ("Demo - Fabrication Bay Setup", "Metro Steelworks", "Fabrication Bay", "Luis Reyes", 3, 35, 1,
     (("Demo Cordless Drill", 3), ("Demo Welding Helmet", 2), ("Demo Welding Rods", "5.50"))),
    ("Demo - Tool Calibration", "Champion Fine Tooling", "Quality Room", "Mila Cruz", 0, 10, 0,
     (("Demo Vernier Caliper", 2), ("Demo Pipe Wrench", 1))),
)


def _one(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()


def apply():
    from db import db
    from services import inventory_service, project_service, user_service

    with db.read() as cur:
        admin = _one(cur, "SELECT user_id FROM `user` WHERE role='Admin' AND status='Active' ORDER BY user_id LIMIT 1", ())
        today = _one(cur, "SELECT CURDATE() AS today", ())["today"]
    if admin is None:
        raise RuntimeError("An active Admin is needed. Create one in the app before adding sample data.")
    actor = {"user_id": admin["user_id"]}
    counts = {"workers": 0, "tools": 0, "projects": 0}
    worker_ids = []
    for name in WORKERS:
        with db.read() as cur:
            row = _one(cur, "SELECT employee_id, status FROM `user` WHERE full_name=%s AND role='Worker' ORDER BY user_id LIMIT 1", (name,))
        if row and row["status"] != "Active":
            raise RuntimeError(f"{name} exists but is inactive; resolve that account before retrying.")
        if row is None:
            row = user_service.register_user(actor, name=name, email="", role="Worker")
            counts["workers"] += 1
        worker_ids.append(row["employee_id"])

    tool_ids = {}
    for name, category, supplier, location, kind, unit, price, stock, minimum, tag in TOOLS:
        with db.read() as cur:
            row = _one(cur, "SELECT tool_id FROM tool WHERE name=%s AND is_archived=0 ORDER BY tool_id LIMIT 1", (name,))
        if row is None:
            row = inventory_service.add_item(actor, name=name, category=category, supplier=supplier,
                                             description="Sample item for a course demonstration", location=location,
                                             item_type=kind, unit_of_measure=unit, price=price, quantity=stock)
            inventory_service.update_item(actor, row["tool_id"], name=name, category=category, supplier=supplier,
                                          description="Sample item for a course demonstration", location=location,
                                          item_type=kind, unit_of_measure=unit, price=price, quantity=stock,
                                          min_stock=minimum, tag_id=tag or "")
            counts["tools"] += 1
        tool_ids[name] = row["tool_id"]

    for name, client, site, head, start, end, worker, needs in PROJECTS:
        with db.read() as cur:
            row = _one(cur, "SELECT project_id FROM projects WHERE name=%s AND archived_at IS NULL LIMIT 1", (name,))
        if row is None:
            project_service.create_project(actor, {
                "name": name, "client": client, "location": site, "project_head": head,
                "description": "Sample project for a course demonstration",
                "start_date": (today + timedelta(days=start)).isoformat(),
                "end_date": (today + timedelta(days=end)).isoformat(),
                "workers": [worker_ids[worker]],
                "requirements": [{"tool_id": tool_ids[tool], "qty": qty} for tool, qty in needs],
            })
            counts["projects"] += 1
    return counts, worker_ids


def main(argv=None):
    parser = argparse.ArgumentParser(description="Add sample projects and inventory without changing existing data.")
    parser.add_argument("--apply", action="store_true", help="actually add missing sample records to the database in .env")
    args = parser.parse_args(argv)
    if not (ROOT / ".env").is_file():
        parser.error(".env was not found in the project folder. Set up the application's database connection first.")
    from db.pool import config_from_env
    cfg = config_from_env()
    print(f"Target: {cfg['database']} on {cfg['host']} (no password displayed)")
    print(f"Sample: {len(TOOLS)} inventory items, {len(PROJECTS)} projects, {len(WORKERS)} workers. Existing records are kept.")
    if not args.apply:
        print("Preview only. To add these records, run: python scripts/add_mock_data.py --apply")
        return 0
    try:
        counts, workers = apply()
    except Exception as exc:
        print(f"Could not finish adding sample data: {exc}", file=sys.stderr)
        print("Records already added are kept; rerun the same command after fixing the problem.", file=sys.stderr)
        return 1
    print("Added: {tools} items, {projects} projects, {workers} workers.".format(**counts))
    print("Sample Worker IDs: " + ", ".join(workers))
    print("Restart the application to see the new records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
