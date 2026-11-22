"""Database layer: MySQL / MariaDB (XAMPP) connection, schema set-up and transaction helpers.

Key design points taken from the proposal:
  * the BATCH (not the product) is the unit of stock control;
  * stock is reduced in the same transaction that records the sale;
  * the audit log is append-only (enforced by database triggers);
  * an expired batch can never appear on a sale (enforced by a trigger too).
"""
import os
from contextlib import contextmanager
from datetime import datetime

try:
    import pymysql
    from pymysql.constants import CLIENT, FIELD_TYPE
    from pymysql.converters import conversions as _conversions
except ImportError:                      # reported nicely by connect()
    pymysql = None

from . import config, schema
from .sqlcompat import Row, to_number, translate

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("HMS_DATA_DIR", os.path.join(BASE_DIR, "data"))   # receipts, backups, error log


class HMSError(Exception):
    """Base class for all business-rule errors shown to the user."""


class DatabaseUnavailable(HMSError):
    """MySQL is not running / not reachable / driver missing."""


if pymysql:
    IntegrityError = pymysql.err.IntegrityError
    DatabaseError = pymysql.err.MySQLError        # every error the server or driver can raise
else:                                             # placeholders so imports still work
    class IntegrityError(Exception):
        pass

    class DatabaseError(Exception):
        pass


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ connection
class Cursor:
    """Result of Connection.execute(): rows are fetched immediately so statements can be nested safely."""

    def __init__(self, raw_cursor):
        self.rowcount = raw_cursor.rowcount
        self.lastrowid = raw_cursor.lastrowid
        self._rows = list(raw_cursor.fetchall()) if raw_cursor.description else []
        raw_cursor.close()

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """Thin wrapper that gives PyMySQL the conn.execute(sql, params) interface used everywhere."""

    def __init__(self, raw, database):
        self.raw = raw
        self.database = database
        self._in_tx = False

    def execute(self, sql, params=None):
        if not self._in_tx:
            self.raw.ping(reconnect=True)             # survive MySQL's idle time-out
        sql, params = translate(sql, params)
        cur = self.raw.cursor()
        try:
            cur.execute(sql, params)
            return Cursor(cur)
        except BaseException:
            cur.close()
            raise

    def begin(self):
        self.execute("START TRANSACTION")
        self._in_tx = True

    def commit(self):
        self._in_tx = False
        self.raw.commit()

    def rollback(self):
        self._in_tx = False
        self.raw.rollback()

    def escape(self, value):
        return self.raw.escape(value)

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


def connect(database=None):
    """Connect to MySQL, creating the database if it does not exist yet."""
    if pymysql is None:
        raise DatabaseUnavailable("The MySQL driver is not installed.\n"
                                  "Run:  python -m pip install -r requirements.txt")
    cfg = config.load()
    name = database or cfg["database"]
    conv = _conversions.copy()
    conv[FIELD_TYPE.NEWDECIMAL] = to_number
    conv[FIELD_TYPE.DECIMAL] = to_number

    class RowCursor(pymysql.cursors.DictCursor):
        dict_type = Row

    try:
        raw = pymysql.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                              password=cfg["password"], charset="utf8mb4", autocommit=True,
                              connect_timeout=5, conv=conv, cursorclass=RowCursor,
                              client_flag=CLIENT.FOUND_ROWS)     # rowcount = rows matched, as users expect
        with raw.cursor() as cur:
            cur.execute("CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4 "
                        "COLLATE utf8mb4_general_ci".format(name.replace("`", "")))
        raw.select_db(name)
    except pymysql.err.OperationalError as exc:
        raise DatabaseUnavailable(
            "Cannot connect to MySQL at {}:{} (user '{}').\n\n"
            "Start MySQL in the XAMPP Control Panel (or use run.bat), "
            "and check config.ini.\n\nDetails: {}".format(cfg["host"], cfg["port"], cfg["user"], exc))
    return Connection(raw, name)


@contextmanager
def transaction(conn):
    """START TRANSACTION ... COMMIT, rolling back on any error."""
    conn.begin()
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


# -------------------------------------------------------------------- settings
def get_setting(conn, key, default=None):
    row = conn.execute("SELECT setting_value FROM settings WHERE setting_key = ?", (key,)).fetchone()
    return row["setting_value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(setting_key, setting_value) VALUES(?, ?) "
                 "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)", (key, str(value)))


# ---------------------------------------------------------------------- schema
def init_db(conn):
    """Create any missing tables / triggers / default settings. Safe to run every start-up."""
    for _name, ddl in schema.TABLES:
        conn.execute(ddl)
    existing = {r[0] for r in conn.execute(
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()").fetchall()}
    for name, ddl in schema.TRIGGERS:
        if name not in existing:
            conn.execute(ddl)
    for key, value in (("alert_thresholds", "90,60,30"),
                       ("backup_dir", os.path.join(DATA_DIR, "backups")),
                       ("last_backup", ""), ("last_expiry_check", "")):
        conn.execute("INSERT IGNORE INTO settings(setting_key, setting_value) VALUES(?, ?)", (key, value))


def reset_schema(conn):
    """Drop every table (used by the unit tests only)."""
    conn.execute("SET FOREIGN_KEY_CHECKS = 0")
    for name in reversed(schema.TABLE_NAMES):
        conn.execute("DROP TABLE IF EXISTS `{}`".format(name))
    conn.execute("SET FOREIGN_KEY_CHECKS = 1")
