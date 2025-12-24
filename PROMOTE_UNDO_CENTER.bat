@echo off
setlocal
cd /d "%~dp0\.."
pwsh -ExecutionPolicy Bypass -NoProfile -File tools\promote_center.ps1 -Mode Undo
pause
