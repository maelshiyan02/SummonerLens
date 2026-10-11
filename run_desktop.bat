@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  SummonerLens - launch the Flutter desktop shell
rem  Double-click this file.
rem ============================================================

set "EXE=%~dp0app\build\windows\x64\runner\Release\summonerlens.exe"

rem ---- locate a usable Python: venv -> system -> PATH launcher ----
set "PY="
if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\summonerlens\Scripts\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\summonerlens\Scripts\python.exe"
if not defined PY if exist "C:\Python38\python.exe" set "PY=C:\Python38\python.exe"
if not defined PY for %%C in (py python python3) do if not defined PY (where %%C >nul 2>nul && set "PY=%%C")

if "%~1"=="--check" (
  echo [check] root   = %CD%
  echo [check] python = %PY%
  echo [check] exe    = %EXE%
  exit /b 0
)

if not exist "%EXE%" (
  echo [ERROR] desktop shell is not built yet.
  echo         Build it with:  python tools\flutter_task.py build
  pause
  exit /b 1
)

rem ---- tell the shell which python to use (only when it is a real path) ----
if defined PY ( echo %PY% | find /I ".exe" >nul && set "SUMMONERLENS_PYTHON=%PY%" )

echo Launching SummonerLens desktop shell ...
echo    python : %PY%
echo    exe    : %EXE%
echo.
start "" "%EXE%"
