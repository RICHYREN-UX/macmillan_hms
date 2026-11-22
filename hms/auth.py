"""Login, hashed passwords and role-based access control (RBAC)."""
import hashlib
import hmac
import secrets

from . import audit, db

ROLES = ("administrator", "pharmacist", "cashier")
ITERATIONS = 200_000

PERMISSIONS = {
    "administrator": {
        "sell", "search_sales", "authorise_reversal", "manage_products", "change_price",
        "receive_stock", "adjust_stock", "view_expiry", "view_reports",
        "view_sales_reports", "manage_users", "view_audit", "backup", "manage_settings"},
    "pharmacist": {
        "search_sales", "authorise_reversal", "manage_products", "receive_stock",
        "adjust_stock", "view_expiry", "view_reports"},
    "cashier": {"sell", "search_sales"},
}


class AuthError(db.HMSError):
    pass


class PermissionDenied(AuthError):
    pass


def has(user, permission):
    return bool(user) and permission in PERMISSIONS.get(user["role"], ())


def require(user, permission):
    if not has(user, permission):
        raise PermissionDenied("Your role is not allowed to do this ({}).".format(permission))


# ---------------------------------------------------------------- passwords
def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(ITERATIONS, salt, digest.hex())


def verify_password(password, stored):
    try:
        _, iters, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _check_password_rules(password):
    if len(password) < 6:
        raise db.HMSError("Password must be at least 6 characters long.")


def _lookup(conn, username, password):
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row and row["active"] and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "username": row["username"],
                "full_name": row["full_name"], "role": row["role"]}
    return None


# ------------------------------------------------------------------- login
def authenticate(conn, username, password):
    user = _lookup(conn, username, password)
    if user:
        audit.log(conn, user, "LOGIN", "Signed in")
    else:
        audit.log(conn, None, "LOGIN_FAILED", "Username tried: {}".format(username.strip()))
    return user


def verify_authoriser(conn, username, password):
    """Supervisor override for voids and returns."""
    user = _lookup(conn, username, password)
    if not user or not has(user, "authorise_reversal"):
        audit.log(conn, None, "AUTHORISATION_FAILED", "Username tried: {}".format(username.strip()))
        raise AuthError("Authorisation failed: invalid credentials or not a supervisor.")
    return user


def logout(conn, user):
    audit.log(conn, user, "LOGOUT", "Signed out")


def ensure_default_admin(conn):
    """First run only: create admin / admin123 (to be changed immediately)."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    conn.execute(
        "INSERT INTO users(username, full_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
        ("admin", "System Administrator", "administrator", hash_password("admin123"), db.now_str()))
    audit.log(conn, None, "USER_CREATED", "Default administrator created on first run")
    return True


# ------------------------------------------------------------ user admin
def list_users(conn):
    return conn.execute("SELECT id, username, full_name, role, active, created_at "
                        "FROM users ORDER BY username").fetchall()


def create_user(conn, admin, username, full_name, role, password):
    require(admin, "manage_users")
    username, full_name = username.strip(), full_name.strip()
    if not username or not full_name:
        raise db.HMSError("Username and full name are required.")
    if role not in ROLES:
        raise db.HMSError("Role must be one of: " + ", ".join(ROLES))
    _check_password_rules(password)
    try:
        with db.transaction(conn):
            conn.execute(
                "INSERT INTO users(username, full_name, role, password_hash, created_at) "
                "VALUES (?,?,?,?,?)",
                (username, full_name, role, hash_password(password), db.now_str()))
            audit.log(conn, admin, "USER_CREATED", "{} ({})".format(username, role))
    except db.IntegrityError:
        raise db.HMSError("That username already exists.")


def reset_password(conn, admin, user_id, new_password):
    require(admin, "manage_users")
    _check_password_rules(new_password)
    with db.transaction(conn):
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                           (hash_password(new_password), user_id))
        if cur.rowcount != 1:
            raise db.HMSError("User not found.")
        audit.log(conn, admin, "PASSWORD_RESET", "User id {}".format(user_id))


def set_active(conn, admin, user_id, active):
    require(admin, "manage_users")
    with db.transaction(conn):
        target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            raise db.HMSError("User not found.")
        if not active:
            if target["id"] == admin["id"]:
                raise db.HMSError("You cannot deactivate your own account.")
            others = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='administrator' AND active=1 AND id<>?",
                (user_id,)).fetchone()[0]
            if target["role"] == "administrator" and others == 0:
                raise db.HMSError("At least one active administrator is required.")
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
        audit.log(conn, admin, "USER_ACTIVATED" if active else "USER_DEACTIVATED", target["username"])


def change_password(conn, user, old_password, new_password):
    if not _lookup(conn, user["username"], old_password):
        raise AuthError("Current password is incorrect.")
    _check_password_rules(new_password)
    with db.transaction(conn):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (hash_password(new_password), user["id"]))
        audit.log(conn, user, "PASSWORD_CHANGED", "Own password changed")
