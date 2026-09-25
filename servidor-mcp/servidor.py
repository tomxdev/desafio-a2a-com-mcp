"""Servidor MCP da central de salas da Hill Valley Tech.

Transporte Streamable HTTP em endpoint unico, na porta 7301 por padrao. O
modelo e stateless: cada request carrega o proprio `_meta` com a versao do
protocolo e as capabilities do cliente, e nada e inferido de um request
anterior. O SDK rejeita sozinho, com -32602 e HTTP 400, o request que chegar
sem esses campos.

Sobe com:  python "servidor-mcp/servidor.py"
"""

from __future__ import annotations

import os
import sys

from mcp.server import MCPServer

import regras
from dominio import SALAS, ConflitoOut, Disponibilidade, ListaDeSalas
from log import log_middleware

HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORTA = int(os.environ.get("MCP_PORT", "7301"))
CAMINHO = os.environ.get("MCP_PATH", "/mcp")

mcp = MCPServer("central-de-salas", version="1.0.0", middleware=[log_middleware])


@mcp.tool()
def listar_salas() -> ListaDeSalas:
    """Lista todas as salas com capacidade e recursos."""
    # Devolver um modelo, e nao uma lista: o SDK so faz o bloco de texto e o
    # structuredContent baterem quando a saida e um objeto.
    return ListaDeSalas(salas=SALAS)


@mcp.tool()
def consultar_disponibilidade(sala: str, inicio: str, fim: str) -> Disponibilidade:
    """Diz se uma sala esta livre no intervalo, e quais reservas conflitam."""
    # As mesmas validacoes da reserva, com os mesmos erros de execucao.
    _, comeco, termino = regras.validar_pedido(sala, inicio, fim)
    colisoes = regras.conflitos(sala, comeco, termino)
    return Disponibilidade(
        sala=sala,
        livre=not colisoes,
        conflitos=[
            ConflitoOut(id=r.id, inicio=r.inicio, fim=r.fim, responsavel=r.responsavel)
            for r in colisoes
        ],
    )


def criar_app():
    """O app ASGI do transporte Streamable HTTP."""
    return mcp.streamable_http_app(streamable_http_path=CAMINHO, stateless_http=True, host=HOST)


def main() -> None:
    import uvicorn

    print(f"[mcp] central-de-salas em http://{HOST}:{PORTA}{CAMINHO}", file=sys.stderr, flush=True)
    uvicorn.run(criar_app(), host=HOST, port=PORTA, log_level="warning")


if __name__ == "__main__":
    main()
