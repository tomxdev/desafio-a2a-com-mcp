#!/usr/bin/env bash
# Sobe o servidor MCP (Streamable HTTP, porta 7301 por padrao).
set -euo pipefail
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$raiz/.env" ]; then
  set -a; . "$raiz/.env"; set +a
fi
if [ -z "${REQUEST_STATE_SECRET:-}" ]; then
  echo "REQUEST_STATE_SECRET nao definido. Copie .env.example para .env e gere a chave com:" >&2
  echo '  python3 -c "import secrets; print(secrets.token_hex(32))"' >&2
  exit 1
fi

python="$raiz/.venv/bin/python"
[ -x "$python" ] || python="$(command -v python3 || command -v python)"
exec "$python" "$raiz/servidor-mcp/servidor.py"
