@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m bot.main --monte-carlo 100
if exist sortie\rapport.html start "" "sortie\rapport.html"
pause
