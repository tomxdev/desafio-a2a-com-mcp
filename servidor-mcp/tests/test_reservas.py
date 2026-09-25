"""Criacao de reservas em memoria."""

from __future__ import annotations

import pytest

import dominio
import regras

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


@pytest.fixture(autouse=True)
def reservas_isoladas():
    """RESERVAS e estado de modulo: cada teste comeca do arquivo original."""
    original = list(dominio.RESERVAS)
    yield
    dominio.RESERVAS[:] = original


def test_numeracao_continua_a_do_arquivo():
    # dados/reservas.json termina em res-0002.
    assert dominio.proximo_id_de_reserva() == "res-0003"


def test_numeracao_avanca_a_cada_reserva():
    assert dominio.criar_reserva("sala-aquario", h("09:00"), h("10:00"), "Doc").id == "res-0003"
    assert dominio.criar_reserva("sala-porao", h("09:00"), h("10:00"), "Marty").id == "res-0004"


def test_numeracao_usa_o_maior_id_e_nao_a_contagem():
    dominio.RESERVAS[:] = [dominio.Reserva(id="res-0042", sala="sala-porao", inicio=h("09:00"), fim=h("10:00"), responsavel="Biff")]
    assert dominio.proximo_id_de_reserva() == "res-0043"


def test_a_reserva_criada_fica_visivel_para_a_consulta_seguinte():
    comeco, termino = regras.instante(h("09:00")), regras.instante(h("10:00"))
    assert regras.esta_livre("sala-aquario", comeco, termino)

    dominio.criar_reserva("sala-aquario", h("09:00"), h("10:00"), "Doc")

    assert not regras.esta_livre("sala-aquario", comeco, termino)
    assert [r.id for r in regras.conflitos("sala-aquario", comeco, termino)] == ["res-0003"]


def test_horarios_sao_guardados_como_vieram():
    # O cliente compara o que recebe de volta com o que enviou.
    nova = dominio.criar_reserva("sala-aquario", h("09:00"), h("10:00"), "Doc")
    assert nova.inicio == h("09:00") and nova.fim == h("10:00")


def test_a_reserva_criada_muda_as_alternativas_seguintes():
    comeco, termino = regras.instante(h("14:00")), regras.instante(h("15:00"))
    pedida = dominio.sala_por_id("sala-garagem")
    assert regras.alternativas(pedida, comeco, termino) == ["sala-fusca", "sala-mirante"]

    dominio.criar_reserva("sala-fusca", h("14:00"), h("15:00"), "Biff")

    assert regras.alternativas(pedida, comeco, termino) == ["sala-mirante"]
