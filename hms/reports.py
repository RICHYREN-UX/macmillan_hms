"""Management reports. Each returns (headers, rows) so the GUI and CSV export share one path."""
import csv

from . import stock


def sales_summary(conn, date_from, date_to):
    stock.parse_date(date_from)
    stock.parse_date(date_to)
    days = {}
    for r in conn.execute(
            "SELECT DATE_FORMAT(sold_at, '%Y-%m-%d') d, COUNT(*) n, SUM(total) g FROM sales "
            "WHERE status='COMPLETED' AND DATE(sold_at) BETWEEN ? AND ? GROUP BY d", (date_from, date_to)):
        days[r["d"]] = [r["n"], r["g"], 0.0]
    for r in conn.execute(
            "SELECT DATE_FORMAT(r.returned_at, '%Y-%m-%d') d, SUM(r.refund) f FROM returns r WHERE "
            "DATE(r.returned_at) BETWEEN ? AND ? GROUP BY d", (date_from, date_to)):
        days.setdefault(r["d"], [0, 0.0, 0.0])[2] = r["f"]
    rows, tn, tg, tf = [], 0, 0.0, 0.0
    for d in sorted(days):
        n, g, f = days[d]
        rows.append((d, n, "{:,.2f}".format(g), "{:,.2f}".format(f), "{:,.2f}".format(g - f)))
        tn, tg, tf = tn + n, tg + g, tf + f
    rows.append(("TOTAL", tn, "{:,.2f}".format(tg), "{:,.2f}".format(tf), "{:,.2f}".format(tg - tf)))
    return ["Date", "Sales", "Gross (KSh)", "Refunds (KSh)", "Net (KSh)"], rows


def stock_valuation(conn, today=None):
    today = today or stock.today_str()
    rows = conn.execute(
        """SELECT p.code, p.name,
                  COALESCE(SUM(CASE WHEN b.expiry_date>=:t THEN b.quantity END),0) vq,
                  COALESCE(SUM(CASE WHEN b.expiry_date>=:t THEN b.quantity*b.cost_price END),0) vcost,
                  COALESCE(SUM(CASE WHEN b.expiry_date>=:t THEN b.quantity*p.price END),0) vretail,
                  COALESCE(SUM(CASE WHEN b.expiry_date<:t THEN b.quantity END),0) eq,
                  COALESCE(SUM(CASE WHEN b.expiry_date<:t THEN b.quantity*b.cost_price END),0) ecost
           FROM products p LEFT JOIN batches b ON b.product_id=p.id WHERE p.active=1
           GROUP BY p.id ORDER BY p.name""", {"t": today}).fetchall()
    out = [(r["code"], r["name"], r["vq"], "{:,.2f}".format(r["vcost"]), "{:,.2f}".format(r["vretail"]),
            r["eq"], "{:,.2f}".format(r["ecost"])) for r in rows]
    out.append(("TOTAL", "", sum(r["vq"] for r in rows), "{:,.2f}".format(sum(r["vcost"] for r in rows)),
                "{:,.2f}".format(sum(r["vretail"] for r in rows)), sum(r["eq"] for r in rows),
                "{:,.2f}".format(sum(r["ecost"] for r in rows))))
    return (["Code", "Product", "Valid qty", "Cost value", "Retail value", "Expired qty",
             "Expired cost (loss)"], out)


def expiry_report(conn):
    rows = [(r["code"], r["name"], r["batch_no"], r["expiry_date"], r["days_left"], r["quantity"],
             r["status"]) for r in stock.expiry_report(conn)]
    return ["Code", "Product", "Batch", "Expiry", "Days left", "Qty", "Status"], rows


def export_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)
