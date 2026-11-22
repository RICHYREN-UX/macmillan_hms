"""Tests for the SQL helper layer - these need no MySQL server."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hms.sqlcompat import Row, to_number, translate


class TestCompat(unittest.TestCase):
    def test_positional(self):
        sql, args = translate("SELECT * FROM t WHERE a=? AND b LIKE ?", [1, "%x%"])
        self.assertEqual(sql, "SELECT * FROM t WHERE a=%s AND b LIKE %s")
        self.assertEqual(args, (1, "%x%"))

    def test_named(self):
        sql, args = translate("SELECT :t, :s", {"t": 1, "s": 2})
        self.assertEqual(sql, "SELECT %(t)s, %(s)s")

    def test_percent_escaped_only_with_params(self):
        self.assertEqual(translate("SELECT DATE_FORMAT(x,'%Y')", None)[0], "SELECT DATE_FORMAT(x,'%Y')")
        self.assertEqual(translate("SELECT DATE_FORMAT(x,'%Y') WHERE a=?", (1,))[0],
                         "SELECT DATE_FORMAT(x,'%%Y') WHERE a=%s")

    def test_row_and_numbers(self):
        r = Row(a=5, b="x")
        self.assertEqual((r[0], r["b"], dict(r)), (5, "x", {"a": 5, "b": "x"}))
        self.assertEqual(to_number("300"), 300)
        self.assertIsInstance(to_number("300"), int)
        self.assertEqual(to_number("2.5"), 2.5)


if __name__ == "__main__":
    unittest.main()
