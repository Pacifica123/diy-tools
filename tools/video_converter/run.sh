#!/usr/bin/env sh
set -eu
# Лаунчер не меняет текущую папку: относительные пути в аргументах считаются от папки, где вы его запустили.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo "Ошибка: python3 не найден. Установите Python 3.11 или новее." >&2
  exit 127
fi
exec python3 "$DIR/src/cli.py" "$@"
