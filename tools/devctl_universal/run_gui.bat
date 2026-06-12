@echo off
setlocal
cd /d "%~dp0"
python gui\devctl_gui.py
if errorlevel 1 (
  echo.
  echo GUI завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
