"""Dados do dominio das salas, carregados uma vez na subida.

`dados/` e somente leitura: nada aqui escreve de volta no disco. As reservas
criadas durante a execucao ficam nesta lista em memoria e, como o enunciado
manda, nao sobrevivem a um restart do processo.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"


class SalaOut(BaseModel):
    """Uma sala, na forma em que o structuredContent a devolve."""

    id: str
    nome: str
    capacidade: int
    recursos: list[str]


class ListaDeSalas(BaseModel):
    """Saida de `listar_salas`."""

    salas: list[SalaOut]


class Reserva(BaseModel):
    """Uma reserva, no formato de `dados/reservas.json`."""

    id: str
    sala: str
    inicio: str
    fim: str
    responsavel: str


def _ler_json(nome: str) -> list[dict]:
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def _ler_versao_da_politica() -> str:
    """A versao declarada na primeira linha de `dados/politica-de-uso.md`."""
    primeira = (DADOS / "politica-de-uso.md").read_text(encoding="utf-8").splitlines()[0]
    return primeira.split(":", 1)[1].strip()


SALAS: list[SalaOut] = [SalaOut(**s) for s in _ler_json("salas.json")]
RESERVAS: list[Reserva] = [Reserva(**r) for r in _ler_json("reservas.json")]
VERSAO_DA_POLITICA: str = _ler_versao_da_politica()


def sala_por_id(identificador: str) -> SalaOut | None:
    return next((s for s in SALAS if s.id == identificador), None)
