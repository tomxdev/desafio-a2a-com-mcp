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

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    ElicitationResult,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.request_state import RequestStateSecurity

import dominio
import regras
from elicitacao import Escolha, escolha_de_sala
from dominio import (
    POLITICA,
    SALAS,
    VERSAO_DA_POLITICA,
    ConflitoOut,
    Disponibilidade,
    ListaDeSalas,
    ReservaOut,
)
from log import log_middleware
from seguranca import SegredoInvalido, chave_do_request_state

HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORTA = int(os.environ.get("MCP_PORT", "7301"))
CAMINHO = os.environ.get("MCP_PATH", "/mcp")
if not CAMINHO.startswith("/"):
    # No Git Bash, um MCP_PATH="/mcp" chega aqui convertido para um caminho do
    # Windows. Sem esta checagem o erro so aparece la dentro do roteador.
    print(
        f"[mcp] MCP_PATH invalido: {CAMINHO!r}. O caminho precisa comecar com '/'. "
        "No Git Bash, exporte MSYS_NO_PATHCONV=1 para desligar a conversao de caminhos.",
        file=sys.stderr,
    )
    raise SystemExit(1)

# Entre 5 e 30 minutos, como o enunciado exige. O intervalo precisa cobrir uma
# pausa de Task do lado A2A sem manter um token util por tempo demais.
VALIDADE_DO_REQUEST_STATE = 900.0

try:
    _CHAVE = chave_do_request_state()
except SegredoInvalido as erro:
    print(f"[mcp] {erro}", file=sys.stderr)
    raise SystemExit(1) from None

mcp = MCPServer(
    "central-de-salas",
    version="1.0.0",
    middleware=[log_middleware],
    # Chave fixa, vinda do ambiente, e nao a ephemeral que o SDK instala por
    # padrao: com a ephemeral o token morre junto com o processo, e o retry
    # precisa funcionar mesmo depois de um restart, porque o estado viaja no
    # token e nao no servidor.
    request_state_security=RequestStateSecurity(keys=[_CHAVE], ttl=VALIDADE_DO_REQUEST_STATE),
)


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


@mcp.tool()
async def reservar_sala(
    sala: str,
    inicio: str,
    fim: str,
    responsavel: str,
    escolha: Annotated[ElicitationResult[Escolha], Resolve(escolha_de_sala)],
) -> ReservaOut:
    """Reserva uma sala. Se o intervalo estiver ocupado, pergunta qual alternativa usar."""
    # O union e obrigatorio: com a anotacao desembrulhada, uma recusa viraria
    # erro de execucao em vez de concluir sem reservar.
    match escolha:
        case DeclinedElicitation() | CancelledElicitation():
            return ReservaOut(reservado=False, motivo="recusado")
        case AcceptedElicitation(data=decidida):
            alvo = decidida.sala
        case _:  # pragma: no cover - o SDK so produz os tres acima
            raise ToolError("Resposta de elicitation inesperada")

    nova = dominio.criar_reserva(alvo, inicio, fim, responsavel)
    return ReservaOut(
        reserva=nova.id,
        reservado=True,
        sala=alvo,
        inicio=inicio,
        fim=fim,
        responsavel=responsavel,
        politica=VERSAO_DA_POLITICA,
    )


@mcp.resource(
    "politica://uso",
    name="politica-de-uso",
    description="A politica de uso das salas, com a versao declarada na primeira linha.",
    mime_type="text/markdown",
)
def politica_de_uso() -> str:
    """O conteudo de dados/politica-de-uso.md.

    Resource, e nao tool, porque quem controla a leitura e a aplicacao: o
    agente decide ler a politica para extrair a versao que vai no artifact.
    """
    return POLITICA


def criar_app():
    """O app ASGI do transporte Streamable HTTP."""
    return mcp.streamable_http_app(streamable_http_path=CAMINHO, stateless_http=True, host=HOST)


def main() -> None:
    import uvicorn

    print(f"[mcp] central-de-salas em http://{HOST}:{PORTA}{CAMINHO}", file=sys.stderr, flush=True)
    uvicorn.run(criar_app(), host=HOST, port=PORTA, log_level="warning")


if __name__ == "__main__":
    main()
