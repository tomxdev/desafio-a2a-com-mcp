"""O resolver do MRTR: quando pergunta, o que pergunta e quando nao pergunta."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver import Elicit
from mcp.server.mcpserver.exceptions import ToolError

import dominio
import elicitacao
import regras

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


def resolver(sala: str, inicio: str, fim: str):
    return asyncio.run(elicitacao.escolha_de_sala(sala, inicio, fim))


def enum_de(elicit: Elicit) -> list[str]:
    campo = elicit.schema.model_json_schema()["properties"]["sala"]
    return campo.get("enum") or [campo["const"]]


@pytest.fixture(autouse=True)
def reservas_isoladas():
    original = list(dominio.RESERVAS)
    yield
    dominio.RESERVAS[:] = original


def test_sala_livre_nao_pergunta_nada():
    # Sem pergunta nao ha round-trip: a chamada ja conclui.
    resultado = resolver("sala-aquario", h("09:00"), h("10:00"))
    assert not isinstance(resultado, Elicit)
    assert resultado.sala == "sala-aquario"


def test_conflito_pergunta_com_as_alternativas_na_ordem():
    # res-0001 ocupa a garagem das 14h as 15h.
    resultado = resolver("sala-garagem", h("14:00"), h("15:00"))
    assert isinstance(resultado, Elicit)
    assert enum_de(resultado) == ["sala-fusca", "sala-mirante"]


def test_a_pergunta_usa_a_mensagem_do_enunciado():
    resultado = resolver("sala-garagem", h("14:00"), h("15:00"))
    assert resultado.message == "A sala pedida esta ocupada nesse intervalo. Escolha uma alternativa."


def test_o_schema_da_pergunta_e_plano():
    esquema = resolver("sala-garagem", h("14:00"), h("15:00")).schema.model_json_schema()
    assert esquema["type"] == "object"
    assert list(esquema["properties"]) == ["sala"]
    assert esquema["required"] == ["sala"]
    assert esquema["properties"]["sala"]["type"] == "string"


def test_alternativa_unica_vira_const_ou_enum_de_um():
    # Fusca ocupada as 16h; garagem e a unica livre com capacidade >= 12.
    dominio.criar_reserva("sala-mirante", h("16:00"), h("17:00"), "Ocupante")
    campo = resolver("sala-fusca", h("16:00"), h("17:00")).schema.model_json_schema()["properties"]["sala"]
    assert campo.get("enum") == ["sala-garagem"] or campo.get("const") == "sala-garagem"


def test_sem_alternativa_nao_pergunta_e_devolve_a_mensagem_do_enunciado():
    dominio.criar_reserva("sala-mirante", h("11:00"), h("12:00"), "Ocupante")
    with pytest.raises(ToolError) as capturado:
        resolver("sala-mirante", h("11:00"), h("12:00"))
    assert str(capturado.value) == regras.ERRO_SEM_ALTERNATIVAS


def test_o_resolver_tambem_valida_o_pedido():
    # Ele roda antes do corpo da tool, entao precisa barrar sala inexistente.
    with pytest.raises(ToolError) as capturado:
        resolver("sala-delorean", h("09:00"), h("10:00"))
    assert str(capturado.value) == "Sala inexistente: sala-delorean"


def test_o_resolver_nao_reserva_nada():
    antes = len(dominio.RESERVAS)
    resolver("sala-garagem", h("14:00"), h("15:00"))
    assert len(dominio.RESERVAS) == antes
