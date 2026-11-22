"""Tkinter desktop interface. Tabs are shown according to the signed-in user's role (RBAC)."""
import os
import sys
import traceback
import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from . import audit, auth, backup, db, reports, sales, stock

APP_TITLE = "Macmillan Company - Hospital Sales Management System"
NAVY, BLUE, SKY, PALE, WHITE = "#0B2A5B", "#1565C0", "#2F80ED", "#F2F6FC", "#FFFFFF"
ICONS = {"sell": "\U0001F6D2", "manage_products": "\U0001F4E6", "view_expiry": "\u23F0",
         "search_sales": "\U0001F9FE", "view_reports": "\U0001F4CA", "manage_users": "\u2699",
         "view_audit": "\U0001F4DC"}
EXPECTED = (ValueError, db.HMSError, db.DatabaseError)



def setup_style(root):
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=PALE)
    base = ("Segoe UI", 10)
    st.configure(".", font=base, background=PALE)
    st.configure("TFrame", background=PALE)
    st.configure("TLabel", background=PALE)
    st.configure("TLabelframe", background=PALE, bordercolor="#C5D3EA")
    st.configure("TLabelframe.Label", background=PALE, foreground=BLUE, font=("Segoe UI", 10, "bold"))
    st.configure("TButton", background=BLUE, foreground=WHITE, padding=(12, 6), borderwidth=0, focusthickness=0)
    st.map("TButton", background=[("active", SKY), ("pressed", NAVY)])
    st.configure("TEntry", padding=5, fieldbackground=WHITE)
    st.configure("TCombobox", padding=4)
    st.configure("Treeview", rowheight=28, background=WHITE, fieldbackground=WHITE, bordercolor="#C5D3EA")
    st.map("Treeview", background=[("selected", SKY)], foreground=[("selected", WHITE)])
    st.configure("Treeview.Heading", background=NAVY, foreground=WHITE, padding=6, font=("Segoe UI", 10, "bold"))
    st.map("Treeview.Heading", background=[("active", BLUE)])
    st.configure("Card.TFrame", background=WHITE)
    st.configure("Card.TLabel", background=WHITE, foreground="#33415C")
    st.configure("Login.TButton", background=BLUE, foreground=WHITE, padding=(10, 9), font=("Segoe UI", 11, "bold"))
    st.map("Login.TButton", background=[("active", SKY), ("pressed", NAVY)])
    st.configure("Nav.TButton", background=NAVY, foreground="#CFE0FA", anchor="w", padding=(18, 12),
                 font=("Segoe UI", 11), borderwidth=0)
    st.map("Nav.TButton", background=[("active", "#173F82")], foreground=[("active", WHITE)])
    st.configure("NavOn.TButton", background=BLUE, foreground=WHITE, anchor="w", padding=(18, 12),
                 font=("Segoe UI", 11, "bold"), borderwidth=0)
    st.map("NavOn.TButton", background=[("active", BLUE)])
    st.configure("Side.TButton", background="#173F82", foreground=WHITE, anchor="w", padding=(18, 9), borderwidth=0)
    st.map("Side.TButton", background=[("active", SKY)])

# ------------------------------------------------------------------ helpers
def make_tree(parent, columns, height=10, expand=True):
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=expand, padx=4, pady=4)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                        height=height, selectmode="browse")
    for cid, heading, width in columns:
        tree.heading(cid, text=heading)
        tree.column(cid, width=width, anchor="w")
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return tree


def fill_tree(tree, headers, rows):
    ids = ["c{}".format(i) for i in range(len(headers))]
    tree["columns"] = ids
    tree["show"] = "headings"
    for cid, head in zip(ids, headers):
        tree.heading(cid, text=head)
        tree.column(cid, width=max(90, min(260, len(head) * 11)), anchor="w")
    tree.delete(*tree.get_children())
    for row in rows:
        tree.insert("", "end", values=row)


def selected_id(tree):
    sel = tree.selection()
    return int(sel[0]) if sel else None


def money(value):
    return "{:,.2f}".format(value)


class FormDialog(tk.Toplevel):
    """Small modal form. fields = [(key, label, default[, 'password' | [choices]])]."""

    def __init__(self, parent, title, fields, on_submit, submit_label="Save"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.on_submit = on_submit
        self.vars = {}
        first = None
        for i, f in enumerate(fields):
            key, label, default = f[0], f[1], f[2]
            opt = f[3] if len(f) > 3 else None
            ttk.Label(self, text=label).grid(row=i, column=0, sticky="w", padx=10, pady=5)
            var = tk.StringVar(value=str(default))
            if isinstance(opt, (list, tuple)):
                widget = ttk.Combobox(self, textvariable=var, values=opt, state="readonly", width=30)
            else:
                widget = ttk.Entry(self, textvariable=var, width=33, show="*" if opt == "password" else "")
            widget.grid(row=i, column=1, padx=10, pady=5)
            self.vars[key] = var
            first = first or widget
        row = ttk.Frame(self)
        row.grid(row=len(fields), column=0, columnspan=2, pady=10)
        ttk.Button(row, text=submit_label, command=self.submit).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        self.bind("<Return>", lambda e: self.submit())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        first.focus_set()

    def submit(self):
        try:
            self.on_submit({k: v.get() for k, v in self.vars.items()})
        except EXPECTED as exc:
            messagebox.showerror("Cannot continue", str(exc), parent=self)
            return
        self.destroy()


def ask(parent, title, fields, on_submit, submit_label="Save"):
    dlg = FormDialog(parent, title, fields, on_submit, submit_label)
    parent.wait_window(dlg)


# ------------------------------------------------------------ sale / receipt
class SaleWindow(tk.Toplevel):
    """Receipt viewer with print, authorised return and authorised void."""

    def __init__(self, app, sale_id, on_change=None):
        super().__init__(app)
        self.app, self.sale_id, self.on_change = app, sale_id, on_change
        self.title("Receipt")
        self.geometry("560x640")
        self.text = tk.Text(self, font=("Courier New", 10), height=22, wrap="none")
        self.text.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Label(self, text="Items (select one to return it):").pack(anchor="w", padx=8)
        self.items = make_tree(self, [("name", "Item", 200), ("qty", "Sold", 60),
                                      ("ret", "Returned", 70), ("batch", "Batch", 90)],
                               height=4, expand=False)
        bar = ttk.Frame(self)
        bar.pack(pady=8)
        ttk.Button(bar, text="Print", command=self.print_receipt).pack(side="left", padx=4)
        ttk.Button(bar, text="Return selected item", command=self.do_return).pack(side="left", padx=4)
        ttk.Button(bar, text="Void sale", command=self.do_void).pack(side="left", padx=4)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.reload()

    def reload(self):
        conn = self.app.conn
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", sales.receipt_text(conn, self.sale_id))
        self.text.configure(state="disabled")
        _, items = sales.get_sale(conn, self.sale_id)
        self.items.delete(*self.items.get_children())
        for it in items:
            self.items.insert("", "end", iid=str(it["id"]),
                              values=(it["name"], it["quantity"], it["returned_qty"], it["batch_no"]))

    def save_receipt(self):
        sale, _ = sales.get_sale(self.app.conn, self.sale_id)
        folder = os.path.join(db.DATA_DIR, "receipts")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, sale["receipt_no"] + ".txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sales.receipt_text(self.app.conn, self.sale_id))
        return path

    def print_receipt(self):
        path = self.save_receipt()
        if sys.platform.startswith("win"):
            try:
                os.startfile(path, "print")                  # default printer
                return
            except OSError as exc:
                messagebox.showwarning("Print", "Could not print: {}".format(exc), parent=self)
        messagebox.showinfo("Receipt saved", "Receipt saved to:\n" + path, parent=self)

    def _changed(self):
        self.reload()
        if self.on_change:
            self.on_change()

    def do_return(self):
        item_id = selected_id(self.items)
        if item_id is None:
            messagebox.showinfo("Return", "Select an item first.", parent=self)
            return
        supervisor = self.app.get_authoriser(self)
        if not supervisor:
            return

        def submit(data):
            refund = sales.return_item(self.app.conn, supervisor, item_id, data["qty"],
                                       data["reason"], requested_by=self.app.user)
            messagebox.showinfo("Return recorded", "Refund due: KSh {}".format(money(refund)), parent=self)

        ask(self, "Return item", [("qty", "Quantity returned", "1"), ("reason", "Reason", "")],
            submit, "Record return")
        self._changed()

    def do_void(self):
        supervisor = self.app.get_authoriser(self)
        if not supervisor:
            return

        def submit(data):
            sales.void_sale(self.app.conn, supervisor, self.sale_id, data["reason"],
                            requested_by=self.app.user)

        ask(self, "Void sale", [("reason", "Reason", "")], submit, "Void sale")
        self._changed()


# ---------------------------------------------------------------------- tabs
class POSTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.cart = app, {}
        left = ttk.LabelFrame(self, text="1. Find product (double-click to add)")
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.query = tk.StringVar()
        entry = ttk.Entry(left, textvariable=self.query)
        entry.pack(fill="x", padx=6, pady=6)
        self.query.trace_add("write", lambda *a: self.search())
        self.products = make_tree(left, [("code", "Code", 70), ("name", "Product", 200),
                                         ("price", "Price", 70), ("stock", "Valid stock", 80)])
        self.products.tag_configure("out", foreground="#999999")
        self.products.bind("<Double-1>", lambda e: self.add())
        row = ttk.Frame(left)
        row.pack(pady=6)
        ttk.Label(row, text="Quantity:").pack(side="left")
        self.qty = tk.StringVar(value="1")
        ttk.Spinbox(row, from_=1, to=9999, width=6, textvariable=self.qty).pack(side="left", padx=6)
        ttk.Button(row, text="Add to cart", command=self.add).pack(side="left")

        right = ttk.LabelFrame(self, text="2. Cart")
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.cart_tree = make_tree(right, [("name", "Product", 190), ("qty", "Qty", 50),
                                           ("price", "Price", 70), ("total", "Total", 80)])
        row = ttk.Frame(right)
        row.pack(fill="x", padx=6)
        ttk.Button(row, text="Remove selected", command=self.remove).pack(side="left")
        ttk.Button(row, text="Clear", command=self.clear).pack(side="left", padx=6)
        cust = ttk.Frame(right)
        cust.pack(fill="x", padx=6, pady=6)
        ttk.Label(cust, text="Customer (optional):").pack(side="left")
        self.customer = tk.StringVar()
        ttk.Entry(cust, textvariable=self.customer).pack(side="left", fill="x", expand=True, padx=6)
        self.total_var = tk.StringVar(value="TOTAL: KSh 0.00")
        ttk.Label(right, textvariable=self.total_var, font=("Segoe UI", 16, "bold")).pack(pady=6)
        ttk.Button(right, text="Complete sale and print receipt", command=self.complete).pack(pady=6, ipadx=10, ipady=6)
        ttk.Label(right, text="Stock is taken automatically from the earliest-expiring valid batch.\n"
                              "Expired batches are rejected.", foreground="#555555").pack(pady=4)

    def refresh(self):
        self.search()

    def search(self):
        self.products.delete(*self.products.get_children())
        for p in stock.list_products(self.app.conn, self.query.get()):
            self.products.insert("", "end", iid=str(p["id"]), tags=("out",) if p["valid_stock"] == 0 else (),
                                 values=(p["code"], p["name"], money(p["price"]), p["valid_stock"]))

    def add(self):
        pid = selected_id(self.products)
        if pid is None:
            messagebox.showinfo("Add to cart", "Select a product first.")
            return
        try:
            qty = int(self.qty.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Quantity", "Enter a whole number greater than zero.")
            return
        prod = self.app.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        have = sales.available_stock(self.app.conn, pid)
        in_cart = self.cart.get(pid, {}).get("qty", 0)
        if qty + in_cart > have:
            expired = self.app.conn.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM batches WHERE product_id=? AND expiry_date<?",
                (pid, stock.today_str())).fetchone()[0]
            note = "\n{} expired unit(s) are blocked from sale.".format(expired) if expired else ""
            messagebox.showerror("Not enough valid stock", "{}: only {} valid unit(s) available "
                                 "({} already in cart).{}".format(prod["name"], have, in_cart, note))
            return
        line = self.cart.setdefault(pid, {"name": prod["name"], "price": prod["price"], "qty": 0})
        line["qty"] += qty
        self.redraw()

    def redraw(self):
        self.cart_tree.delete(*self.cart_tree.get_children())
        total = 0.0
        for pid, l in self.cart.items():
            lt = round(l["qty"] * l["price"], 2)
            total += lt
            self.cart_tree.insert("", "end", iid=str(pid),
                                  values=(l["name"], l["qty"], money(l["price"]), money(lt)))
        self.total_var.set("TOTAL: KSh {}".format(money(total)))

    def remove(self):
        pid = selected_id(self.cart_tree)
        if pid is not None:
            self.cart.pop(pid, None)
            self.redraw()

    def clear(self):
        self.cart.clear()
        self.redraw()

    def complete(self):
        if not self.cart:
            messagebox.showinfo("Cart", "The cart is empty.")
            return
        try:
            result = sales.create_sale(self.app.conn, self.app.user,
                                       [(pid, l["qty"]) for pid, l in self.cart.items()],
                                       self.customer.get())
        except EXPECTED as exc:
            messagebox.showerror("Sale not completed", str(exc))
            self.search()
            return
        self.cart.clear()
        self.customer.set("")
        self.redraw()
        self.search()
        SaleWindow(self.app, result["sale_id"])
        if result["low_stock"]:
            messagebox.showwarning("Low stock", "Reorder soon:\n- " + "\n- ".join(result["low_stock"]))


class StockTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)
        self.query = tk.StringVar()
        ttk.Label(top, text="Search:").pack(side="left")
        ttk.Entry(top, textvariable=self.query, width=24).pack(side="left", padx=6)
        self.query.trace_add("write", lambda *a: self.refresh())
        u = app.user
        for perm, label, cmd in (("manage_products", "New product", self.new_product),
                                 ("manage_products", "Edit product", self.edit_product),
                                 ("change_price", "Change price", self.change_price),
                                 ("receive_stock", "Receive batch", self.receive),
                                 ("adjust_stock", "Adjust batch", self.adjust)):
            if auth.has(u, perm):
                ttk.Button(top, text=label, command=cmd).pack(side="left", padx=3)
        self.tree = make_tree(self, [("code", "Code", 80), ("name", "Product", 230), ("unit", "Unit", 60),
                                     ("price", "Price", 80), ("valid", "Valid stock", 90),
                                     ("expired", "Expired", 70), ("reorder", "Reorder lvl", 80),
                                     ("flag", "Status", 110)], height=9)
        self.tree.tag_configure("low", background="#fff3cd")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_batches())
        ttk.Label(self, text="Batches of the selected product (earliest expiry is sold first):").pack(anchor="w", padx=8)
        self.batches = make_tree(self, [("batch", "Batch no.", 120), ("expiry", "Expiry", 100),
                                        ("qty", "Quantity", 80), ("cost", "Cost price", 90),
                                        ("received", "Received", 150), ("status", "Status", 90)], height=6)
        self.batches.tag_configure("expired", background="#f8d7da")

    def refresh(self):
        keep = selected_id(self.tree)
        self.tree.delete(*self.tree.get_children())
        for p in stock.list_products(self.app.conn, self.query.get()):
            low = p["reorder_level"] > 0 and p["valid_stock"] <= p["reorder_level"]
            self.tree.insert("", "end", iid=str(p["id"]), tags=("low",) if low else (),
                             values=(p["code"], p["name"], p["unit"], money(p["price"]), p["valid_stock"],
                                     p["expired_stock"], p["reorder_level"], "LOW STOCK" if low else "OK"))
        if keep and self.tree.exists(str(keep)):
            self.tree.selection_set(str(keep))
        self.show_batches()

    def show_batches(self):
        self.batches.delete(*self.batches.get_children())
        pid = selected_id(self.tree)
        if pid is None:
            return
        for b in stock.batches_for_product(self.app.conn, pid):
            self.batches.insert("", "end", iid=str(b["id"]), tags=("expired",) if b["status"] == "EXPIRED" else (),
                                values=(b["batch_no"], b["expiry_date"], b["quantity"], money(b["cost_price"]),
                                        b["received_at"], b["status"]))

    def _need_product(self):
        pid = selected_id(self.tree)
        if pid is None:
            messagebox.showinfo("Stock", "Select a product first.")
        return pid

    def new_product(self):
        ask(self, "New product",
            [("code", "Code", ""), ("name", "Name", ""), ("unit", "Unit (tab, vial...)", "unit"),
             ("price", "Selling price (KSh)", ""), ("reorder", "Reorder level", "0")],
            lambda d: stock.add_product(self.app.conn, self.app.user, d["code"], d["name"], d["unit"],
                                        d["price"], d["reorder"]))
        self.refresh()

    def edit_product(self):
        pid = self._need_product()
        if pid is None:
            return
        p = self.app.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        ask(self, "Edit product", [("name", "Name", p["name"]), ("unit", "Unit", p["unit"]),
                                   ("reorder", "Reorder level", p["reorder_level"])],
            lambda d: stock.update_product(self.app.conn, self.app.user, pid, d["name"], d["unit"], d["reorder"]))
        self.refresh()

    def change_price(self):
        pid = self._need_product()
        if pid is None:
            return
        p = self.app.conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        ask(self, "Change price - " + p["name"], [("price", "New price (KSh)", p["price"])],
            lambda d: stock.update_product_price(self.app.conn, self.app.user, pid, d["price"]))
        self.refresh()

    def receive(self):
        pid = self._need_product()
        if pid is None:
            return
        ask(self, "Receive new batch",
            [("batch", "Batch number", ""), ("expiry", "Expiry date (YYYY-MM-DD)", ""),
             ("qty", "Quantity received", ""), ("cost", "Cost price per unit (KSh)", "0")],
            lambda d: stock.receive_batch(self.app.conn, self.app.user, pid, d["batch"], d["expiry"],
                                          d["qty"], d["cost"]), "Receive")
        self.refresh()

    def adjust(self):
        bid = selected_id(self.batches)
        if bid is None:
            messagebox.showinfo("Stock", "Select a batch in the lower table first.")
            return
        b = self.app.conn.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
        ask(self, "Adjust batch {} (now {})".format(b["batch_no"], b["quantity"]),
            [("qty", "Correct quantity", b["quantity"]), ("reason", "Reason (required)", "")],
            lambda d: stock.adjust_batch(self.app.conn, self.app.user, bid, d["qty"], d["reason"]))
        self.refresh()


class ExpiryTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)
        self.summary = tk.StringVar()
        ttk.Label(top, textvariable=self.summary, font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="Run expiry check now", command=self.run_check).pack(side="right", padx=4)
        if auth.has(app.user, "manage_settings"):
            ttk.Button(top, text="Alert thresholds...", command=self.thresholds).pack(side="right", padx=4)
        ttk.Label(self, text="Expired and near-expiry batches (expired stock cannot be sold):").pack(anchor="w", padx=8)
        self.tree = make_tree(self, [("code", "Code", 70), ("name", "Product", 200), ("batch", "Batch", 90),
                                     ("expiry", "Expiry", 90), ("days", "Days left", 70), ("qty", "Qty", 60),
                                     ("status", "Status", 200)], height=10)
        self.tree.tag_configure("expired", background="#f8d7da")
        self.tree.tag_configure("urgent", background="#ffe5b4")
        self.tree.tag_configure("soon", background="#fff3cd")
        ttk.Label(self, text="Low-stock warnings (at or below reorder level):").pack(anchor="w", padx=8)
        self.low = make_tree(self, [("code", "Code", 70), ("name", "Product", 240), ("valid", "Valid stock", 90),
                                    ("reorder", "Reorder level", 100)], height=5)

    def refresh(self):
        conn = self.app.conn
        rows = stock.expiry_report(conn)
        smallest = stock.get_thresholds(conn)[0]
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            tag = "expired" if r["threshold"] == 0 else ("urgent" if r["threshold"] <= smallest else "soon")
            self.tree.insert("", "end", iid=str(i), tags=(tag,),
                             values=(r["code"], r["name"], r["batch_no"], r["expiry_date"],
                                     r["days_left"], r["quantity"], r["status"]))
        self.low.delete(*self.low.get_children())
        for p in stock.low_stock(conn):
            self.low.insert("", "end", iid=str(p["id"]),
                            values=(p["code"], p["name"], p["valid_stock"], p["reorder_level"]))
        expired = sum(1 for r in rows if r["threshold"] == 0)
        self.summary.set("{} expired batch(es), {} near expiry. Last check: {}".format(
            expired, len(rows) - expired, db.get_setting(conn, "last_expiry_check") or "never"))

    def run_check(self):
        stock.run_expiry_check(self.app.conn, self.app.user)
        self.refresh()

    def thresholds(self):
        ask(self, "Alert thresholds", [("t", "Days before expiry (comma separated)",
                                        ",".join(str(t) for t in reversed(stock.get_thresholds(self.app.conn))))],
            lambda d: stock.set_thresholds(self.app.conn, self.app.user, d["t"]))
        self.run_check()


class ArchiveTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        form = ttk.LabelFrame(self, text="Search sales")
        form.pack(fill="x", padx=6, pady=6)
        self.vars = {}
        for i, (key, label, w) in enumerate((("ref", "Sale ID / receipt", 16), ("item", "Item name", 16),
                                             ("frm", "From (YYYY-MM-DD)", 12), ("to", "To (YYYY-MM-DD)", 12),
                                             ("cashier", "Cashier", 12))):
            ttk.Label(form, text=label).grid(row=0, column=i, padx=6, sticky="w")
            self.vars[key] = tk.StringVar()
            e = ttk.Entry(form, textvariable=self.vars[key], width=w)
            e.grid(row=1, column=i, padx=6, pady=4)
            e.bind("<Return>", lambda ev: self.search())
        ttk.Button(form, text="Search", command=self.search).grid(row=1, column=5, padx=6)
        ttk.Button(form, text="Today", command=self.today).grid(row=1, column=6)
        ttk.Button(form, text="Clear", command=self.clear).grid(row=1, column=7, padx=6)
        self.tree = make_tree(self, [("id", "ID", 50), ("receipt", "Receipt no.", 150), ("when", "Date / time", 140),
                                     ("cashier", "Cashier", 90), ("customer", "Customer", 140),
                                     ("total", "Total (KSh)", 90), ("refunds", "Refunds", 80),
                                     ("status", "Status", 90)])
        self.tree.tag_configure("voided", foreground="#b00020")
        self.tree.bind("<Double-1>", lambda e: self.open())
        ttk.Button(self, text="Open selected sale (receipt / return / void)", command=self.open).pack(pady=6)

    def today(self):
        self.vars["frm"].set(date.today().isoformat())
        self.vars["to"].set(date.today().isoformat())
        self.search()

    def clear(self):
        for v in self.vars.values():
            v.set("")
        self.search()

    def refresh(self):
        self.search()

    def search(self):
        try:
            rows = sales.search_sales(self.app.conn, self.vars["ref"].get(), self.vars["item"].get(),
                                      self.vars["frm"].get(), self.vars["to"].get(), self.vars["cashier"].get())
        except EXPECTED as exc:
            messagebox.showerror("Search", str(exc))
            return
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]), tags=("voided",) if r["status"] == "VOIDED" else (),
                             values=(r["id"], r["receipt_no"], r["sold_at"], r["cashier"], r["customer"],
                                     money(r["total"]), money(r["refunds"]), r["status"]))

    def open(self):
        sid = selected_id(self.tree)
        if sid is not None:
            SaleWindow(self.app, sid, on_change=self.search)


class ReportsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app, self.headers, self.rows = app, [], []
        names = ["Stock valuation", "Near-expiry and expired stock"]
        if auth.has(app.user, "view_sales_reports"):
            names.insert(0, "Sales summary")
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)
        self.kind = tk.StringVar(value=names[0])
        ttk.Combobox(top, textvariable=self.kind, values=names, state="readonly", width=30).pack(side="left")
        self.frm = tk.StringVar(value=(date.today() - timedelta(days=30)).isoformat())
        self.to = tk.StringVar(value=date.today().isoformat())
        ttk.Label(top, text="  From").pack(side="left")
        ttk.Entry(top, textvariable=self.frm, width=11).pack(side="left", padx=3)
        ttk.Label(top, text="To").pack(side="left")
        ttk.Entry(top, textvariable=self.to, width=11).pack(side="left", padx=3)
        ttk.Button(top, text="Run report", command=self.run).pack(side="left", padx=8)
        ttk.Button(top, text="Export to CSV", command=self.export).pack(side="left")
        self.tree = make_tree(self, [("a", "", 100)], height=18)

    def refresh(self):
        self.run()

    def run(self):
        conn, kind = self.app.conn, self.kind.get()
        try:
            if kind == "Sales summary":
                self.headers, self.rows = reports.sales_summary(conn, self.frm.get(), self.to.get())
            elif kind == "Stock valuation":
                self.headers, self.rows = reports.stock_valuation(conn)
            else:
                self.headers, self.rows = reports.expiry_report(conn)
        except EXPECTED as exc:
            messagebox.showerror("Report", str(exc))
            return
        fill_tree(self.tree, self.headers, self.rows)

    def export(self):
        if not self.rows:
            self.run()
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV file", "*.csv")],
                                            initialfile="report_{}.csv".format(date.today().isoformat()))
        if path:
            reports.export_csv(path, self.headers, self.rows)
            messagebox.showinfo("Export", "Saved to " + path)


class AdminTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="Add user", command=self.add).pack(side="left", padx=3)
        ttk.Button(bar, text="Reset password", command=self.reset).pack(side="left", padx=3)
        ttk.Button(bar, text="Activate / deactivate", command=self.toggle).pack(side="left", padx=3)
        self.tree = make_tree(self, [("user", "Username", 120), ("name", "Full name", 200),
                                     ("role", "Role", 110), ("active", "Active", 70), ("since", "Created", 150)], height=9)
        box = ttk.LabelFrame(self, text="Backup")
        box.pack(fill="x", padx=6, pady=8)
        self.info = tk.StringVar()
        ttk.Label(box, textvariable=self.info, wraplength=900).pack(anchor="w", padx=8, pady=4)
        row = ttk.Frame(box)
        row.pack(anchor="w", padx=8, pady=6)
        ttk.Button(row, text="Choose backup folder (external drive)...", command=self.choose).pack(side="left", padx=3)
        ttk.Button(row, text="Back up now", command=self.backup_now).pack(side="left", padx=3)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for u in auth.list_users(self.app.conn):
            self.tree.insert("", "end", iid=str(u["id"]),
                             values=(u["username"], u["full_name"], u["role"], "Yes" if u["active"] else "No", u["created_at"]))
        c = self.app.conn
        self.info.set("Backup folder: {}\nLast backup: {}   (an automatic backup runs once a day at start-up)".format(
            db.get_setting(c, "backup_dir"), db.get_setting(c, "last_backup") or "never"))

    def add(self):
        ask(self, "Add user", [("u", "Username", ""), ("n", "Full name", ""), ("r", "Role", "cashier", list(auth.ROLES)),
                               ("p", "Password (min 6)", "", "password")],
            lambda d: auth.create_user(self.app.conn, self.app.user, d["u"], d["n"], d["r"], d["p"]))
        self.refresh()

    def reset(self):
        uid = selected_id(self.tree)
        if uid is not None:
            ask(self, "Reset password", [("p", "New password (min 6)", "", "password")],
                lambda d: auth.reset_password(self.app.conn, self.app.user, uid, d["p"]))

    def toggle(self):
        uid = selected_id(self.tree)
        if uid is None:
            return
        row = self.app.conn.execute("SELECT active FROM users WHERE id=?", (uid,)).fetchone()
        try:
            auth.set_active(self.app.conn, self.app.user, uid, not row["active"])
        except EXPECTED as exc:
            messagebox.showerror("Users", str(exc))
        self.refresh()

    def choose(self):
        folder = filedialog.askdirectory(title="Choose backup folder")
        if folder:
            db.set_setting(self.app.conn, "backup_dir", folder)
            audit.log(self.app.conn, self.app.user, "BACKUP_FOLDER_CHANGED", folder)
            self.refresh()

    def backup_now(self):
        ok, msg = backup.run_backup(self.app.conn, self.app.user)
        (messagebox.showinfo if ok else messagebox.showerror)("Backup", msg)
        self.refresh()


class AuditTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=6)
        ttk.Label(top, text="Filter (user, action or details):").pack(side="left")
        self.q = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.q, width=30)
        e.pack(side="left", padx=6)
        e.bind("<Return>", lambda ev: self.refresh())
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left")
        ttk.Label(top, text="Read-only: entries cannot be edited or deleted.", foreground="#555555").pack(side="right")
        self.tree = make_tree(self, [("id", "#", 55), ("ts", "Time", 140), ("user", "User", 90),
                                     ("action", "Action", 160), ("details", "Details", 560)], height=22)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for r in audit.recent(self.app.conn, self.q.get()):
            self.tree.insert("", "end", values=(r["id"], r["ts"], r["username"], r["action"], r["details"]))


# ------------------------------------------------------------------ main app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1150x720")
        self.minsize(950, 620)
        setup_style(self)
        self.conn = db.connect()
        db.init_db(self.conn)
        auth.ensure_default_admin(self.conn)
        self.user = None
        self.tabs, self.timer, self.last_day = [], None, date.today()
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.show_login()

    def report_callback_exception(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        log_error(text)
        messagebox.showerror(APP_TITLE, "Something went wrong:\n\n{}\n\n(details saved in data/error.log)".format(val))

    # ---- session
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def show_login(self):
        self._clear()
        if self.timer:
            self.after_cancel(self.timer)
            self.timer = None
        bg = tk.Frame(self.body, bg=BLUE)
        bg.pack(fill="both", expand=True)
        tk.Label(bg, text="\u271A", font=("Segoe UI", 40, "bold"), bg=BLUE, fg=WHITE).place(relx=0.5, rely=0.13, anchor="center")
        tk.Label(bg, text="Macmillan Company", font=("Segoe UI", 28, "bold"), bg=BLUE, fg=WHITE).place(relx=0.5, rely=0.22, anchor="center")
        tk.Label(bg, text="Hospital Sales Management System", font=("Segoe UI", 13), bg=BLUE, fg="#CFE0FA").place(relx=0.5, rely=0.285, anchor="center")
        box = ttk.Frame(bg, style="Card.TFrame", padding=(36, 28))
        box.place(relx=0.5, rely=0.6, anchor="center")
        ttk.Label(box, text="Sign in to continue", style="Card.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 14))
        self.u, self.p = tk.StringVar(), tk.StringVar()
        ttk.Label(box, text="Username", style="Card.TLabel").pack(anchor="w")
        eu = ttk.Entry(box, textvariable=self.u, width=32)
        eu.pack(pady=(2, 10))
        ttk.Label(box, text="Password", style="Card.TLabel").pack(anchor="w")
        ep = ttk.Entry(box, textvariable=self.p, show="*", width=32)
        ep.pack(pady=(2, 16))
        ttk.Button(box, text="Sign in", style="Login.TButton", command=self.login).pack(fill="x")
        ep.bind("<Return>", lambda e: self.login())
        eu.bind("<Return>", lambda e: ep.focus_set())
        eu.focus_set()

    def login(self):
        user = auth.authenticate(self.conn, self.u.get(), self.p.get())
        if not user:
            messagebox.showerror("Sign in", "Invalid username or password.")
            self.p.set("")
            return
        self.user = user
        stock.run_expiry_check(self.conn, user)           # expiry engine runs at start-up
        backup.scheduled_backup(self.conn, user)          # one automatic backup per day
        self.show_main()
        if auth.has(user, "view_expiry"):
            res = stock.run_expiry_check(self.conn, user)
            if res["expired"] or res["near_expiry"]:
                messagebox.showwarning("Expiry alert", "{} expired batch(es) are blocked from sale.\n"
                                       "{} batch(es) are close to expiry.\n\nSee the 'Expiry & Alerts' tab."
                                       .format(res["expired"], res["near_expiry"]))
        self.timer = self.after(3_600_000, self.hourly)

    def logout(self):
        auth.logout(self.conn, self.user)
        self.user = None
        self.show_login()

    def quit_app(self):
        if self.user:
            auth.logout(self.conn, self.user)
        self.conn.close()
        self.destroy()

    def hourly(self):
        """Daily check: when the date rolls over, re-run the expiry engine and the backup."""
        if date.today() != self.last_day and self.user:
            self.last_day = date.today()
            stock.run_expiry_check(self.conn, self.user)
            backup.scheduled_backup(self.conn, self.user)
            self.refresh_current()
        self.timer = self.after(3_600_000, self.hourly)

    def change_password(self):
        ask(self, "Change my password", [("o", "Current password", "", "password"),
                                         ("n", "New password (min 6)", "", "password"),
                                         ("c", "Repeat new password", "", "password")],
            self._do_change_password)

    def _do_change_password(self, d):
        if d["n"] != d["c"]:
            raise db.HMSError("The new passwords do not match.")
        auth.change_password(self.conn, self.user, d["o"], d["n"])
        messagebox.showinfo("Password", "Password changed.")

    def get_authoriser(self, parent):
        """Voids and returns need a supervisor (administrator or pharmacist)."""
        if auth.has(self.user, "authorise_reversal"):
            ok = messagebox.askyesno("Authorisation", "Authorise this action as {}?".format(
                self.user["username"]), parent=parent)
            return self.user if ok else None
        found = {}
        ask(parent, "Supervisor authorisation required",
            [("u", "Supervisor username", ""), ("p", "Supervisor password", "", "password")],
            lambda d: found.update(user=auth.verify_authoriser(self.conn, d["u"], d["p"])), "Authorise")
        return found.get("user")

    # ---- main screen
    def show_main(self):
        self._clear()
        u = self.user
        head = tk.Frame(self.body, bg=NAVY, height=54)
        head.pack(fill="x")
        tk.Label(head, text="\u271A  Macmillan HMS", font=("Segoe UI", 14, "bold"), bg=NAVY, fg=WHITE).pack(side="left", padx=18, pady=12)
        tk.Label(head, text="{}  \u2022  {}".format(u["full_name"], u["role"].title()), font=("Segoe UI", 10),
                 bg=NAVY, fg="#CFE0FA").pack(side="right", padx=18)
        side = tk.Frame(self.body, bg=NAVY, width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.content = ttk.Frame(self.body)
        self.content.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        self.tabs, self.navbtns, self.current = [], [], None
        spec = (("sell", "Point of Sale", POSTab), ("manage_products", "Stock & Batches", StockTab),
                ("view_expiry", "Expiry & Alerts", ExpiryTab), ("search_sales", "Sales Archive", ArchiveTab),
                ("view_reports", "Reports", ReportsTab), ("manage_users", "Administration", AdminTab),
                ("view_audit", "Audit Log", AuditTab))
        tk.Label(side, text="MENU", font=("Segoe UI", 9, "bold"), bg=NAVY, fg="#7FA6E0").pack(anchor="w", padx=20, pady=(18, 6))
        for perm, title, cls in spec:
            if auth.has(u, perm):
                tab = cls(self.content, self)
                self.tabs.append(tab)
                idx = len(self.tabs) - 1
                btn = ttk.Button(side, text="{}   {}".format(ICONS.get(perm, "\u2022"), title), style="Nav.TButton",
                                 command=lambda i=idx: self.show_tab(i))
                btn.pack(fill="x")
                self.navbtns.append(btn)
        ttk.Button(side, text="\U0001F6AA   Sign out", style="Side.TButton", command=self.logout).pack(side="bottom", fill="x", pady=(0, 14))
        ttk.Button(side, text="\U0001F511   Change my password", style="Side.TButton",
                   command=self.change_password).pack(side="bottom", fill="x", pady=(0, 4))
        if self.tabs:
            self.show_tab(0)

    def show_tab(self, index):
        if self.current is not None:
            self.tabs[self.current].pack_forget()
        self.current = index
        for i, btn in enumerate(self.navbtns):
            btn.configure(style="NavOn.TButton" if i == index else "Nav.TButton")
        self.tabs[index].pack(fill="both", expand=True)
        self.refresh_current()

    def refresh_current(self):
        if self.tabs and self.current is not None:
            tab = self.tabs[self.current]
            if hasattr(tab, "refresh"):
                tab.refresh()


def log_error(text):
    """Append to data/error.log (the app may be running without a console window)."""
    try:
        os.makedirs(db.DATA_DIR, exist_ok=True)
        with open(os.path.join(db.DATA_DIR, "error.log"), "a", encoding="utf-8") as fh:
            fh.write("[{}]\n{}\n".format(db.now_str(), text))
    except OSError:
        pass


def main():
    try:
        app = App()
    except db.HMSError as exc:                       # MySQL not running, wrong password, driver missing...
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, str(exc))
        root.destroy()
        return
    app.mainloop()
