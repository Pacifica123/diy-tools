@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (
  echo Ошибка: не найден python. Установите Python 3.11 или новее и добавьте его в PATH.
  exit /b 9009
)
python "%~dp0src\cli.py" %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
