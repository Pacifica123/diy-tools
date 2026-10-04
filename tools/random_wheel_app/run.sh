#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Не найден python3. Установите Python 3.11 или новее и повторите запуск." >&2
  exit 127
fi
python3 main.py "$@"
