#!/usr/bin/env sh
set -eu
# Каталог не меняется: workspace ищется от папки, из которой запущена команда.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo "Ошибка: python3 не найден. Установите Python 3.11 или новее и повторите запуск." >&2
  exit 127
fi
exec python3 "$DIR/devctl.py" "$@"
