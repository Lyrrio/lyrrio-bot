@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Lance d'abord installer.bat.
  pause
  exit /b 1
)
.venv\Scripts\python.exe bot.py
echo.
echo Le bot est arrete. Appuie sur une touche pour fermer cette fenetre.
pause >nul
