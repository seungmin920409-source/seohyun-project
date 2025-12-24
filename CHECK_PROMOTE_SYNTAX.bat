@echo off
setlocal
cd /d "%~dp0"
pwsh -NoProfile -ExecutionPolicy Bypass -File ".\CHECK_PROMOTE_SYNTAX.ps1"
pause
