"""Product and batch registry, stock adjustments and the Expiry Alert Engine."""
from datetime import date

from . import audit, auth, db


def today_str():
    return date.today().isoformat()


def parse_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError("Dates must be written as YYYY-MM-DD (e.g. 2027-03-31).")


def _number(value, label, integer=False, minimum=0):
    try:
        num = int(str(value).strip()) if integer else float(str(value).strip())
    except ValueError:
        raise ValueError("{} must be a {}.".format(label, "whole number" if integer else "number"))
    if num < minimum:
        raise ValueError("{} cannot be less than {}.".format(label, minimum))
    return num


# ----------------------------------------------------------------- products
def add_product(conn, user, code, name, unit, price, reorder_level):
    auth.require(user, "manage_products")
    code, name, unit = code.strip().upper(), name.strip(), (unit.strip() or "unit")
    if not code or not name:
        raise ValueError("Product code and name are required.")
    price = _number(price, "Price")
    reorder_level = _number(reorder_level, "Reorder level", integer=True)
    try:
        with db.transaction(conn):
            cur = conn.execute(
                "INSERT INTO products(code, name, unit, price, reorder_level) VALUES (?,?,?,?,?)",
                (code, name, unit, price, reorder_level))
            audit.log(conn, user, "PRODUCT_ADDED", "{} {} @ {:.2f}".format(code, name, price))
            return cur.lastrowid
    except db.IntegrityError:
        raise ValueError("A product with code {} already exists.".format(code))


def update_product(conn, user, product_id, name, unit, reorder_level):
    auth.require(user, "manage_products")
    name = name.strip()
    if not name:
        raise ValueError("Product name is required.")
    reorder_level = _number(reorder_level, "Reorder level", integer=True)
    with db.transaction(conn):
        cur = conn.execute("UPDATE products SET name=?, unit=?, reorder_level=? WHERE id=?",
                           (name, unit.strip() or "unit", reorder_level, product_id))
        if cur.rowcount != 1:
            raise ValueError("Product not found.")
        audit.log(conn, user, "PRODUCT_EDITED", "id {} -> {}, reorder level {}".format(
            product_id, name, reorder_level))


def update_product_price(conn, user, product_id, new_price):
    auth.require(user, "change_price")
    new_price = _number(new_price, "Price")
    with db.transaction(conn):
        row = conn.execute("SELECT code, price FROM products WHERE id=?", (product_id,)).fetchone()
        if not row:
            raise ValueError("Product not found.")
        conn.execute("UPDATE products SET price=? WHERE id=?", (new_price, product_id))
        audit.log(conn, user, "PRICE_CHANGED", "{}: {:.2f} -> {:.2f}".format(
            row["code"], row["price"], new_price))


def list_products(conn, search="", today=None):
    today = today or today_str()
    like = "%{}%".format(search.strip())
    return conn.execute(
        """SELECT p.*,
                  COALESCE(SUM(CASE WHEN b.expiry_date >= :t THEN b.quantity END), 0) AS valid_stock,
                  COALESCE(SUM(CASE WHEN b.expiry_date <  :t THEN b.quantity END), 0) AS expired_stock
           FROM products p LEFT JOIN batches b ON b.product_id = p.id
           WHERE p.active = 1 AND (p.name LIKE :s OR p.code LIKE :s)
           GROUP BY p.id ORDER BY p.name""", {"t": today, "s": like}).fetchall()


def low_stock(conn, today=None):
    return [p for p in list_products(conn, "", today)
            if p["reorder_level"] > 0 and p["valid_stock"] <= p["reorder_level"]]


# ------------------------------------------------------------------ batches
def receive_batch(conn, user, product_id, batch_no, expiry_date, quantity, cost_price):
    auth.require(user, "receive_stock")
    batch_no = batch_no.strip().upper()
    if not batch_no:
        raise ValueError("Batch number is required.")
    expiry = parse_date(expiry_date)
    if expiry < date.today():
        raise ValueError("This batch has already expired and cannot be received into stock.")
    quantity = _number(quantity, "Quantity", integer=True, minimum=1)
    cost_price = _number(cost_price, "Cost price")
    try:
        with db.transaction(conn):
            prod = conn.execute("SELECT code FROM products WHERE id=? AND active=1",
                                (product_id,)).fetchone()
            if not prod:
                raise ValueError("Product not found.")
            cur = conn.execute(
                "INSERT INTO batches(product_id, batch_no, expiry_date, quantity, cost_price, received_at)"
                " VALUES (?,?,?,?,?,?)",
                (product_id, batch_no, expiry.isoformat(), quantity, cost_price, db.now_str()))
            audit.log(conn, user, "BATCH_RECEIVED", "{} batch {} qty {} exp {}".format(
                prod["code"], batch_no, quantity, expiry))
            return cur.lastrowid
    except db.IntegrityError:
        raise ValueError("Batch {} already exists for this product. Use 'Adjust batch' to correct it."
                         .format(batch_no))


def batches_for_product(conn, product_id, today=None):
    today = today or today_str()
    rows = conn.execute("SELECT * FROM batches WHERE product_id=? ORDER BY expiry_date, id",
                        (product_id,)).fetchall()
    return [dict(r, status="EXPIRED" if r["expiry_date"] < today else "VALID") for r in rows]


def adjust_batch(conn, user, batch_id, new_quantity, reason):
    auth.require(user, "adjust_stock")
    new_quantity = _number(new_quantity, "New quantity", integer=True)
    reason = reason.strip()
    if not reason:
        raise ValueError("A reason is required for every stock adjustment.")
    with db.transaction(conn):
        row = conn.execute(
            "SELECT b.batch_no, b.quantity, p.code FROM batches b JOIN products p ON p.id=b.product_id "
            "WHERE b.id=?", (batch_id,)).fetchone()
        if not row:
            raise ValueError("Batch not found.")
        conn.execute("UPDATE batches SET quantity=? WHERE id=?", (new_quantity, batch_id))
        audit.log(conn, user, "STOCK_ADJUSTED", "{} batch {}: {} -> {} ({})".format(
            row["code"], row["batch_no"], row["quantity"], new_quantity, reason))


# ------------------------------------------------------- expiry alert engine
def get_thresholds(conn):
    raw = db.get_setting(conn, "alert_thresholds", "90,60,30")
    vals = sorted({int(x) for x in raw.split(",") if x.strip().isdigit() and int(x) > 0})
    return vals or [90, 60, 30]


def set_thresholds(conn, user, text):
    auth.require(user, "manage_settings")
    try:
        vals = sorted({int(x) for x in text.replace(" ", "").split(",") if x}, reverse=True)
    except ValueError:
        raise ValueError("Enter whole numbers separated by commas, e.g. 90,60,30.")
    if not vals or min(vals) < 1:
        raise ValueError("Thresholds must be positive whole numbers of days.")
    with db.transaction(conn):
        db.set_setting(conn, "alert_thresholds", ",".join(str(v) for v in vals))
        audit.log(conn, user, "THRESHOLDS_CHANGED", ",".join(str(v) for v in vals))


def _threshold_for(days_left, thresholds):
    """0 if expired, otherwise the tightest threshold the batch has crossed."""
    if days_left < 0:
        return 0
    for t in thresholds:               # ascending: smallest threshold that still covers it
        if days_left <= t:
            return t
    return None


def expiry_report(conn, today=None):
    """Every batch with stock that is expired or inside the widest alert window."""
    today_d = date.fromisoformat(today) if today else date.today()
    thresholds = get_thresholds(conn)
    out = []
    rows = conn.execute(
        "SELECT b.id AS batch_id, p.code, p.name, b.batch_no, b.expiry_date, b.quantity, b.cost_price "
        "FROM batches b JOIN products p ON p.id=b.product_id "
        "WHERE b.quantity > 0 AND p.active=1 ORDER BY b.expiry_date, p.name").fetchall()
    for r in rows:
        days_left = (date.fromisoformat(r["expiry_date"]) - today_d).days
        t = _threshold_for(days_left, thresholds)
        if t is None:
            continue
        out.append(dict(r, days_left=days_left, threshold=t,
                        status="EXPIRED" if t == 0 else "EXPIRES IN {} DAYS OR LESS".format(t)))
    return out


def run_expiry_check(conn, user=None, today=None):
    """Runs at start-up and daily. Records one alert per batch per threshold crossed."""
    rows = expiry_report(conn, today)
    with db.transaction(conn):
        new = 0
        for r in rows:
            cur = conn.execute(
                "INSERT IGNORE INTO expiry_alerts(batch_id, threshold, raised_on) VALUES (?,?,?)",
                (r["batch_id"], r["threshold"], today or today_str()))
            new += cur.rowcount
        db.set_setting(conn, "last_expiry_check", db.now_str())
        if new:
            audit.log(conn, user, "EXPIRY_ALERTS_RAISED", "{} new alert(s)".format(new))
    expired = sum(1 for r in rows if r["threshold"] == 0)
    return {"expired": expired, "near_expiry": len(rows) - expired,
            "new_alerts": new, "rows": rows}
