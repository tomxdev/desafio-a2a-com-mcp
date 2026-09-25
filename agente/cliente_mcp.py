"""O agente por dentro: um host MCP de verdade, falando HTTP com o servidor.

Duas coisas nao obvias moram aqui.

A primeira e por que existe um `elicitation_callback` que nunca roda. O cliente
do SDK so declara a capability de elicitation quando um callback esta
registrado, e sem essa capability o servidor recusa o pedido com -32021. Mas
se a chamada for feita pelo caminho de alto nivel, o callback responde a
pergunta sozinho, o ciclo fecha por dentro e a Task nunca pausa: metade do
desafio evapora. A saida e registrar o callback so para declarar a capability
e dirigir o ciclo por `session.call_tool(..., allow_input_required=True)`, que
devolve o `input_required` cru sem nunca chamar o callback.

A segunda e que o `requestState` e opaco. Ele entra e sai daqui como string,
sem ser aberto, interpretado nem reconstruido, mesmo que o conteudo seja
legivel.

Este modulo tambem nao conhece regra de sala: conflito, politica e
alternativas sao decisao do servidor MCP. O que ele faz e traduzir protocolo.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

from mcp.client import Client
from mcp.types import InputRequiredResult

URL_PADRAO = os.environ.get("MCP_URL", "http://127.0.0.1:7301/mcp")

TOOL_DE_RESERVA = "reservar_sala"
RESOURCE_DA_POLITICA = "politica://uso"


class ElicitationInesperada(RuntimeError):
    """O callback rodou, quando ele so existe para declarar a capability."""


@dataclass(frozen=True)
class Pausa:
    """O servidor precisa de mais informacao antes de concluir.

    `request_state` e opaco: guardar e devolver sem tocar.
    """

    chave: str
    campo: str
    alternativas: list[str]
    request_state: str


@dataclass(frozen=True)
class Conclusao:
    """O servidor concluiu, com sucesso ou com erro de execucao da tool."""

    dados: dict[str, Any]
    texto: str
    erro: bool


def traceparent_derivado(recebido: str | None) -> str:
    """Mantem o trace-id de quem chamou e gera um span-id novo.

    O span-id pode ser novo, o trace-id nao: e ele que liga a chamada A2A ao
    request MCP no log do servidor. Sem um traceparent de entrada, abre um
    trace proprio para a chamada nao ficar orfa.
    """
    partes = (recebido or "").split("-")
    trace_id = partes[1] if len(partes) >= 3 and len(partes[1]) == 32 else secrets.token_hex(16)
    return f"00-{trace_id}-{secrets.token_hex(8)}-01"


async def _nunca_responder(ctx: Any, params: Any) -> Any:
    raise ElicitationInesperada(
        "O cliente tentou responder a elicitation sozinho. A pausa precisa "
        "chegar ate o cliente A2A: use session.call_tool(allow_input_required=True)."
    )


class HostMCP:
    """Mantem um cliente MCP vivo e traduz o ciclo de MRTR.

    O objeto cliente vive entre chamadas, o que e normal e recomendado. O que
    nao pode e inferir versao, capabilities ou contexto de um request anterior:
    cada request carrega o proprio `_meta`, e disso o SDK cuida.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or URL_PADRAO
        self._cliente: Client | None = None
        self._tools: list[str] = []
        self._politica: str | None = None

    async def __aenter__(self) -> "HostMCP":
        self._cliente = Client(self._url, elicitation_callback=_nunca_responder)
        await self._cliente.__aenter__()
        await self._descobrir()
        return self

    async def __aexit__(self, *excecao: Any) -> None:
        if self._cliente is not None:
            await self._cliente.__aexit__(*excecao)
            self._cliente = None

    @property
    def tools(self) -> list[str]:
        return list(self._tools)

    async def _descobrir(self) -> None:
        """tools/list antes da primeira chamada, sempre.

        A lista vem do servidor em runtime; nada de lista fixa no codigo.
        """
        listagem = await self._sessao.list_tools()
        self._tools = [t.name for t in listagem.tools]
        if TOOL_DE_RESERVA not in self._tools:
            raise RuntimeError(
                f"o servidor MCP nao expoe {TOOL_DE_RESERVA!r}; encontrei {self._tools}"
            )

    @property
    def _sessao(self):
        if self._cliente is None:
            raise RuntimeError("o host MCP precisa ser aberto com 'async with'")
        return self._cliente.session

    async def versao_da_politica(self, traceparent: str | None = None) -> str:
        """Le o resource e extrai a versao declarada na primeira linha.

        Resource, e nao tool, porque a escolha de ler e da aplicacao.
        """
        if self._politica is None:
            leitura = await self._sessao.read_resource(
                RESOURCE_DA_POLITICA, meta={"traceparent": traceparent_derivado(traceparent)}
            )
            texto = "".join(getattr(c, "text", "") for c in leitura.contents)
            self._politica = texto.splitlines()[0].split(":", 1)[1].strip()
        return self._politica

    async def reservar(
        self, argumentos: dict[str, Any], traceparent: str | None = None
    ) -> Pausa | Conclusao:
        """Primeira tentativa do `tools/call`."""
        return self._traduzir(
            await self._sessao.call_tool(
                TOOL_DE_RESERVA,
                argumentos,
                meta={"traceparent": traceparent_derivado(traceparent)},
                allow_input_required=True,
            )
        )

    async def retomar(
        self,
        argumentos: dict[str, Any],
        pausa: Pausa,
        resposta: dict[str, Any],
        traceparent: str | None = None,
    ) -> Pausa | Conclusao:
        """Repete o `tools/call` original levando a resposta e o estado.

        O SDK gera um id de JSON-RPC novo a cada chamada, que e o que a spec
        exige: sao requests independentes, e reaproveitar o id quebra na
        verificacao.
        """
        return self._traduzir(
            await self._sessao.call_tool(
                TOOL_DE_RESERVA,
                argumentos,
                input_responses={pausa.chave: resposta},
                request_state=pausa.request_state,  # ecoado sem modificacao
                meta={"traceparent": traceparent_derivado(traceparent)},
                allow_input_required=True,
            )
        )

    @staticmethod
    def _traduzir(resultado: Any) -> Pausa | Conclusao:
        if not isinstance(resultado, InputRequiredResult):
            return Conclusao(
                dados=resultado.structured_content or {},
                texto=" ".join(getattr(c, "text", "") for c in (resultado.content or [])),
                erro=bool(resultado.is_error),
            )

        chave = next(iter(resultado.input_requests or {}))
        esquema = (resultado.input_requests or {})[chave].params.requested_schema
        # O schema da elicitation e plano e tem uma propriedade so. Ler o nome
        # dela em vez de fixar "sala" mantem o agente no papel de tradutor.
        (campo, definicao), = esquema["properties"].items()
        opcoes = definicao.get("enum") or [definicao["const"]]
        return Pausa(
            chave=chave,
            campo=campo,
            alternativas=list(opcoes),
            request_state=resultado.request_state or "",
        )


def resposta_de_aceite(pausa: Pausa, escolha: str) -> dict[str, Any]:
    return {"action": "accept", "content": {pausa.campo: escolha}}


def resposta_de_recusa() -> dict[str, Any]:
    return {"action": "decline"}
