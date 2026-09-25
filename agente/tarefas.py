"""A Task do A2A: identidade, estado e produto.

Enquanto o MCP resolve a ausencia de sessao com um token que viaja, o A2A
resolve com a Task, que fica. Estado terminal e definitivo: uma Task
COMPLETED, CANCELED ou FAILED nao volta a WORKING.

Tudo em memoria, por processo. O enunciado nao pede persistencia.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

SUBMITTED = "TASK_STATE_SUBMITTED"
WORKING = "TASK_STATE_WORKING"
INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
COMPLETED = "TASK_STATE_COMPLETED"
CANCELED = "TASK_STATE_CANCELED"
FAILED = "TASK_STATE_FAILED"

TERMINAIS = frozenset({COMPLETED, CANCELED, FAILED})


def _id(prefixo: str) -> str:
    return f"{prefixo}-{secrets.token_hex(6)}"


def mensagem_do_agente(texto: str, task_id: str, context_id: str) -> dict[str, Any]:
    return {
        "messageId": _id("msg"),
        "role": "ROLE_AGENT",
        "parts": [{"text": texto}],
        "taskId": task_id,
        "contextId": context_id,
    }


@dataclass
class Task:
    """Uma Task A2A. `pausa` e estado interno e nunca sai numa resposta."""

    id: str = field(default_factory=lambda: _id("task"))
    context_id: str = field(default_factory=lambda: _id("ctx"))
    estado: str = SUBMITTED
    mensagem_de_status: dict[str, Any] | None = None
    historico: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    # Estado interno da ponte: o requestState opaco e o que for preciso para
    # repetir o tools/call. Nunca serializado.
    pausa: Any = None
    argumentos: dict[str, Any] | None = None

    @property
    def terminada(self) -> bool:
        return self.estado in TERMINAIS

    def registrar(self, mensagem: dict[str, Any]) -> None:
        self.historico.append(mensagem)

    def dizer(self, texto: str) -> dict[str, Any]:
        """Poe uma fala do agente no status e no historico."""
        mensagem = mensagem_do_agente(texto, self.id, self.context_id)
        self.mensagem_de_status = mensagem
        self.registrar(mensagem)
        return mensagem

    def mover_para(self, estado: str, texto: str | None = None) -> None:
        self.estado = estado
        if texto is not None:
            self.dizer(texto)

    def anexar(self, nome: str, conteudo: dict[str, Any]) -> None:
        self.artifacts.append(
            {
                "artifactId": _id("art"),
                "name": nome,
                "parts": [{"text": json.dumps(conteudo, ensure_ascii=False)}],
            }
        )

    def como_json(self) -> dict[str, Any]:
        """A forma que vai na resposta. Note que `pausa` nao entra aqui."""
        status: dict[str, Any] = {"state": self.estado}
        if self.mensagem_de_status is not None:
            status["message"] = self.mensagem_de_status
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": status,
            "history": self.historico,
            "artifacts": self.artifacts,
        }


class Tarefas:
    """Guarda as Tasks do processo. O estado pausado e por Task."""

    def __init__(self) -> None:
        self._por_id: dict[str, Task] = {}

    def abrir(self) -> Task:
        nova = Task()
        self._por_id[nova.id] = nova
        return nova

    def buscar(self, identificador: str) -> Task | None:
        return self._por_id.get(identificador)
