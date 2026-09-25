"""O agente por fora: servidor A2A no binding JSON-RPC.

Atende `SendMessage` e `GetTask` em /a2a e publica o Agent Card no
well-known. Este modulo so roteia: quem traduz entre o servidor MCP e a Task
e `ponte.py`.

O agente nao decide nada de dominio. Conflito, politica e alternativas sao
resposta do servidor MCP; aqui a Task so se move.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import ponte
import tarefas as t
from card import agent_card
from cliente_mcp import HostMCP

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


async def _card(request: Request) -> JSONResponse:
    return JSONResponse(agent_card())


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
        tarefa = await ponte.abrir(host, tarefas, mensagem, traceparent)
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

    await ponte.continuar(host, tarefa, mensagem, traceparent)
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
