@echo off
setlocal
rem Каталог не меняется: относительные пути в аргументах считаются от папки, где запущена команда.
where cargo >nul 2>nul
if errorlevel 1 (
  echo Ошибка: cargo не найден. Установите Rust ^(https://rustup.rs^) и повторите запуск.
  exit /b 9009
)
cargo run --quiet --manifest-path "%~dp0Cargo.toml" -- %*
if errorlevel 1 (
  echo.
  echo Инструмент завершился с ошибкой. См. сообщение выше.
  exit /b %errorlevel%
)
endlocal
