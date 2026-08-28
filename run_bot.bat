@echo off
title ASSASSIN BOT v2 - LIVE RUNNER
color 0A
cls
echo =======================================================
echo   ASSASSIN BOT v2 - 24/7 AUTO-RUNNER
echo =======================================================
echo.
cd /d "%~dp0"

echo [1/2] Checking Python requirements...
pip install -r requirements.txt >nul 2>&1

echo [2/2] Launching Assassin Bot...
echo Telegram: @homma1_bot (Admin ID: 6363315804)
echo Monitored: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT (1m / 5m Expiry)
echo.
:loop
python -u main.py
echo.
echo [WARNING] Bot disconnected or crashed. Restarting in 5 seconds...
timeout /t 5 >nul
goto loop
