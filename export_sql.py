"""Developer utility: regenerate database/macmillan_hms.sql from hms/schema.py.
Import that file in phpMyAdmin if you prefer to create the database by hand."""
import os

from hms import auth, schema

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "macmillan_hms.sql")


def build():
    out = ["-- Macmillan Company - Hospital Sales Management System (MySQL / MariaDB, XAMPP)",
           "-- phpMyAdmin: open http://localhost/phpmyadmin -> Import -> choose this file -> Go.",
           "-- Creates the database, tables, safety triggers and the first login admin / admin123.",
           "",
           "CREATE DATABASE IF NOT EXISTS `macmillan_hms` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;",
           "USE `macmillan_hms`;", "SET NAMES utf8mb4;", ""]
    for _name, ddl in schema.TABLES:
        out += [ddl + ";", ""]
    out += ["DELIMITER $$"]
    for name, ddl in schema.TRIGGERS:
        out += ["DROP TRIGGER IF EXISTS {} $$".format(name), ddl + " $$"]
    out += ["DELIMITER ;", ""]
    out += ["INSERT IGNORE INTO settings(setting_key, setting_value) VALUES ('alert_thresholds', '90,60,30');",
            "INSERT INTO users(username, full_name, role, password_hash, created_at)",
            "  SELECT 'admin', 'System Administrator', 'administrator', '{}', NOW() FROM DUAL".format(
                auth.hash_password("admin123")),
            "  WHERE NOT EXISTS (SELECT 1 FROM users);", ""]
    return "\n".join(out)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build())
    print("Written", OUT)
