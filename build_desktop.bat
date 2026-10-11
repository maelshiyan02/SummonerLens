@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  Rebuild the SummonerLens desktop shell (Flutter Windows)
rem  Double-click this file.  Takes a few minutes.
rem ============================================================

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
  echo [ERROR] Python not found. Install Python 3.8+ or set SUMMONERLENS_PYTHON.
  pause
  exit /b 1
)

echo ============================================================
echo  Rebuilding SummonerLens desktop shell
echo    python : %PY%
echo    This takes a few minutes. Do NOT close this window.
echo ============================================================
echo.

echo [1/3] flutter analyze
%PY% tools\flutter_task.py analyze
echo.

echo [2/3] flutter build windows --release
%PY% tools\flutter_task.py build
echo.

set "EXE=%~dp0app\build\windows\x64\runner\Release\summonerlens.exe"
if exist "%EXE%" (
  echo [3/3] DONE -^> shell rebuilt.
  echo       Next: double-click  run_desktop.bat  to launch it.
) else (
  echo [3/3] BUILD FAILED -^> no exe was produced.
  echo       See the text above and  build\flutter_logs\
)
echo.
pause
