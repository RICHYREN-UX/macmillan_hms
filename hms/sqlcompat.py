"""Small helpers that let the rest of the code keep its  conn.execute(sql, params)  style.

* "?" placeholders and ":name" placeholders are converted to PyMySQL's %s / %(name)s
* rows can be read by column name (row["total"]) or by position (row[0])
* DECIMAL results (SUM of integers) come back as plain int/float
"""
import re
from decimal import Decimal

_NAMED = re.compile(r":([A-Za-z_]\w*)")


def translate(sql, params):
    """Return (sql, params) ready for PyMySQL. Without parameters the SQL is passed through untouched."""
    if params is None or (not isinstance(params, dict) and len(params) == 0):
        return sql, None
    sql = sql.replace("%", "%%")
    if isinstance(params, dict):
        return _NAMED.sub(r"%(\1)s", sql), params
    return sql.replace("?", "%s"), tuple(params)


def to_number(text):
    """Converter for DECIMAL columns: 12 -> int, 12.5 -> float."""
    value = Decimal(text)
    return int(value) if value == value.to_integral_value() else float(value)


class Row(dict):
    """dict that also supports row[0]."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)
