@echo off
setlocal
cd /d "%~dp0"
python src\cli.py %*
exit /b %errorlevel%
