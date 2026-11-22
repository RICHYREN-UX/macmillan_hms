"""Append-only audit trail (the table is protected by triggers in db.py)."""
from . import db


def log(conn, user, action, details=""):
    uid = user["id"] if user else None
    uname = user["username"] if user else "system"
    conn.execute(
        "INSERT INTO audit_log(ts, user_id, username, action, details) VALUES (?,?,?,?,?)",
        (db.now_str(), uid, uname, action, details))


def recent(conn, text="", limit=1000):
    like = "%{}%".format(text.strip())
    return conn.execute(
        "SELECT id, ts, username, action, details FROM audit_log "
        "WHERE action LIKE ? OR username LIKE ? OR details LIKE ? "
        "ORDER BY id DESC LIMIT ?", (like, like, like, limit)).fetchall()
