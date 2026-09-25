#!/usr/bin/env bash
# Sobe o agente A2A (JSON-RPC, porta 7300 por padrao).
set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$raiz/.env" ]; then
  set -a; . "$raiz/.env"; set +a
fi

python="$raiz/.venv/bin/python"
[ -x "$python" ] || python="$(command -v python3 || command -v python)"
exec "$python" "$raiz/agente/servidor.py"
