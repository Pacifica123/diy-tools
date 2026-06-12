@echo off
setlocal
cd /d "%~dp0"
python main.py %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
