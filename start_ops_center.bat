@echo off
rem Starts the Operations Center on this PC (double-click). Same address every time: http://127.0.0.1:8765
cd /d "%~dp0"
python run_local.py
pause
