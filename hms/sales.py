"""POS billing: FEFO allocation, real-time stock deduction, voids and returns."""
import secrets

from . import audit, auth, db, stock

RECEIPT_WIDTH = 46


class SaleError(db.HMSError):
    pass


def available_stock(conn, product_id, today=None):
    today = today or stock.today_str()
    return conn.execute("SELECT COALESCE(SUM(quantity),0) FROM batches "
                        "WHERE product_id=? AND expiry_date>=?", (product_id, today)).fetchone()[0]


def allocate_fefo(conn, product_id, qty, today=None):
    """First-Expired, First-Out: earliest-expiring VALID batches first, splitting across batches.
    Expired batches are never considered."""
    today = today or stock.today_str()
    rows = conn.execute(
        "SELECT id, batch_no, expiry_date, quantity FROM batches "
        "WHERE product_id=? AND quantity>0 AND expiry_date>=? ORDER BY expiry_date, id FOR UPDATE",
        (product_id, today)).fetchall()
    need, plan = qty, []
    for r in rows:
        if need == 0:
            break
        take = min(need, r["quantity"])
        plan.append((r["id"], r["batch_no"], r["expiry_date"], take))
        need -= take
    if need > 0:
        name = conn.execute("SELECT name FROM products WHERE id=?", (product_id,)).fetchone()["name"]
        expired = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM batches "
                               "WHERE product_id=? AND expiry_date<?", (product_id, today)).fetchone()[0]
        msg = "Not enough valid stock of {}: requested {}, available {}.".format(
            name, qty, qty - need)
        if expired:
            msg += " {} expired unit(s) are blocked from sale.".format(expired)
        raise SaleError(msg)
    return plan


def create_sale(conn, user, items, customer=""):
    """items: iterable of (product_id, quantity). One transaction: allocation, line items,
    stock deduction and audit entry either all happen or none do."""
    auth.require(user, "sell")
    merged = {}
    for pid, qty in items:
        qty = int(qty)
        if qty <= 0:
            raise SaleError("Quantities must be positive.")
        merged[pid] = merged.get(pid, 0) + qty
    if not merged:
        raise SaleError("The cart is empty.")

    with db.transaction(conn):
        today = stock.today_str()
        lines, total = [], 0.0
        for pid, qty in merged.items():
            prod = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
            if not prod:
                raise SaleError("Product not found.")
            for bid, _bno, _exp, take in allocate_fefo(conn, pid, qty, today):
                line = round(take * prod["price"], 2)
                lines.append((pid, bid, take, prod["price"], line))
                total += line
        total = round(total, 2)
        # the receipt number contains the sale id, so insert first with a temporary number
        cur = conn.execute(
            "INSERT INTO sales(receipt_no, sold_at, cashier_id, customer, total) VALUES (?,?,?,?,?)",
            ("TMP-" + secrets.token_hex(8), db.now_str(), user["id"], customer.strip(), total))
        sale_id = cur.lastrowid
        receipt_no = "RC-{}-{:05d}".format(today.replace("-", ""), sale_id)
        conn.execute("UPDATE sales SET receipt_no=? WHERE id=?", (receipt_no, sale_id))
        for pid, bid, take, price, line in lines:
            conn.execute("INSERT INTO sale_items(sale_id, product_id, batch_id, quantity, unit_price, "
                         "line_total) VALUES (?,?,?,?,?,?)", (sale_id, pid, bid, take, price, line))
            upd = conn.execute("UPDATE batches SET quantity = quantity - ? WHERE id=? AND quantity >= ?",
                               (take, bid, take))
            if upd.rowcount != 1:
                raise SaleError("Stock changed during the sale. Please try again.")
        audit.log(conn, user, "SALE", "{} total {:.2f}".format(receipt_no, total))
        low = [p["name"] for p in stock.list_products(conn, "", today)
               if p["id"] in merged and p["reorder_level"] > 0 and p["valid_stock"] <= p["reorder_level"]]
    return {"sale_id": sale_id, "receipt_no": receipt_no, "total": total, "low_stock": low}


# ------------------------------------------------- voids and returns (authorised)
def void_sale(conn, authoriser, sale_id, reason, requested_by=None):
    auth.require(authoriser, "authorise_reversal")
    reason = reason.strip()
    if not reason:
        raise SaleError("A reason is required to void a sale.")
    with db.transaction(conn):
        sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        if not sale:
            raise SaleError("Sale not found.")
        if sale["status"] != "COMPLETED":
            raise SaleError("This sale has already been voided.")
        if conn.execute("SELECT COUNT(*) FROM returns r JOIN sale_items si ON si.id=r.sale_item_id "
                        "WHERE si.sale_id=?", (sale_id,)).fetchone()[0]:
            raise SaleError("This sale already has returns and can no longer be voided.")
        for it in conn.execute("SELECT batch_id, quantity FROM sale_items WHERE sale_id=?", (sale_id,)):
            conn.execute("UPDATE batches SET quantity = quantity + ? WHERE id=?",
                         (it["quantity"], it["batch_id"]))
        conn.execute("UPDATE sales SET status='VOIDED', void_reason=?, voided_by=?, voided_at=? WHERE id=?",
                     (reason, authoriser["id"], db.now_str(), sale_id))
        by = " (requested by {})".format(requested_by["username"]) if requested_by else ""
        audit.log(conn, authoriser, "SALE_VOIDED", "{}: {}{}".format(sale["receipt_no"], reason, by))


def return_item(conn, authoriser, sale_item_id, qty, reason, requested_by=None):
    auth.require(authoriser, "authorise_reversal")
    reason = reason.strip()
    if not reason:
        raise SaleError("A reason is required for a return.")
    qty = int(qty)
    if qty <= 0:
        raise SaleError("Return quantity must be positive.")
    with db.transaction(conn):
        it = conn.execute(
            "SELECT si.*, s.status, s.receipt_no FROM sale_items si JOIN sales s ON s.id=si.sale_id "
            "WHERE si.id=?", (sale_item_id,)).fetchone()
        if not it:
            raise SaleError("Sale item not found.")
        if it["status"] != "COMPLETED":
            raise SaleError("Items on a voided sale cannot be returned.")
        done = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM returns WHERE sale_item_id=?",
                            (sale_item_id,)).fetchone()[0]
        if qty > it["quantity"] - done:
            raise SaleError("Only {} unit(s) of this item can still be returned.".format(
                it["quantity"] - done))
        refund = round(qty * it["unit_price"], 2)
        conn.execute("UPDATE batches SET quantity = quantity + ? WHERE id=?", (qty, it["batch_id"]))
        conn.execute("INSERT INTO returns(sale_item_id, quantity, refund, reason, authorised_by, returned_at)"
                     " VALUES (?,?,?,?,?,?)",
                     (sale_item_id, qty, refund, reason, authoriser["id"], db.now_str()))
        by = " (requested by {})".format(requested_by["username"]) if requested_by else ""
        audit.log(conn, authoriser, "ITEM_RETURNED", "{}: {} x item {} refund {:.2f}, {}{}".format(
            it["receipt_no"], qty, sale_item_id, refund, reason, by))
        return refund


# ----------------------------------------------------- archive, search, receipt
def get_sale(conn, sale_id):
    sale = conn.execute(
        "SELECT s.*, u.username AS cashier, u.full_name AS cashier_name FROM sales s "
        "JOIN users u ON u.id=s.cashier_id WHERE s.id=?", (sale_id,)).fetchone()
    if not sale:
        raise SaleError("Sale not found.")
    items = conn.execute(
        "SELECT si.id, p.code, p.name, b.batch_no, b.expiry_date, si.quantity, si.unit_price, "
        "si.line_total, COALESCE((SELECT SUM(quantity) FROM returns r WHERE r.sale_item_id=si.id),0) "
        "AS returned_qty FROM sale_items si JOIN products p ON p.id=si.product_id "
        "JOIN batches b ON b.id=si.batch_id WHERE si.sale_id=? ORDER BY si.id", (sale_id,)).fetchall()
    return dict(sale), [dict(i) for i in items]


def search_sales(conn, ref="", item="", date_from="", date_to="", cashier="", limit=500):
    sql = ("SELECT s.id, s.receipt_no, s.sold_at, u.username AS cashier, s.customer, s.total, s.status, "
           "(SELECT COALESCE(SUM(r.refund),0) FROM returns r JOIN sale_items si ON si.id=r.sale_item_id "
           " WHERE si.sale_id=s.id) AS refunds "
           "FROM sales s JOIN users u ON u.id=s.cashier_id WHERE 1=1")
    args = []
    if ref.strip():
        if ref.strip().isdigit():                      # a plain number means the sale ID
            sql += " AND s.id = ?"
            args.append(int(ref.strip()))
        else:                                          # otherwise match the receipt number
            sql += " AND s.receipt_no LIKE ?"
            args.append("%{}%".format(ref.strip()))
    if item.strip():
        sql += (" AND EXISTS (SELECT 1 FROM sale_items si JOIN products p ON p.id=si.product_id "
                "WHERE si.sale_id=s.id AND (p.name LIKE ? OR p.code LIKE ?))")
        args += ["%{}%".format(item.strip())] * 2
    if date_from.strip():
        stock.parse_date(date_from)
        sql += " AND DATE(s.sold_at) >= ?"
        args.append(date_from.strip())
    if date_to.strip():
        stock.parse_date(date_to)
        sql += " AND DATE(s.sold_at) <= ?"
        args.append(date_to.strip())
    if cashier.strip():
        sql += " AND (u.username LIKE ? OR u.full_name LIKE ?)"
        args += ["%{}%".format(cashier.strip())] * 2
    sql += " ORDER BY s.id DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()


def receipt_text(conn, sale_id):
    sale, items = get_sale(conn, sale_id)
    w = RECEIPT_WIDTH
    out = ["MACMILLAN COMPANY".center(w), "Kiambu County, Kenya".center(w), "",
           "Receipt : " + sale["receipt_no"], "Date    : " + sale["sold_at"],
           "Cashier : " + sale["cashier_name"]]
    if sale["customer"]:
        out.append("Customer: " + sale["customer"])
    out += ["-" * w, "{:<22}{:>4}{:>9}{:>11}".format("Item", "Qty", "Price", "Total"), "-" * w]
    for it in items:
        out.append("{:<22}{:>4}{:>9.2f}{:>11.2f}".format(it["name"][:21], it["quantity"],
                                                          it["unit_price"], it["line_total"]))
        note = "  batch {} exp {}".format(it["batch_no"], it["expiry_date"])
        if it["returned_qty"]:
            note += "  (returned {})".format(it["returned_qty"])
        out.append(note)
    out.append("-" * w)
    out.append("{:<{a}}{:>{b}.2f}".format("TOTAL (KSh)", sale["total"], a=w - 12, b=12))
    refunds = conn.execute("SELECT COALESCE(SUM(r.refund),0) FROM returns r JOIN sale_items si ON "
                           "si.id=r.sale_item_id WHERE si.sale_id=?", (sale_id,)).fetchone()[0]
    if refunds:
        out.append("{:<{a}}{:>{b}.2f}".format("Refunded", -refunds, a=w - 12, b=12))
    if sale["status"] == "VOIDED":
        out += ["", "*** VOIDED: {} ***".format(sale["void_reason"]).center(w)]
    out += ["", "Thank you for your business.".center(w)]
    return "\n".join(out)
