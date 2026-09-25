"""A costura entre o MRTR do MCP e a Task do A2A."""

from __future__ import annotations

import asyncio
import json

import pytest

import ponte
import tarefas as t
from cliente_mcp import Conclusao, Pausa

PEDIDO = (
    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
    "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
)


def mensagem(texto: str, task_id: str | None = None) -> dict:
    corpo = {"messageId": "msg-1", "role": "ROLE_USER", "parts": [{"text": texto}]}
    if task_id:
        corpo["taskId"] = task_id
    return corpo


def pausa_de(alternativas: list[str]) -> Pausa:
    return Pausa(
        chave="elicitacao:escolha_de_sala",
        campo="sala",
        alternativas=alternativas,
        request_state="v1.token-opaco-nao-interpretar",
    )


def reserva_feita(sala: str, identificador: str = "res-0003") -> Conclusao:
    return Conclusao(
        dados={
            "reserva": identificador,
            "reservado": True,
            "sala": sala,
            "inicio": "2026-11-03T14:00:00-03:00",
            "fim": "2026-11-03T15:00:00-03:00",
            "responsavel": "Marty",
            "politica": "2026-11-01",
            "motivo": None,
        },
        texto="",
        erro=False,
    )


class HostFalso:
    """Registra o que a ponte pediu ao servidor MCP."""

    def __init__(self, primeira, seguinte=None):
        self.primeira = primeira
        self.seguinte = seguinte
        self.chamadas: list[tuple] = []

    async def reservar(self, argumentos, traceparent=None):
        self.chamadas.append(("reservar", argumentos, traceparent))
        return self.primeira

    async def retomar(self, argumentos, pausa, resposta, traceparent=None):
        self.chamadas.append(("retomar", argumentos, pausa, resposta, traceparent))
        return self.seguinte

    async def versao_da_politica(self, traceparent=None):
        return "2026-11-01"


def abrir(host) -> t.Task:
    return asyncio.run(ponte.abrir(host, t.Tarefas(), mensagem(PEDIDO), None))


def continuar(host, tarefa, texto) -> None:
    asyncio.run(ponte.continuar(host, tarefa, mensagem(texto, tarefa.id), None))


# --- a linha de alternativas ---------------------------------------------


def test_a_linha_e_exatamente_a_do_enunciado():
    # O avaliador compara duas pausas byte a byte.
    assert ponte.linha_de_alternativas(["sala-fusca", "sala-mirante"]) == (
        "alternativas: sala-fusca, sala-mirante"
    )


def test_a_linha_nao_ganha_prefixo_nem_saudacao():
    linha = ponte.linha_de_alternativas(["sala-mirante"])
    assert linha == "alternativas: sala-mirante"
    assert linha.startswith("alternativas:")


# --- pausa ----------------------------------------------------------------


def test_input_required_vira_task_pausada():
    tarefa = abrir(HostFalso(pausa_de(["sala-fusca", "sala-mirante"])))
    assert tarefa.estado == t.INPUT_REQUIRED
    assert tarefa.mensagem_de_status["parts"][0]["text"] == "alternativas: sala-fusca, sala-mirante"


def test_a_pausa_guarda_o_estado_ligado_aquela_task():
    tarefa = abrir(HostFalso(pausa_de(["sala-fusca"])))
    assert tarefa.pausa.request_state == "v1.token-opaco-nao-interpretar"
    assert tarefa.argumentos["sala"] == "sala-garagem"


def test_o_request_state_nao_sai_na_resposta():
    tarefa = abrir(HostFalso(pausa_de(["sala-fusca"])))
    assert "v1.token-opaco-nao-interpretar" not in json.dumps(tarefa.como_json())


# --- retomada -------------------------------------------------------------


def test_a_escolha_valida_repete_o_tools_call_com_a_mesma_chave_e_o_estado_ecoado():
    host = HostFalso(pausa_de(["sala-fusca", "sala-mirante"]), reserva_feita("sala-fusca"))
    tarefa = abrir(host)
    continuar(host, tarefa, "escolha=sala-fusca")

    _, argumentos, pausa, resposta, _ = host.chamadas[-1]
    assert argumentos == tarefa.argumentos  # o mesmo pedido original
    assert pausa.request_state == "v1.token-opaco-nao-interpretar"  # ecoado sem tocar
    assert resposta == {"action": "accept", "content": {"sala": "sala-fusca"}}


def test_a_escolha_valida_conclui_com_o_artifact():
    host = HostFalso(pausa_de(["sala-fusca"]), reserva_feita("sala-fusca"))
    tarefa = abrir(host)
    continuar(host, tarefa, "escolha=sala-fusca")

    assert tarefa.estado == t.COMPLETED
    artifact = tarefa.artifacts[0]
    assert artifact["name"] == "reserva"
    conteudo = json.loads(artifact["parts"][0]["text"])
    assert conteudo["sala"] == "sala-fusca"
    assert conteudo["politica"] == "2026-11-01"


def test_recusar_vira_decline_e_termina_em_canceled():
    recusa = Conclusao(dados={"reservado": False, "motivo": "recusado"}, texto="", erro=False)
    host = HostFalso(pausa_de(["sala-fusca"]), recusa)
    tarefa = abrir(host)
    continuar(host, tarefa, "escolha=recusar")

    assert host.chamadas[-1][3] == {"action": "decline"}
    assert tarefa.estado == t.CANCELED


@pytest.mark.parametrize("texto", ["escolha=sala-aquario", "escolha=sala-inventada"])
def test_escolha_fora_do_enum_mantem_a_task_pausada(texto):
    host = HostFalso(pausa_de(["sala-fusca", "sala-mirante"]))
    tarefa = abrir(host)
    continuar(host, tarefa, texto)

    assert tarefa.estado == t.INPUT_REQUIRED
    assert tarefa.mensagem_de_status["parts"][0]["text"] == "alternativas: sala-fusca, sala-mirante"
    # Sem round-trip: o requestState nao foi gasto.
    assert [c[0] for c in host.chamadas] == ["reservar"]


def test_texto_incompreensivel_tambem_mantem_a_pausa():
    host = HostFalso(pausa_de(["sala-fusca", "sala-mirante"]))
    tarefa = abrir(host)
    continuar(host, tarefa, "sei la, qualquer uma")

    assert tarefa.estado == t.INPUT_REQUIRED
    assert tarefa.mensagem_de_status["parts"][0]["text"] == "alternativas: sala-fusca, sala-mirante"


def test_a_pausa_repetida_e_identica_byte_a_byte():
    primeira = abrir(HostFalso(pausa_de(["sala-fusca", "sala-mirante"])))
    segunda = abrir(HostFalso(pausa_de(["sala-fusca", "sala-mirante"])))
    assert (
        primeira.mensagem_de_status["parts"][0]["text"]
        == segunda.mensagem_de_status["parts"][0]["text"]
    )


# --- isolamento -----------------------------------------------------------


def test_duas_tasks_pausadas_nao_trocam_de_request_state():
    a = abrir(HostFalso(Pausa("k", "sala", ["sala-mirante"], "v1.token-A")))
    b = abrir(HostFalso(Pausa("k", "sala", ["sala-mirante"], "v1.token-B")))

    assert a.id != b.id
    assert a.pausa.request_state == "v1.token-A"
    assert b.pausa.request_state == "v1.token-B"


# --- erro de execucao -----------------------------------------------------


def test_erro_da_tool_termina_em_failed_com_a_mensagem_exata():
    erro = Conclusao(
        dados={},
        texto="Error executing tool reservar_sala: Sala inexistente: sala-delorean",
        erro=True,
    )
    tarefa = abrir(HostFalso(erro))
    assert tarefa.estado == t.FAILED
    assert "Sala inexistente: sala-delorean" in tarefa.mensagem_de_status["parts"][0]["text"]


def test_pedido_em_formato_invalido_termina_em_failed_sem_chamar_o_mcp():
    host = HostFalso(None)
    tarefa = asyncio.run(ponte.abrir(host, t.Tarefas(), mensagem("me arruma uma sala ai"), None))
    assert tarefa.estado == t.FAILED
    assert host.chamadas == []
