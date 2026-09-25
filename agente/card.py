"""O Agent Card: a identidade publica do agente.

E por aqui que outro agente descobre a skill de reserva, sem saber nada do
que existe por dentro. Opacidade e o ponto: quem chama nao tem como saber se
atras disto ha um modelo, um grafo ou um `if`.

A forma e a da v1.0: `supportedInterfaces` (e nao `interfaces`), com
`protocolBinding` (e nao `preferredTransport`) dentro de cada entrada.
"""

from __future__ import annotations

import os
from typing import Any

HOST = os.environ.get("AGENTE_HOST", "127.0.0.1")
PORTA = int(os.environ.get("AGENTE_PORT", "7300"))
CAMINHO = os.environ.get("AGENTE_PATH", "/a2a")

URL_DO_ENDPOINT = os.environ.get("AGENTE_URL", f"http://{HOST}:{PORTA}{CAMINHO}")

EXEMPLO = (
    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
    "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
)


def agent_card() -> dict[str, Any]:
    return {
        "name": "Central de Salas",
        "description": "Reserva salas de reuniao da Hill Valley Tech.",
        "provider": {
            "organization": "Hill Valley Tech",
            "url": "https://hillvalley.example",
        },
        "version": "1.0.0",
        "supportedInterfaces": [
            {
                "url": URL_DO_ENDPOINT,
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        # Fora de escopo por decisao do enunciado: sem streaming, sem push,
        # sem card estendido autenticado.
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "reservar-sala",
                "name": "Reservar sala",
                "description": (
                    "Reserva uma sala em um intervalo. Se houver conflito, "
                    "pergunta qual alternativa usar."
                ),
                "tags": ["salas", "agenda"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
                "examples": [EXEMPLO],
            }
        ],
    }
