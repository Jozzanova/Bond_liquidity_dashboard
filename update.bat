@echo off
cd /d "%~dp0"
python -X utf8 update.py %*
echo.
pause
