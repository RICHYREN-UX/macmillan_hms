import os, sys, tempfile, unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hms import audit, auth, backup, db, reports, sales, stock


def d(days):
    return (date.today() + timedelta(days=days)).isoformat()


TEST_DB = os.environ.get("HMS_TEST_DB", "macmillan_hms_test")     # a separate database; never the live one


def setUpModule():
    try:
        db.connect(TEST_DB).close()
    except db.HMSError as exc:
        raise unittest.SkipTest("MySQL is not available - start it in XAMPP first.\n{}".format(exc))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(TEST_DB)
        db.reset_schema(self.conn)
        db.init_db(self.conn)
        auth.ensure_default_admin(self.conn)
        self.admin = auth.authenticate(self.conn, "admin", "admin123")
        auth.create_user(self.conn, self.admin, "phil", "Pharmacist P", "pharmacist", "pharm123")
        auth.create_user(self.conn, self.admin, "cass", "Cashier C", "cashier", "cash123")
        self.pharm = auth.authenticate(self.conn, "phil", "pharm123")
        self.cash = auth.authenticate(self.conn, "cass", "cash123")
        self.pid = stock.add_product(self.conn, self.pharm, "PARA", "Paracetamol 500mg", "tab", 10, 20)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def qty(self, bid):
        return self.conn.execute("SELECT quantity FROM batches WHERE id=?", (bid,)).fetchone()[0]


class TestAuth(Base):
    def test_passwords_hashed_and_login(self):
        stored = self.conn.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0]
        self.assertNotIn("admin123", stored)
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertIsNone(auth.authenticate(self.conn, "admin", "wrong"))
        self.assertIsNotNone(auth.authenticate(self.conn, "ADMIN", "admin123"))

    def test_rbac(self):
        with self.assertRaises(auth.PermissionDenied):
            stock.adjust_batch(self.conn, self.cash, 1, 5, "x")
        with self.assertRaises(auth.PermissionDenied):
            stock.update_product_price(self.conn, self.pharm, self.pid, 12)
        with self.assertRaises(auth.PermissionDenied):
            sales.create_sale(self.conn, self.pharm, [(self.pid, 1)])
        with self.assertRaises(auth.PermissionDenied):
            auth.create_user(self.conn, self.cash, "z", "Z", "cashier", "secret1")

    def test_last_admin_protected(self):
        with self.assertRaises(db.HMSError):
            auth.set_active(self.conn, self.admin, self.admin["id"], False)


class TestFEFO(Base):
    def test_fefo_order_and_split(self):
        late = stock.receive_batch(self.conn, self.pharm, self.pid, "L", d(400), 100, 5)
        soon = stock.receive_batch(self.conn, self.pharm, self.pid, "S", d(100), 30, 5)
        res = sales.create_sale(self.conn, self.cash, [(self.pid, 50)])
        self.assertEqual(self.qty(soon), 0)          # earliest batch emptied first
        self.assertEqual(self.qty(late), 80)         # remainder from the later batch
        _, items = sales.get_sale(self.conn, res["sale_id"])
        self.assertEqual([(i["batch_no"], i["quantity"]) for i in items], [("S", 30), ("L", 20)])
        self.assertEqual(res["total"], 500.0)

    def test_arrival_order_does_not_matter(self):
        first = stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(300), 10, 5)
        second = stock.receive_batch(self.conn, self.pharm, self.pid, "B", d(60), 10, 5)
        sales.create_sale(self.conn, self.cash, [(self.pid, 5)])
        self.assertEqual(self.qty(second), 5)
        self.assertEqual(self.qty(first), 10)

    def test_expired_batch_blocked(self):
        # insert an already-expired batch directly (simulating stock that aged on the shelf)
        self.conn.execute("INSERT INTO batches(product_id,batch_no,expiry_date,quantity,cost_price,received_at)"
                          " VALUES (?,?,?,?,?,?)", (self.pid, "OLD", d(-5), 50, 1, db.now_str()))
        with self.assertRaises(sales.SaleError) as ctx:
            sales.create_sale(self.conn, self.cash, [(self.pid, 1)])
        self.assertIn("expired", str(ctx.exception).lower())
        good = stock.receive_batch(self.conn, self.pharm, self.pid, "NEW", d(200), 10, 1)
        sales.create_sale(self.conn, self.cash, [(self.pid, 10)])
        self.assertEqual(self.qty(good), 0)
        with self.assertRaises(sales.SaleError):      # only expired stock left
            sales.create_sale(self.conn, self.cash, [(self.pid, 1)])
        self.assertEqual(self.conn.execute("SELECT quantity FROM batches WHERE batch_no='OLD'").fetchone()[0], 50)

    def test_database_trigger_blocks_expired_even_if_code_bypassed(self):
        self.conn.execute("INSERT INTO batches(product_id,batch_no,expiry_date,quantity,cost_price,received_at)"
                          " VALUES (?,?,?,?,?,?)", (self.pid, "OLD", d(-1), 5, 1, db.now_str()))
        bid = self.conn.execute("SELECT id FROM batches WHERE batch_no='OLD'").fetchone()[0]
        self.conn.execute("INSERT INTO sales(receipt_no,sold_at,cashier_id,total) VALUES ('X',?,?,1)",
                          (db.now_str(), self.cash["id"]))
        with self.assertRaises(db.DatabaseError):
            self.conn.execute("INSERT INTO sale_items(sale_id,product_id,batch_id,quantity,unit_price,line_total)"
                              " VALUES (1,?,?,1,1,1)", (self.pid, bid))

    def test_cannot_receive_expired_batch(self):
        with self.assertRaises(ValueError):
            stock.receive_batch(self.conn, self.pharm, self.pid, "E", d(-1), 5, 1)

    def test_sale_is_atomic(self):
        other = stock.add_product(self.conn, self.pharm, "AMOX", "Amoxicillin", "cap", 20, 0)
        a = stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(100), 10, 1)
        stock.receive_batch(self.conn, self.pharm, other, "B", d(100), 2, 1)
        with self.assertRaises(sales.SaleError):
            sales.create_sale(self.conn, self.cash, [(self.pid, 5), (other, 9)])
        self.assertEqual(self.qty(a), 10)             # first line rolled back
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0)

    def test_low_stock_warning(self):
        stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(100), 25, 1)
        res = sales.create_sale(self.conn, self.cash, [(self.pid, 6)])   # 19 left <= reorder 20
        self.assertEqual(res["low_stock"], ["Paracetamol 500mg"])
        self.assertEqual(len(stock.low_stock(self.conn)), 1)


class TestReversals(Base):
    def setUp(self):
        super().setUp()
        self.bid = stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(100), 50, 1)
        self.sale = sales.create_sale(self.conn, self.cash, [(self.pid, 10)])

    def test_void_needs_supervisor_and_restores_stock(self):
        with self.assertRaises(auth.PermissionDenied):
            sales.void_sale(self.conn, self.cash, self.sale["sale_id"], "mistake")
        with self.assertRaises(auth.AuthError):
            auth.verify_authoriser(self.conn, "cass", "cash123")        # cashier cannot authorise
        sup = auth.verify_authoriser(self.conn, "phil", "pharm123")
        sales.void_sale(self.conn, sup, self.sale["sale_id"], "wrong item", requested_by=self.cash)
        self.assertEqual(self.qty(self.bid), 50)
        with self.assertRaises(sales.SaleError):
            sales.void_sale(self.conn, sup, self.sale["sale_id"], "again")

    def test_partial_return(self):
        _, items = sales.get_sale(self.conn, self.sale["sale_id"])
        refund = sales.return_item(self.conn, self.pharm, items[0]["id"], 4, "damaged pack")
        self.assertEqual(refund, 40.0)
        self.assertEqual(self.qty(self.bid), 44)
        with self.assertRaises(sales.SaleError):
            sales.return_item(self.conn, self.pharm, items[0]["id"], 7, "too many")
        with self.assertRaises(sales.SaleError):                          # voiding after returns
            sales.void_sale(self.conn, self.pharm, self.sale["sale_id"], "x")
        self.assertIn("Refunded", sales.receipt_text(self.conn, self.sale["sale_id"]))


class TestAudit(Base):
    def test_audit_append_only_and_complete(self):
        bid = stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(100), 50, 1)
        stock.update_product_price(self.conn, self.admin, self.pid, 12)
        stock.adjust_batch(self.conn, self.pharm, bid, 45, "damaged")
        sale = sales.create_sale(self.conn, self.cash, [(self.pid, 1)])
        sales.void_sale(self.conn, self.pharm, sale["sale_id"], "test")
        actions = {r["action"] for r in audit.recent(self.conn)}
        for a in ("LOGIN", "PRICE_CHANGED", "STOCK_ADJUSTED", "SALE", "SALE_VOIDED", "BATCH_RECEIVED"):
            self.assertIn(a, actions)
        with self.assertRaises(db.DatabaseError):
            self.conn.execute("UPDATE audit_log SET details='tampered' WHERE id=1")
        with self.assertRaises(db.DatabaseError):
            self.conn.execute("DELETE FROM audit_log")


class TestExpiryEngine(Base):
    def test_thresholds_and_idempotence(self):
        stock.receive_batch(self.conn, self.pharm, self.pid, "N85", d(85), 5, 1)
        stock.receive_batch(self.conn, self.pharm, self.pid, "N50", d(50), 5, 1)
        stock.receive_batch(self.conn, self.pharm, self.pid, "N10", d(10), 5, 1)
        stock.receive_batch(self.conn, self.pharm, self.pid, "FAR", d(500), 5, 1)
        self.conn.execute("INSERT INTO batches(product_id,batch_no,expiry_date,quantity,cost_price,received_at)"
                          " VALUES (?,?,?,?,?,?)", (self.pid, "EXP", d(-3), 5, 1, db.now_str()))
        first = stock.run_expiry_check(self.conn, self.admin)
        by = {r["batch_no"]: r["threshold"] for r in first["rows"]}
        self.assertEqual(by, {"N85": 90, "N50": 60, "N10": 30, "EXP": 0})
        self.assertEqual((first["expired"], first["near_expiry"], first["new_alerts"]), (1, 3, 4))
        self.assertEqual(stock.run_expiry_check(self.conn, self.admin)["new_alerts"], 0)

    def test_configurable_thresholds(self):
        stock.set_thresholds(self.conn, self.admin, "120, 45")
        self.assertEqual(stock.get_thresholds(self.conn), [45, 120])
        with self.assertRaises(auth.PermissionDenied):
            stock.set_thresholds(self.conn, self.pharm, "10")


class TestArchiveReportsBackup(Base):
    def setUp(self):
        super().setUp()
        stock.receive_batch(self.conn, self.pharm, self.pid, "A", d(100), 100, 2)
        self.s1 = sales.create_sale(self.conn, self.cash, [(self.pid, 3)], "Clinic Ngong")
        self.s2 = sales.create_sale(self.conn, self.admin, [(self.pid, 2)])

    def test_search(self):
        self.assertEqual(len(sales.search_sales(self.conn, ref=str(self.s1["sale_id"]))), 1)
        self.assertEqual(len(sales.search_sales(self.conn, ref=self.s2["receipt_no"])), 1)
        self.assertEqual(len(sales.search_sales(self.conn, item="parac")), 2)
        self.assertEqual(len(sales.search_sales(self.conn, item="nothing")), 0)
        self.assertEqual(len(sales.search_sales(self.conn, cashier="cass")), 1)
        self.assertEqual(len(sales.search_sales(self.conn, date_from=d(0), date_to=d(0))), 2)
        self.assertEqual(len(sales.search_sales(self.conn, date_from=d(1))), 0)

    def test_reports(self):
        h, rows = reports.sales_summary(self.conn, d(-1), d(1))
        self.assertEqual(rows[-1][:2], ("TOTAL", 2))
        self.assertEqual(rows[-1][2], "50.00")
        h, rows = reports.stock_valuation(self.conn)
        self.assertEqual(rows[-1][2], 95)
        path = os.path.join(self.tmp.name, "r.csv")
        reports.export_csv(path, h, rows)
        self.assertTrue(os.path.getsize(path) > 0)

    def test_backup_is_valid_sql_dump(self):
        target = backup.backup_database(self.conn, os.path.join(self.tmp.name, "bk"))
        self.assertTrue(target.endswith(".sql"))
        text = open(target, encoding="utf-8").read()
        for table in ("users", "sales", "sale_items", "batches", "audit_log"):
            self.assertIn("CREATE TABLE `{}`".format(table), text)
        self.assertEqual(text.count("INSERT INTO `sales`"), 1)
        self.assertIn("RC-", text)
        db.set_setting(self.conn, "backup_dir", os.path.join(self.tmp.name, "bk2"))
        ok, msg = backup.run_backup(self.conn, self.admin)
        self.assertTrue(ok, msg)
        self.assertEqual(backup.scheduled_backup(self.conn)[1], "Already backed up today")
        db.set_setting(self.conn, "backup_dir", "/proc/nope/forbidden")   # unplugged drive
        self.assertFalse(backup.run_backup(self.conn, self.admin)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
