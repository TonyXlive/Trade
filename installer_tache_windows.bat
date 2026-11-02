@echo off
chcp 65001 >nul
rem Cree une tache Windows qui fait tourner le bot chaque jour a 7 h
schtasks /Create /SC DAILY /ST 07:00 /TN "Bot portefeuille fictif" /TR "\"%~dp0portefeuille_auto.bat\"" /F
echo.
echo Tache creee : le bot jouera une journee chaque matin a 7 h (PC allume).
echo Pour la supprimer : schtasks /Delete /TN "Bot portefeuille fictif" /F
pause
