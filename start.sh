#!/usr/bin/env bash
# GeoLog — запуск в один шаг (macOS / Linux).
# Создаёт .venv, ставит зависимости один раз, поднимает сервер.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${1:-8000}"

PY=""
for v in python3.13 python3.12 python3.11 python3.10 python3 python; do
  [ -z "$PY" ] && command -v "$v" >/dev/null 2>&1 && PY="$v"
done
if [ -z "$PY" ]; then
  echo "❌ Python не найден. Установите Python 3.10+ (рекомендуется 3.12)."
  exit 1
fi
echo "[i] Python: $("$PY" --version 2>&1)"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Создаю виртуальное окружение .venv ..."
  "$PY" -m venv .venv
fi
VPY=".venv/bin/python"

if [ ! -f ".venv/.deps-ok" ]; then
  echo "[2/3] Устанавливаю зависимости из requirements.txt ..."
  "$VPY" -m pip install --upgrade pip >/dev/null
  "$VPY" -m pip install -r requirements.txt
  : > ".venv/.deps-ok"
fi

echo "[3/3] Сервер: http://127.0.0.1:${PORT}"
exec "$VPY" run.py "$PORT"
