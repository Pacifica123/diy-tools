@echo off
setlocal
cd /d "%~dp0"
where npm >nul 2>nul
if errorlevel 1 (
  echo Ошибка: npm не найден. Установите Node.js 20 или новее ^(вместе с npm^) и добавьте его в PATH.
  exit /b 9009
)
if not exist "node_modules\" (
  echo Ошибка: зависимости не установлены ^(нет папки node_modules^).
  echo Один раз выполните в папке инструмента: npm install
  exit /b 1
)
call npm run dev
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
