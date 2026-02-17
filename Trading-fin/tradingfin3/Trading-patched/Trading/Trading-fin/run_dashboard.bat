@echo off
title Trading AI Dashboard
echo ==================================================
echo      TRADING AI - CONTROL PANEL LAUNCHER
echo ==================================================
echo.

echo [1/3] Checking dependencies...
pip install fastapi uvicorn Jinja2 python-multipart python-telegram-bot pandas inputimeout aiofiles > nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    pip install fastapi uvicorn Jinja2 python-multipart python-telegram-bot pandas inputimeout aiofiles
)

echo [2/3] Starting Server...
echo.
echo    OPEN THIS URL IN BROWSER:
echo    http://localhost:8080
echo.
echo.

start http://localhost:8080

python web_ui/server.py

pause
