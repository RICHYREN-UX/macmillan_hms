# Hospital Sales Management System - Macmillan Company

Windows desktop system (Python + Tkinter) that stores its data in **MySQL / MariaDB from XAMPP**.

## Quick start (Windows + XAMPP)
1. Install XAMPP (default `C:\xampp`) and Python 3.8+ (tick "Add python.exe to PATH" and keep tcl/tk).
2. **Double-click `run.bat`.** It will, automatically:
   * start MySQL from XAMPP if it is not already running,
   * install the one Python package needed (`PyMySQL`, first run only - needs internet),
   * create the database `macmillan_hms`, all tables, triggers and the admin user,
   * open the system.
3. First login: `admin` / `admin123` - **change it immediately** ("Change my password").

`run_with_demo_data.bat` does the same and also loads sample users, products and batches
(`pharmacist/pharm123`, `cashier/cash123`) - use it on a fresh database only, never on live data.

If MySQL was started by `run.bat`, it runs in a minimised window titled "MySQL (XAMPP)"; closing that window
stops MySQL. You can also just start MySQL from the XAMPP Control Panel before running `run.bat`.

## Using phpMyAdmin instead (optional)
`database/macmillan_hms.sql` contains the whole database (tables, triggers, admin user).
Open http://localhost/phpmyadmin -> **Import** -> choose that file -> **Go**. The application also creates
anything that is missing by itself, so this step is not required.

## Settings
`config.ini` holds the connection (XAMPP defaults: host 127.0.0.1, port 3306, user `root`, empty password,
database `macmillan_hms`). Edit it if you have set a MySQL password.

## Roles (RBAC)
| Role | Sees |
|---|---|
| Cashier | Point of Sale, Sales Archive |
| Pharmacist | Stock & Batches (add products, receive/adjust batches), Expiry & Alerts, Sales Archive, Reports (stock/expiry); can authorise voids and returns |
| Administrator | Everything, plus price changes, alert thresholds, user management, backup, sales reports, Audit Log |

## Proposal -> code map
| Proposal feature (Section 3 / 4.1) | Where |
|---|---|
| Batch-level stock registry | `hms/stock.py` (`receive_batch`, `adjust_batch`), `batches` table |
| FEFO allocation, splitting across batches | `hms/sales.py` `allocate_fefo`, `create_sale` |
| Expiry Alert Engine (90/60/30 days, configurable), runs at start-up and daily | `hms/stock.py` `run_expiry_check`; called from `hms/app.py` at login and hourly date check |
| Expired batches cannot be sold | `allocate_fefo` skips them; POS rejects with a message; MySQL trigger `block_expired_sale` is a second safeguard |
| Real-time stock + reorder warnings | stock is deducted in the same transaction as the sale; warning on POS and in Expiry & Alerts tab |
| Accurate billing, itemised receipt, printing | `create_sale`, `receipt_text`, Print button (receipts also saved in `data/receipts/`) |
| Returns and voids need authorisation | `void_sale`, `return_item` - a cashier needs a supervisor's username and password |
| Searchable sales archive | `search_sales` - by ID/receipt, item, date range, cashier |
| Reports | `hms/reports.py` - sales summary, stock valuation, near-expiry & expired; CSV export |
| RBAC, hashed passwords | `hms/auth.py` (PBKDF2-SHA256, 200,000 iterations, per-user salt) |
| Audit trail users cannot edit | `audit_log` table + `audit_no_update` / `audit_no_delete` MySQL triggers |
| Scheduled backup to external drive | `hms/backup.py` writes a restorable `.sql` file; automatic once a day at start-up; folder set in Administration tab; `run_backup.py` for Windows Task Scheduler |

## Tests
MySQL must be running. The tests use a separate database `macmillan_hms_test`, never the live one.
```
python -m unittest tests.test_hms -v
```
18 tests cover FEFO order and splitting, expiry blocking (code and database trigger), atomic sales,
RBAC, authorised voids/returns, audit immutability, alert thresholds, search, reports and backup.

## Notes for deployment (Section 6 of the schedule)
* Data lives in the MySQL database `macmillan_hms` (XAMPP folder `mysql\\data`); receipts are also saved in `data\\receipts`.
* Backups are `.sql` files in the folder chosen in the Administration tab (e.g. `E:\\Backups`). To restore, use
  phpMyAdmin -> Import. Start the application afterwards: it re-creates the safety triggers if they are missing.
* If the drive is unplugged the app does not crash; the failure is recorded in the audit log.
* Unexpected errors are written to `data\\error.log`.
* Capture real opening stock through "Receive batch" (never use the demo data on the live database).
