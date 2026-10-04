#!/usr/bin/env sh
set -eu
cd -- "$(dirname -- "$0")"
if ! command -v npm >/dev/null 2>&1; then
  echo "Ошибка: npm не найден. Установите Node.js 20 или новее (вместе с npm) и повторите запуск." >&2
  exit 127
fi
if [ ! -d node_modules ]; then
  echo "Ошибка: зависимости не установлены (нет папки node_modules)." >&2
  echo "Один раз выполните в папке инструмента: npm install" >&2
  exit 1
fi
npm run dev
