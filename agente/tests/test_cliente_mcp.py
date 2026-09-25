"""Traducao de protocolo no host MCP do agente."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.types import ElicitRequest, ElicitRequestFormParams, InputRequiredResult

from cliente_mcp import (
    HostMCP,
    Pausa,
    resposta_de_aceite,
    resposta_de_recusa,
    traceparent_derivado,
)

TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
ENTRADA = f"00-{TRACE}-00f067aa0ba902b7-01"


# --- traceparent ----------------------------------------------------------


def test_mantem_o_trace_id_de_quem_chamou():
    assert traceparent_derivado(ENTRADA).split("-")[1] == TRACE


def test_gera_span_id_novo():
    saida = traceparent_derivado(ENTRADA)
    assert saida.split("-")[2] != "00f067aa0ba902b7"
    assert len(saida.split("-")[2]) == 16


def test_duas_derivacoes_compartilham_o_trace_e_diferem_no_span():
    a, b = traceparent_derivado(ENTRADA), traceparent_derivado(ENTRADA)
    assert a.split("-")[1] == b.split("-")[1]
    assert a.split("-")[2] != b.split("-")[2]


@pytest.mark.parametrize("entrada", [None, "", "lixo", "00-curto-demais-01"])
def test_sem_traceparent_valido_abre_um_trace_proprio(entrada):
    partes = traceparent_derivado(entrada).split("-")
    assert len(partes[1]) == 32 and len(partes[2]) == 16


# --- traducao do input_required -------------------------------------------


def _pausa_com(propriedades: dict) -> InputRequiredResult:
    return InputRequiredResult(
        input_requests={
            "servidor:resolver": ElicitRequest(
                params=ElicitRequestFormParams(
                    message="Escolha uma alternativa.",
                    requested_schema={
                        "type": "object",
                        "properties": propriedades,
                        "required": list(propriedades),
                    },
                )
            )
        },
        request_state="v1.opaco",
    )


def test_pausa_extrai_chave_alternativas_e_estado():
    pausa = HostMCP._traduzir(_pausa_com({"sala": {"type": "string", "enum": ["a", "b"]}}))
    assert isinstance(pausa, Pausa)
    assert pausa.chave == "servidor:resolver"
    assert pausa.campo == "sala"
    assert pausa.alternativas == ["a", "b"]
    assert pausa.request_state == "v1.opaco"


def test_alternativa_unica_em_const_tambem_e_lida():
    pausa = HostMCP._traduzir(_pausa_com({"sala": {"type": "string", "const": "a"}}))
    assert pausa.alternativas == ["a"]


def test_o_nome_do_campo_vem_do_schema_e_nao_e_fixo():
    # O agente traduz protocolo; ele nao sabe que o dominio se chama "sala".
    pausa = HostMCP._traduzir(_pausa_com({"recurso": {"type": "string", "enum": ["x"]}}))
    assert pausa.campo == "recurso"


def test_conclusao_carrega_dados_texto_e_erro():
    resultado = SimpleNamespace(
        structured_content={"reserva": "res-0003"},
        content=[SimpleNamespace(text='{"reserva": "res-0003"}')],
        is_error=False,
    )
    conclusao = HostMCP._traduzir(resultado)
    assert conclusao.dados == {"reserva": "res-0003"}
    assert conclusao.erro is False


def test_erro_de_execucao_chega_marcado():
    resultado = SimpleNamespace(
        structured_content=None,
        content=[SimpleNamespace(text="Sala inexistente: sala-delorean")],
        is_error=True,
    )
    conclusao = HostMCP._traduzir(resultado)
    assert conclusao.erro is True
    assert "Sala inexistente" in conclusao.texto


# --- respostas da elicitation ---------------------------------------------


def test_aceite_usa_o_campo_da_pausa():
    pausa = Pausa(chave="k", campo="sala", alternativas=["a"], request_state="v1.x")
    assert resposta_de_aceite(pausa, "a") == {"action": "accept", "content": {"sala": "a"}}


def test_recusa_nao_leva_conteudo():
    assert resposta_de_recusa() == {"action": "decline"}
