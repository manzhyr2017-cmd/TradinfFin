@echo off
REM Auto-Restart Script for Neuro-Bot
REM Run this script to keep the bot running 24/7

:loop
echo ========================================
echo Starting Neuro-Bot at %date% %time%
echo ========================================

cd /d "%~dp0"
python main_bybit.py scan --continuous

echo ========================================
echo Bot stopped. Restarting in 10 seconds...
echo Press Ctrl+C to exit.
echo ========================================
timeout /t 10 >nul
goto loop
