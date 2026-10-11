@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  SummonerLens - open dashboard in your browser
rem  Double-click this file.  Close the window to stop.
rem ============================================================

rem ---- locate a usable Python: venv -> system -> PATH launcher ----
set "PY="
if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\summonerlens\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\summonerlens\Scripts\python.exe"
if not defined PY if exist "C:\Python38\python.exe" set "PY=C:\Python38\python.exe"
if not defined PY for %%C in (py python python3) do if not defined PY (where %%C >nul 2>nul && set "PY=%%C")

if "%~1"=="--check" (
  echo [check] root   = %CD%
  echo [check] python = %PY%
  exit /b 0
)

if not defined PY (
  echo [ERROR] Python not found.
  echo         Option A: install Python 3.8+  or set SUMMONERLENS_PYTHON
  echo         Option B: just double-click  app\web\index.html  ^(offline^)
  pause
  exit /b 1
)

echo ============================================================
echo  SummonerLens dashboard  (browser mode)
echo    python : %PY%
echo    A browser tab will open automatically.
echo    CLOSE THIS WINDOW to stop the local server.
echo ============================================================
echo.
%PY% python\bridge\serve.py --port=0 --open

echo.
echo [stopped] local server closed.
pause
