"""Optional: load demo users, products and batches so every feature can be shown.
Run once on a fresh database:  python seed_demo.py
Do NOT run this on the live Macmillan database - capture real opening stock instead."""
from datetime import date, timedelta

from hms import auth, db, stock

conn = db.connect()
db.init_db(conn)
auth.ensure_default_admin(conn)
if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]:
    raise SystemExit("Database already has products - demo data not loaded.")

admin = auth.authenticate(conn, "admin", "admin123")
if not admin:
    raise SystemExit("Default admin password has been changed; log in through the app instead.")
auth.create_user(conn, admin, "pharmacist", "Demo Pharmacist", "pharmacist", "pharm123")
auth.create_user(conn, admin, "cashier", "Demo Cashier", "cashier", "cash123")
pharm = auth.authenticate(conn, "pharmacist", "pharm123")


def d(days):
    return (date.today() + timedelta(days=days)).isoformat()


catalogue = [
    ("PARA500", "Paracetamol 500mg", "tab", 5, 200, [("PA-101", d(25), 300, 2), ("PA-102", d(240), 800, 2)]),
    ("AMOX250", "Amoxicillin 250mg", "cap", 12, 100, [("AM-77", d(55), 150, 6), ("AM-78", d(400), 300, 6)]),
    ("ORS", "Oral Rehydration Salts", "sachet", 20, 50, [("OR-9", d(80), 40, 9)]),
    ("SYR-COF", "Cough Syrup 100ml", "bottle", 150, 20, [("CS-5", d(150), 18, 90)]),
    ("GLOVE-M", "Examination Gloves (M)", "box", 450, 10, [("GL-1", d(700), 60, 300)]),
]
for code, name, unit, price, reorder, batches in catalogue:
    pid = stock.add_product(conn, pharm, code, name, unit, price, reorder)
    for batch_no, expiry, qty, cost in batches:
        stock.receive_batch(conn, pharm, pid, batch_no, expiry, qty, cost)

# stock that aged on the shelf (as happens in real life) so the expiry block can be demonstrated
pid = conn.execute("SELECT id FROM products WHERE code='ORS'").fetchone()[0]
conn.execute("INSERT INTO batches(product_id,batch_no,expiry_date,quantity,cost_price,received_at) "
             "VALUES (?,?,?,?,?,?)", (pid, "OR-OLD", d(-12), 25, 9, db.now_str()))
print("Demo data loaded.\n  admin / admin123\n  pharmacist / pharm123\n  cashier / cash123")
