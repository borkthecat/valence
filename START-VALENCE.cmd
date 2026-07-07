@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0START-VALENCE.ps1"
if errorlevel 1 (
  echo.
  echo Valence did not start successfully.
  pause
  exit /b 1
)
