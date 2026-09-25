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

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, create_model

import dominio
import regras
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


PERGUNTA = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


class Escolha(BaseModel):
    """A sala que vai ser reservada de fato."""

    sala: str = Field(description="Sala alternativa escolhida")


def _escolha_entre(opcoes: list[str]) -> type[BaseModel]:
    """Um modelo cujo campo `sala` so aceita as alternativas calculadas.

    O enum e por pedido, entao o tipo precisa ser montado na hora: `Elicit`
    recebe um tipo, nao um schema solto.
    """
    return create_model(
        "Escolha",
        sala=(Literal[tuple(opcoes)], Field(description="Sala alternativa escolhida")),  # type: ignore[valid-type]
    )


async def escolha_de_sala(sala: str, inicio: str, fim: str) -> Escolha | Elicit[Escolha]:
    """Resolve qual sala reservar, perguntando ao cliente so quando precisa.

    Este e o lado servidor do MRTR. Nao existe canal de volta: quando falta
    informacao, o resolver nao pergunta e espera, ele faz a resposta terminar
    em `input_required` com a elicitation e um `requestState` opaco. O cliente
    volta com um `tools/call` novo levando a resposta e o estado ecoado.

    O resolver roda em todas as rodadas, inclusive no retry, entao ele repete
    as validacoes e o calculo de alternativas.
    """
    pedida, comeco, termino = regras.validar_pedido(sala, inicio, fim)

    if regras.esta_livre(sala, comeco, termino):
        return Escolha(sala=sala)

    opcoes = regras.alternativas(pedida, comeco, termino)
    if not opcoes:
        raise ToolError(regras.ERRO_SEM_ALTERNATIVAS)

    return Elicit(PERGUNTA, _escolha_entre(opcoes))


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
