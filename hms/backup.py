"""Database backup to a folder, normally an external drive.

The backup is a plain .sql file (tables + data) that can be re-imported with phpMyAdmin
(Import tab) or:  mysql -u root macmillan_hms < macmillan_YYYYMMDD_HHMMSS.sql
No mysqldump needed - it is written by the application itself.
"""
import os
from datetime import datetime

from . import audit, db, schema

CHUNK = 500


def _write_table(conn, fh, table):
    create = conn.execute("SHOW CREATE TABLE `{}`".format(table)).fetchone()[1]
    fh.write("DROP TABLE IF EXISTS `{}`;\n{};\n\n".format(table, create))
    offset = 0
    while True:
        rows = conn.execute("SELECT * FROM `{}` ORDER BY 1 LIMIT {} OFFSET {}".format(
            table, CHUNK, offset)).fetchall()
        if not rows:
            break
        cols = ", ".join("`{}`".format(c) for c in rows[0].keys())
        values = ",\n".join("(" + ", ".join(conn.escape(v) for v in r.values()) + ")" for r in rows)
        fh.write("INSERT INTO `{}` ({}) VALUES\n{};\n".format(table, cols, values))
        offset += CHUNK
    fh.write("\n")


def backup_database(conn, dest_dir=None, keep=30):
    """Write every table to a timestamped .sql file and keep only the newest `keep` files."""
    dest_dir = dest_dir or db.get_setting(conn, "backup_dir")
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, "macmillan_{:%Y%m%d_%H%M%S}.sql".format(datetime.now()))
    partial = target + ".part"
    try:
        with open(partial, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("-- Macmillan HMS backup {}\nSET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS = 0;\n\n".format(
                db.now_str()))
            for table in schema.TABLE_NAMES:
                _write_table(conn, fh, table)
            fh.write("SET FOREIGN_KEY_CHECKS = 1;\n")
        os.replace(partial, target)
    finally:
        if os.path.exists(partial):
            os.remove(partial)
    old = sorted(f for f in os.listdir(dest_dir) if f.startswith("macmillan_") and f.endswith(".sql"))
    for name in old[:-keep]:
        os.remove(os.path.join(dest_dir, name))
    return target


def run_backup(conn, user=None):
    """Backup + bookkeeping. Returns (ok, message); never raises (drive may be unplugged)."""
    try:
        path = backup_database(conn)
    except Exception as exc:                         # OSError, database errors, ...
        audit.log(conn, user, "BACKUP_FAILED", str(exc))
        return False, "Backup failed: {}".format(exc)
    db.set_setting(conn, "last_backup", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    audit.log(conn, user, "BACKUP_OK", path)
    return True, "Backup saved to {}".format(path)


def scheduled_backup(conn, user=None):
    """Called at start-up: one automatic backup per day."""
    last = db.get_setting(conn, "last_backup", "")
    if last[:10] != datetime.now().strftime("%Y-%m-%d"):
        return run_backup(conn, user)
    return True, "Already backed up today"
