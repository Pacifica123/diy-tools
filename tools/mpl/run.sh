#!/usr/bin/env sh
set -eu
# Без cd: относительные пути из аргументов CLI считаются от папки пользователя.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v python3 >/dev/null 2>&1; then
  echo "mpl: не найден python3. Нужен Python 3.11 или новее." >&2
  exit 127
fi
exec python3 "$DIR/main.py" "$@"
