"""A chave que protege a integridade do `requestState` do MRTR.

O `requestState` volta pelas maos do cliente, entao e entrada controlada por
atacante: a spec manda proteger a integridade dele e rejeitar o que nao
passar na verificacao. Quem sela e abre e o SDK; o que mora aqui e so a
chave, que vem do ambiente e nunca do codigo, porque o repositorio e publico.
"""

from __future__ import annotations

import os
from typing import Mapping

VARIAVEL = "REQUEST_STATE_SECRET"
MINIMO_DE_BYTES = 32

COMO_GERAR = 'python -c "import secrets; print(secrets.token_hex(32))"'


class SegredoInvalido(RuntimeError):
    """A chave nao foi definida, ou e curta demais para valer alguma coisa."""


def _bytes_de(bruto: str) -> bytes:
    """Aceita hexadecimal (o formato que o README manda gerar) ou texto cru."""
    try:
        return bytes.fromhex(bruto)
    except ValueError:
        return bruto.encode("utf-8")


def chave_do_request_state(ambiente: Mapping[str, str] | None = None) -> bytes:
    bruto = (ambiente if ambiente is not None else os.environ).get(VARIAVEL, "").strip()
    if not bruto:
        raise SegredoInvalido(
            f"{VARIAVEL} nao definido. Gere a chave com:\n    {COMO_GERAR}\n"
            f"e exporte antes de subir o servidor (veja .env.example)."
        )

    chave = _bytes_de(bruto)
    if len(chave) < MINIMO_DE_BYTES:
        raise SegredoInvalido(
            f"{VARIAVEL} tem {len(chave)} bytes, e o minimo sao {MINIMO_DE_BYTES}. "
            f"Gere uma chave nova com:\n    {COMO_GERAR}"
        )
    return chave
