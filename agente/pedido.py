"""Leitura do pedido em formato fixo.

Nada de linguagem natural e nada de LLM: o texto chega num formato fechado e
o agente decide por regra. Dado o mesmo pedido, o mesmo resultado, sempre.

    reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>

A resposta a uma pausa tambem e fixa:

    escolha=<id da sala>   para aceitar
    escolha=recusar        para recusar
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CAMPOS_DA_RESERVA = ("sala", "inicio", "fim", "responsavel")
RECUSAR = "recusar"

# `responsavel` pode ter espacos, entao cada campo vai ate o proximo rotulo.
_CAMPO = re.compile(
    r"(?P<chave>sala|inicio|fim|responsavel)\s*=\s*(?P<valor>.*?)(?=\s+(?:sala|inicio|fim|responsavel)\s*=|$)"
)
_ESCOLHA = re.compile(r"^escolha\s*=\s*(?P<valor>\S.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class Reserva:
    """Um pedido de reserva bem formado."""

    sala: str
    inicio: str
    fim: str
    responsavel: str

    def como_argumentos(self) -> dict[str, str]:
        """Os argumentos do `tools/call`, exatamente como o servidor espera."""
        return {
            "sala": self.sala,
            "inicio": self.inicio,
            "fim": self.fim,
            "responsavel": self.responsavel,
        }


class PedidoInvalido(ValueError):
    """O texto nao esta no formato fixo combinado."""


def interpretar_reserva(texto: str) -> Reserva:
    limpo = (texto or "").strip()
    if not limpo.lower().startswith("reservar"):
        raise PedidoInvalido(
            "pedido em formato invalido. Use: "
            "reservar sala=<id> inicio=<iso8601> fim=<iso8601> responsavel=<nome>"
        )

    encontrados = {m.group("chave"): m.group("valor").strip() for m in _CAMPO.finditer(limpo)}
    faltando = [c for c in CAMPOS_DA_RESERVA if not encontrados.get(c)]
    if faltando:
        raise PedidoInvalido(f"faltam campos no pedido: {', '.join(faltando)}")

    return Reserva(**{c: encontrados[c] for c in CAMPOS_DA_RESERVA})


def interpretar_escolha(texto: str) -> str:
    """Le `escolha=<valor>`. O valor pode ser um id de sala ou `recusar`."""
    encontrado = _ESCOLHA.match((texto or "").strip())
    if not encontrado:
        raise PedidoInvalido("responda com escolha=<id da sala> ou escolha=recusar")
    return encontrado.group("valor").strip()


def e_recusa(escolha: str) -> bool:
    return escolha.casefold() == RECUSAR
