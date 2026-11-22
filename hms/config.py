"""Connection settings for the MySQL server (XAMPP defaults).

Edit config.ini next to main.py, or override with environment variables
HMS_DB_HOST, HMS_DB_PORT, HMS_DB_USER, HMS_DB_PASSWORD, HMS_DB_NAME.
"""
import configparser
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")

DEFAULTS = {"host": "127.0.0.1", "port": "3306", "user": "root", "password": "",
            "database": "macmillan_hms"}


def load():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(CONFIG_FILE, encoding="utf-8")
    values = dict(DEFAULTS)
    if parser.has_section("mysql"):
        values.update({k: v.strip() for k, v in parser.items("mysql") if k in DEFAULTS})
    env = {"host": "HMS_DB_HOST", "port": "HMS_DB_PORT", "user": "HMS_DB_USER",
           "password": "HMS_DB_PASSWORD", "database": "HMS_DB_NAME"}
    for key, var in env.items():
        if var in os.environ:
            values[key] = os.environ[var]
    values["port"] = int(values["port"])
    return values
