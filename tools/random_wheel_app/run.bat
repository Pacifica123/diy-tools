@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Не найден Python. Установите Python 3.11 или новее и повторите запуск.
  exit /b 1
)
python main.py %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
