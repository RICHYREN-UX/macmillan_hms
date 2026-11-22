"""Start the Hospital Sales Management System:  python main.py   (or double-click run.bat)"""
import traceback

from hms.app import log_error, main

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
