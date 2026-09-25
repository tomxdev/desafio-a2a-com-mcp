"""Leitura do pedido em formato fixo."""

from __future__ import annotations

import pytest

from pedido import PedidoInvalido, interpretar_reserva

PEDIDO = (
    "reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00 "
    "fim=2026-11-03T15:00:00-03:00 responsavel=Marty"
)


def test_le_os_quatro_campos():
    r = interpretar_reserva(PEDIDO)
    assert r.sala == "sala-garagem"
    assert r.inicio == "2026-11-03T14:00:00-03:00"
    assert r.fim == "2026-11-03T15:00:00-03:00"
    assert r.responsavel == "Marty"


def test_vira_argumentos_do_tools_call():
    assert interpretar_reserva(PEDIDO).como_argumentos() == {
        "sala": "sala-garagem",
        "inicio": "2026-11-03T14:00:00-03:00",
        "fim": "2026-11-03T15:00:00-03:00",
        "responsavel": "Marty",
    }


def test_responsavel_com_espacos():
    r = interpretar_reserva(PEDIDO.replace("responsavel=Marty", "responsavel=Marty McFly"))
    assert r.responsavel == "Marty McFly"


def test_espacos_em_volta_nao_atrapalham():
    assert interpretar_reserva(f"   {PEDIDO}  ").sala == "sala-garagem"


def test_e_deterministico():
    assert interpretar_reserva(PEDIDO) == interpretar_reserva(PEDIDO)


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "   ",
        "oi, tudo bem?",
        "quero uma sala grande na quinta de tarde",
        "escolha=sala-fusca",
    ],
)
def test_recusa_o_que_nao_e_pedido_de_reserva(texto):
    with pytest.raises(PedidoInvalido):
        interpretar_reserva(texto)


def test_recusa_pedido_incompleto():
    with pytest.raises(PedidoInvalido) as capturado:
        interpretar_reserva("reservar sala=sala-garagem inicio=2026-11-03T14:00:00-03:00")
    assert "fim" in str(capturado.value) and "responsavel" in str(capturado.value)
