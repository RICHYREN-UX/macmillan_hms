"""Stand-alone backup, for Windows Task Scheduler:  python run_backup.py"""
from hms import auth, backup, db

conn = db.connect()
db.init_db(conn)
ok, message = backup.run_backup(conn)
print(message)
raise SystemExit(0 if ok else 1)
