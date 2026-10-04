@echo off
setlocal
rem Каталог не меняется: workspace ищется от папки, из которой запущена команда.
python "%~dp0devctl.py" %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
