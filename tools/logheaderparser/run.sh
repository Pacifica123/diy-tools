#!/usr/bin/env sh
set -eu
# Каталог не меняется: относительные пути в аргументах считаются от папки, где запущена команда.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v cargo >/dev/null 2>&1; then
  echo "Ошибка: cargo не найден. Установите Rust (https://rustup.rs) и повторите запуск." >&2
  exit 127
fi
exec cargo run --quiet --manifest-path "$DIR/Cargo.toml" -- "$@"
