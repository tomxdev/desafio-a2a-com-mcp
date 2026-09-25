"""Agente da central de salas: servidor A2A por fora, host MCP por dentro.

Sobe com:  python "agente/servidor.py"

O servidor MCP precisa estar de pe antes, porque o agente descobre as tools
por tools/list na subida.
"""

from __future__ import annotations

import os
import sys

from servidor_a2a import criar_app

HOST = os.environ.get("AGENTE_HOST", "127.0.0.1")
PORTA = int(os.environ.get("AGENTE_PORT", "7300"))
CAMINHO = os.environ.get("AGENTE_PATH", "/a2a")

if not CAMINHO.startswith("/"):
    print(
        f"[a2a] AGENTE_PATH invalido: {CAMINHO!r}. O caminho precisa comecar com '/'. "
        "No Git Bash, exporte MSYS_NO_PATHCONV=1 para desligar a conversao de caminhos.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main() -> None:
    import uvicorn

    print(f"[a2a] central-de-salas em http://{HOST}:{PORTA}{CAMINHO}", file=sys.stderr, flush=True)
    print(f"[a2a] card em http://{HOST}:{PORTA}/.well-known/agent-card.json", file=sys.stderr, flush=True)
    uvicorn.run(criar_app(CAMINHO), host=HOST, port=PORTA, log_level="warning")


if __name__ == "__main__":
    main()
