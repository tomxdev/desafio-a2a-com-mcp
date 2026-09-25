"""O agente por fora: servidor A2A no binding JSON-RPC.

Atende `SendMessage` e `GetTask` em /a2a e publica o Agent Card no
well-known. Por dentro, cada pedido vira uma chamada ao servidor MCP pelo
`HostMCP` — por HTTP, como um cliente MCP de verdade.

O agente nao decide nada de dominio: conflito, politica e alternativas sao
resposta do servidor MCP. O que ele faz aqui e mover a Task.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import tarefas as t
from card import agent_card
from cliente_mcp import Conclusao, HostMCP
from pedido import PedidoInvalido, interpretar_reserva

PEDIDO_INVALIDO = -32602
TASK_NAO_ENCONTRADA = -32001
TASK_TERMINAL = -32600
METODO_DESCONHECIDO = -32601


def _erro(id_rpc: Any, codigo: int, mensagem: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": id_rpc, "error": {"code": codigo, "message": mensagem}}
    )


def _ok(id_rpc: Any, resultado: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_rpc, "result": resultado})


def _texto_de(mensagem: dict[str, Any]) -> str:
    return " ".join(p.get("text", "") for p in mensagem.get("parts") or [])


async def _card(request: Request) -> JSONResponse:
    return JSONResponse(agent_card())


async def _concluir(tarefa: t.Task, conclusao: Conclusao, host: HostMCP) -> None:
    """Traduz a resposta do servidor MCP no desfecho da Task."""
    if conclusao.erro:
        # A mensagem exata da tool precisa chegar ao cliente A2A.
        tarefa.mover_para(t.FAILED, conclusao.texto)
        return

    dados = conclusao.dados
    if not dados.get("reservado"):
        tarefa.mover_para(t.CANCELED, dados.get("motivo") or "recusado")
        return

    tarefa.anexar(
        "reserva",
        {
            "reserva": dados.get("reserva"),
            "sala": dados.get("sala"),
            "inicio": dados.get("inicio"),
            "fim": dados.get("fim"),
            "responsavel": dados.get("responsavel"),
            # A versao vem do resource lido pelo agente, nao do que a tool
            # devolveu: e a aplicacao que escolhe ler a politica.
            "politica": await host.versao_da_politica(),
        },
    )
    tarefa.mover_para(
        t.COMPLETED, f"Reserva {dados.get('reserva')} confirmada na {dados.get('sala')}."
    )


async def _abrir_tarefa(
    host: HostMCP, tarefas: t.Tarefas, mensagem: dict[str, Any], traceparent: str | None
) -> t.Task:
    tarefa = tarefas.abrir()
    tarefa.registrar(mensagem)

    try:
        pedido = interpretar_reserva(_texto_de(mensagem))
    except PedidoInvalido as erro:
        tarefa.mover_para(t.FAILED, str(erro))
        return tarefa

    tarefa.argumentos = pedido.como_argumentos()
    tarefa.mover_para(t.WORKING)

    resultado = await host.reservar(tarefa.argumentos, traceparent)
    if isinstance(resultado, Conclusao):
        await _concluir(tarefa, resultado, host)
    else:
        # Ponto de costura: e aqui que a Fase 11 poe a Task em
        # TASK_STATE_INPUT_REQUIRED e guarda o requestState.
        tarefa.mover_para(t.FAILED, "pausa ainda nao implementada")
    return tarefa


async def _continuar_tarefa(tarefa: t.Task, mensagem: dict[str, Any]) -> None:
    # A continuacao chega na Fase 11. Aqui so o registro da mensagem.
    tarefa.registrar(mensagem)


async def _send_message(
    id_rpc: Any, params: dict[str, Any], request: Request, traceparent: str | None
) -> JSONResponse:
    mensagem = params.get("message") or {}
    if not mensagem.get("parts"):
        return _erro(id_rpc, PEDIDO_INVALIDO, "message.parts ausente")

    host: HostMCP = request.app.state.host
    tarefas: t.Tarefas = request.app.state.tarefas

    identificador = mensagem.get("taskId")
    if not identificador:
        tarefa = await _abrir_tarefa(host, tarefas, mensagem, traceparent)
        return _ok(id_rpc, {"task": tarefa.como_json()})

    tarefa = tarefas.buscar(identificador)
    if tarefa is None:
        return _erro(id_rpc, TASK_NAO_ENCONTRADA, f"Task nao encontrada: {identificador}")
    if tarefa.terminada:
        # Estado terminal e definitivo: nao volta a WORKING.
        return _erro(
            id_rpc,
            TASK_TERMINAL,
            f"Task {identificador} ja terminou em {tarefa.estado} e nao aceita continuacao",
        )

    await _continuar_tarefa(tarefa, mensagem)
    return _ok(id_rpc, {"task": tarefa.como_json()})


async def _get_task(id_rpc: Any, params: dict[str, Any], request: Request) -> JSONResponse:
    identificador = params.get("id")
    tarefa = request.app.state.tarefas.buscar(identificador)
    if tarefa is None:
        return _erro(id_rpc, TASK_NAO_ENCONTRADA, f"Task nao encontrada: {identificador}")
    return _ok(id_rpc, {"task": tarefa.como_json()})


async def _jsonrpc(request: Request) -> JSONResponse:
    try:
        corpo = await request.json()
    except Exception:
        return _erro(None, -32700, "JSON invalido")

    id_rpc = corpo.get("id")
    metodo = corpo.get("method")
    params = corpo.get("params") or {}
    traceparent = request.headers.get("traceparent")

    if metodo == "SendMessage":
        return await _send_message(id_rpc, params, request, traceparent)
    if metodo == "GetTask":
        return await _get_task(id_rpc, params, request)
    return _erro(id_rpc, METODO_DESCONHECIDO, f"metodo nao suportado: {metodo}")


def criar_app(caminho: str = "/a2a") -> Starlette:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # Um unico cliente MCP vivo para o processo inteiro. Manter o objeto
        # vivo entre chamadas e normal; o que nao pode e inferir estado de
        # protocolo de um request anterior, e disso o _meta cuida.
        async with HostMCP() as host:
            app.state.host = host
            app.state.tarefas = t.Tarefas()
            yield

    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", _card, methods=["GET"]),
            Route(caminho, _jsonrpc, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
