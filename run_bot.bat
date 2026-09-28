@echo off
title ASSASSIN BOT v6.5 - 30+ TPD (85%+ WR Portfolio)
color 0A
cls
echo =======================================================
echo   ASSASSIN BOT v6.5 - 30+ TPD 85%+ WR AUTO-RUNNER
echo   Strategy: 639 Setups (85%+ WR | Pure Compounding)
echo   Pairs: BTC (90%), ETH (90%), BNB (90%), SOL (70%), XRP (70%)
echo          EUR/USD (80%), USD/JPY (80%)
echo =======================================================
echo.
cd /d "%~dp0"

echo [1/2] Checking Python requirements...
pip install -r requirements.txt >nul 2>&1

echo [2/2] Launching Assassin Bot...
echo Telegram: @homma1_bot (Admin ID: 6363315804)
echo Monitored: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
echo.
:loop
python -u main.py
echo.
echo [WARNING] Bot disconnected or crashed. Restarting in 5 seconds...
timeout /t 5 >nul
goto loop
