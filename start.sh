#!/usr/bin/env bash
# GeoLog — запуск в один шаг (macOS / Linux).
# Создаёт .venv, ставит зависимости один раз, поднимает сервер.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PORT="${1:-8000}"

PY=""
command -v python3 >/dev/null 2>&1 && PY=python3
[ -z "$PY" ] && command -v python >/dev/null 2>&1 && PY=python
if [ -z "$PY" ]; then
  echo "❌ Python не найден. Установите Python 3.9+."
  exit 1
fi

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
