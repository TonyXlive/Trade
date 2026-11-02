@echo off
rem Lancement automatique (sans fenetre a fermer), utilise par la tache planifiee
cd /d "%~dp0"
python -m bot.portefeuille >> etat_journal.txt 2>&1
