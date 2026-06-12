@echo off
setlocal
cd /d "%~dp0"
cargo run -- %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
