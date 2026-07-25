@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

rem --- ishem Python ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
  echo [X] Python ne naiden. Ustanovite Python 3.9+ s https://www.python.org/downloads/
  echo     Pri ustanovke otmette galochku "Add python.exe to PATH".
  pause
  exit /b 1
)

rem --- virtualnoe okruzhenie ---
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Sozdayu virtualnoe okruzhenie .venv ...
  %PY% -m venv .venv || (echo [X] Ne udalos sozdat .venv & pause & exit /b 1)
)
set "VPY=.venv\Scripts\python.exe"

rem --- zavisimosti (stavim odin raz) ---
if not exist ".venv\.deps-ok" (
  echo [2/3] Ustanavlivayu zavisimosti iz requirements.txt ...
  "%VPY%" -m pip install --upgrade pip >nul
  "%VPY%" -m pip install -r requirements.txt || (echo [X] Oshibka ustanovki zavisimostei & pause & exit /b 1)
  echo ok> ".venv\.deps-ok"
)

echo [3/3] Zapuskayu server na http://127.0.0.1:%PORT%
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start "" http://127.0.0.1:%PORT%"
"%VPY%" run.py %PORT%

echo.
echo Server ostanovlen.
pause
