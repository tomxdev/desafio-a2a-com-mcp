"""A maquina de estados da Task."""

from __future__ import annotations

import json

import tarefas as t


def test_task_nasce_com_identidade_propria():
    a, b = t.Tarefas().abrir(), t.Tarefas().abrir()
    assert a.id != b.id and a.context_id != b.context_id
    assert a.estado == t.SUBMITTED


def test_estado_terminal_e_definitivo():
    tarefa = t.Tarefas().abrir()
    for terminal in (t.COMPLETED, t.CANCELED, t.FAILED):
        tarefa.estado = terminal
        assert tarefa.terminada
    tarefa.estado = t.WORKING
    assert not tarefa.terminada


def test_input_required_nao_e_terminal():
    # A Task pausada continua aceitando continuacao.
    tarefa = t.Tarefas().abrir()
    tarefa.estado = t.INPUT_REQUIRED
    assert not tarefa.terminada


def test_dizer_poe_a_fala_no_status_e_no_historico():
    tarefa = t.Tarefas().abrir()
    tarefa.dizer("alternativas: sala-fusca")
    assert tarefa.mensagem_de_status["parts"][0]["text"] == "alternativas: sala-fusca"
    assert tarefa.historico[-1] is tarefa.mensagem_de_status
    assert tarefa.mensagem_de_status["role"] == "ROLE_AGENT"
    assert tarefa.mensagem_de_status["taskId"] == tarefa.id


def test_artifact_serializa_o_conteudo_em_texto():
    tarefa = t.Tarefas().abrir()
    tarefa.anexar("reserva", {"reserva": "res-0003", "politica": "2026-11-01"})
    artifact = tarefa.artifacts[0]
    assert artifact["name"] == "reserva"
    assert json.loads(artifact["parts"][0]["text"])["politica"] == "2026-11-01"


def test_o_json_da_task_nao_carrega_o_estado_interno():
    # O requestState nunca pode aparecer numa resposta A2A.
    tarefa = t.Tarefas().abrir()
    tarefa.pausa = "v1.segredo-opaco"
    tarefa.argumentos = {"sala": "sala-garagem"}
    serializado = json.dumps(tarefa.como_json())
    assert "v1.segredo-opaco" not in serializado
    assert "pausa" not in serializado


def test_a_task_e_encontrada_pelo_id():
    registro = t.Tarefas()
    tarefa = registro.abrir()
    assert registro.buscar(tarefa.id) is tarefa
    assert registro.buscar("task-inexistente") is None
