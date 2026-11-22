"""Create the MySQL database, tables, triggers and the default admin user.
Used by run.bat; safe to run any number of times.

    python setup_db.py [--wait SECONDS]     (--wait = keep retrying while MySQL is starting up)
Exit code: 0 = ready, 2 = MySQL not reachable, 3 = other error.
"""
import sys
import time

from hms import auth, db


def main(argv):
    wait = int(argv[argv.index("--wait") + 1]) if "--wait" in argv else 0
    deadline = time.time() + wait
    while True:
        try:
            conn = db.connect()
            break
        except db.DatabaseUnavailable as exc:
            if time.time() >= deadline:
                print(exc)
                return 2
            time.sleep(1.5)
    try:
        db.init_db(conn)
        created = auth.ensure_default_admin(conn)
    except Exception as exc:
        print("Database set-up failed: {}".format(exc))
        return 3
    finally:
        conn.close()
    print("Database '{}' is ready.".format(conn.database))
    if created:
        print("First login:  admin / admin123   (change it after signing in)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
