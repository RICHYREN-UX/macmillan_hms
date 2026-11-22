@echo off
setlocal EnableExtensions
title Macmillan HMS - Launcher
cd /d "%~dp0"
echo ============================================================
echo   Macmillan Company - Hospital Sales Management System
echo ============================================================
echo.

rem ---------- 1. Python ----------
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=python"
    )
)
if not defined PY goto :nopython
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 goto :notk
echo [1/4] Python found.

rem ---------- 2. MySQL (XAMPP) ----------
tasklist /FI "IMAGENAME eq mysqld.exe" 2>nul | find /I "mysqld.exe" >nul
if not errorlevel 1 goto :mysqlup
tasklist /FI "IMAGENAME eq mariadbd.exe" 2>nul | find /I "mariadbd.exe" >nul
if not errorlevel 1 goto :mysqlup

set "XAMPP="
if defined XAMPP_DIR if exist "%XAMPP_DIR%\mysql\bin\my.ini" set "XAMPP=%XAMPP_DIR%"
for %%D in (C D E F G) do (
    if not defined XAMPP if exist "%%D:\xampp\mysql\bin\my.ini" set "XAMPP=%%D:\xampp"
)
if not defined XAMPP if exist "%ProgramFiles%\xampp\mysql\bin\my.ini" set "XAMPP=%ProgramFiles%\xampp"
if not defined XAMPP goto :noxampp

set "MYSQLD=%XAMPP%\mysql\bin\mysqld.exe"
if not exist "%MYSQLD%" set "MYSQLD=%XAMPP%\mysql\bin\mariadbd.exe"
echo [2/4] Starting MySQL from %XAMPP% ...
start "MySQL (XAMPP) - leave this window open" /min "%MYSQLD%" --defaults-file="%XAMPP%\mysql\bin\my.ini" --standalone
goto :mysqlready

:mysqlup
echo [2/4] MySQL is already running.
:mysqlready

rem ---------- 3. MySQL driver for Python ----------
%PY% -c "import pymysql" >nul 2>nul
if errorlevel 1 (
    echo [3/4] Installing the MySQL driver ^(one time only, needs internet^) ...
    %PY% -m pip install --disable-pip-version-check -r requirements.txt
)
%PY% -c "import pymysql" >nul 2>nul
if errorlevel 1 goto :nodriver
echo [3/4] MySQL driver ready.

rem ---------- 4. Database set-up, then open the system ----------
echo [4/4] Preparing the database ^(waits up to 60 seconds for MySQL^) ...
%PY% setup_db.py --wait 60
if errorlevel 1 goto :dberror

if /I "%~1"=="demo" (
    echo Loading demo data ...
    %PY% seed_demo.py
)

echo.
echo Opening the system ...
set "PYW=%PY%"
if "%PY%"=="py -3" (
    where pyw >nul 2>nul
    if not errorlevel 1 set "PYW=pyw -3"
) else (
    where pythonw >nul 2>nul
    if not errorlevel 1 set "PYW=pythonw"
)
start "Macmillan HMS" %PYW% main.py
timeout /t 2 >nul
exit /b 0

:nopython
echo ERROR: Python 3 was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click run.bat again.
start https://www.python.org/downloads/
goto :fail
:notk
echo ERROR: This Python has no Tk support. Re-run the Python installer, choose Modify
echo and make sure "tcl/tk and IDLE" is ticked.
goto :fail
:noxampp
echo ERROR: MySQL is not running and XAMPP was not found in C:\xampp ^(or D:-G:^).
echo Start MySQL from the XAMPP Control Panel and run this file again, or set the
echo environment variable XAMPP_DIR to your XAMPP folder.
goto :fail
:nodriver
echo ERROR: Could not install the MySQL driver. Check your internet connection and run:
echo     %PY% -m pip install -r requirements.txt
goto :fail
:dberror
echo.
echo ERROR: The database could not be prepared ^(see the message above^).
echo If you set a MySQL root password, put it in config.ini.
goto :fail
:fail
echo.
pause
exit /b 1
