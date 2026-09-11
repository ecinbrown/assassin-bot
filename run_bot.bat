@echo off
title ASSASSIN BOT v4.1 - 40 TPD BTC+ETH (85.03% WR)
color 0A
cls
echo =======================================================
echo   ASSASSIN BOT v4.1 - 40 TPD AUTO-RUNNER
echo   Strategy: 281 Setups (85.03% 1-Gale WR | 6.1% Risk)
echo   Pairs: BTCUSDT, ETHUSDT ONLY (90% Payout Tier)
echo =======================================================
echo.
cd /d "%~dp0"

echo [1/2] Checking Python requirements...
pip install -r requirements.txt >nul 2>&1

echo [2/2] Launching Assassin Bot...
echo Telegram: @homma1_bot (Admin ID: 6363315804)
echo Monitored: BTCUSDT, ETHUSDT (Multi-TF Synthesis from 1m)
echo.
:loop
python -u main.py
echo.
echo [WARNING] Bot disconnected or crashed. Restarting in 5 seconds...
timeout /t 5 >nul
goto loop
