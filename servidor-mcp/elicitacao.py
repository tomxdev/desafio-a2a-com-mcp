"""O lado servidor do MRTR: quando perguntar, e o que perguntar.

Nao existe canal de volta no transporte stateless. Quando falta informacao, o
resolver nao pergunta e espera: ele faz a resposta terminar em
`input_required`, com a elicitation e um `requestState` opaco. O cliente volta
com um `tools/call` novo levando a resposta e o estado ecoado.

Fica separado de `servidor.py` para poder ser testado sem subir o transporte.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import Elicit
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

import regras

PERGUNTA = "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."
DESCRICAO_DO_CAMPO = "Sala alternativa escolhida"


class Escolha(BaseModel):
    """A sala que vai ser reservada de fato."""

    sala: str = Field(description=DESCRICAO_DO_CAMPO)


def escolha_entre(opcoes: list[str]) -> type[BaseModel]:
    """Um modelo cujo campo `sala` so aceita as alternativas calculadas.

    O enum e por pedido, entao o tipo precisa ser montado na hora: `Elicit`
    recebe um tipo, nao um schema solto.
    """
    from pydantic import create_model

    return create_model(
        "Escolha",
        sala=(Literal[tuple(opcoes)], Field(description=DESCRICAO_DO_CAMPO)),  # type: ignore[valid-type]
    )


async def escolha_de_sala(sala: str, inicio: str, fim: str) -> Escolha | Elicit[Escolha]:
    """Resolve qual sala reservar, perguntando ao cliente so quando precisa.

    Roda em todas as rodadas, inclusive no retry, entao repete as validacoes
    e o calculo de alternativas.
    """
    pedida, comeco, termino = regras.validar_pedido(sala, inicio, fim)

    if regras.esta_livre(sala, comeco, termino):
        return Escolha(sala=sala)

    opcoes = regras.alternativas(pedida, comeco, termino)
    if not opcoes:
        raise ToolError(regras.ERRO_SEM_ALTERNATIVAS)

    return Elicit(PERGUNTA, escolha_entre(opcoes))
