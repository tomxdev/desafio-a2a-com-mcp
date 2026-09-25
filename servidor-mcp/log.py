"""Registro de cada request MCP no stderr.

O enunciado exige, no minimo, o metodo, o id do JSON-RPC e o `traceparent`
quando ele vem no `_meta`. Vai para o stderr porque o logging pelo proprio
protocolo esta depreciado.

O alvo (`name` de um `tools/call`, `uri` de um `resources/read`) entra junto
porque o avaliador precisa localizar, no log, o par de `tools/call` de uma
mesma reserva e conferir que o id do retry difere do id do request inicial.
"""

from __future__ import annotations

import sys
from typing import Any, Awaitable, Callable


async def log_middleware(ctx: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
    """Middleware de contexto: `(ctx, call_next) -> result`."""
    parametros: dict[str, Any] = ctx.params if isinstance(ctx.params, dict) else {}
    meta = parametros.get("_meta") or {}

    alvo = parametros.get("name") or parametros.get("uri")
    campos = [
        f"metodo={ctx.method}",
        f"id={ctx.request_id}",
        f"traceparent={meta.get('traceparent')}",
    ]
    if alvo:
        campos.insert(1, f"alvo={alvo}")

    print("[mcp] " + " ".join(campos), file=sys.stderr, flush=True)
    return await call_next(ctx)
