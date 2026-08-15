@echo off
cd /d "%~dp0"
set "PY_CMD="
where py >nul 2>nul && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD (
  echo Python est introuvable. Installe Python 3.12 ou 3.13 depuis python.org.
  pause
  exit /b 1
)
%PY_CMD% -m venv .venv
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
if not exist .env copy .env.example .env >nul
echo.
echo Installation terminee. Ouvre maintenant .env et colle ton token Discord.
pause
exit /b 0
:error
echo.
echo L'installation a echoue. Lis le message d'erreur ci-dessus.
pause
exit /b 1
