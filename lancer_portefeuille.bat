@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m bot.portefeuille
if exist docs\index.html start "" "docs\index.html"
pause
