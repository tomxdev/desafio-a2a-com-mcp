"""As regras da politica de uso, testadas sem subir o servidor."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import regras
from dominio import sala_por_id

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


def erro_de(sala: str, inicio: str, fim: str) -> str:
    with pytest.raises(ToolError) as capturado:
        regras.validar_pedido(sala, inicio, fim)
    return str(capturado.value)


# --- validacoes, com as mensagens exatas do enunciado ---------------------


def test_sala_inexistente_cita_o_id_informado():
    assert erro_de("sala-delorean", h("09:00"), h("10:00")) == "Sala inexistente: sala-delorean"


def test_inicio_antes_da_abertura():
    assert erro_de("sala-aquario", h("07:00"), h("08:00")) == regras.ERRO_JANELA


def test_fim_depois_do_fechamento():
    assert erro_de("sala-aquario", h("19:30"), h("20:30")) == regras.ERRO_JANELA


def test_duracao_acima_de_duas_horas():
    assert erro_de("sala-aquario", h("09:00"), h("12:00")) == regras.ERRO_DURACAO


def test_intervalo_invertido():
    assert erro_de("sala-aquario", h("10:00"), h("09:00")) == regras.ERRO_INTERVALO


def test_intervalo_vazio():
    assert erro_de("sala-aquario", h("09:00"), h("09:00")) == regras.ERRO_INTERVALO


def test_intervalo_invertido_vence_a_janela_e_a_duracao():
    # 10:00 -> 09:00 esta dentro da janela e "duraria" -1h: a ordem das
    # validacoes e o que faz o validador ver a mensagem certa.
    assert erro_de("sala-aquario", h("10:00"), h("09:00")) == regras.ERRO_INTERVALO


def test_sala_inexistente_vence_o_intervalo_invalido():
    assert erro_de("sala-delorean", h("10:00"), h("09:00")) == "Sala inexistente: sala-delorean"


@pytest.mark.parametrize("inicio,fim", [("08:00", "10:00"), ("18:00", "20:00"), ("09:00", "11:00")])
def test_limites_da_janela_sao_aceitos(inicio, fim):
    sala, comeco, termino = regras.validar_pedido("sala-aquario", h(inicio), h(fim))
    assert sala.id == "sala-aquario"
    assert termino > comeco


def test_duas_horas_exatas_sao_aceitas():
    regras.validar_pedido("sala-aquario", h("09:00"), h("11:00"))


def test_data_sem_offset_e_lida_como_sao_paulo():
    assert regras.instante("2026-11-03T09:00:00").hour == 9


def test_offset_diferente_e_convertido_para_sao_paulo():
    # 12:00Z e 09:00 em Sao Paulo, dentro da janela.
    regras.validar_pedido("sala-aquario", "2026-11-03T12:00:00+00:00", "2026-11-03T13:00:00+00:00")


def test_data_ilegivel():
    assert erro_de("sala-aquario", "ontem de manha", h("10:00")) == regras.ERRO_DATA


# --- sobreposicao ---------------------------------------------------------


@pytest.mark.parametrize(
    "inicio,fim,esperado",
    [
        ("14:00", "15:00", True),   # exatamente a reserva existente
        ("14:30", "15:30", True),   # comeca dentro
        ("13:30", "14:30", True),   # termina dentro
        ("13:00", "16:00", True),   # engloba a reserva
        ("13:00", "14:00", False),  # encosta no inicio, sem invadir
        ("15:00", "16:00", False),  # encosta no fim, sem invadir
    ],
)
def test_sobreposicao_na_sala_garagem(inicio, fim, esperado):
    # res-0001 ocupa a garagem das 14h as 15h.
    comeco, termino = regras.instante(h(inicio)), regras.instante(h(fim))
    assert bool(regras.conflitos("sala-garagem", comeco, termino)) is esperado


def test_conflito_traz_a_reserva_existente():
    comeco, termino = regras.instante(h("14:00")), regras.instante(h("15:00"))
    colisoes = regras.conflitos("sala-garagem", comeco, termino)
    assert [r.id for r in colisoes] == ["res-0001"]


def test_sala_livre_nao_tem_conflito():
    comeco, termino = regras.instante(h("09:00")), regras.instante(h("10:00"))
    assert regras.esta_livre("sala-garagem", comeco, termino)


# --- alternativas ---------------------------------------------------------


def test_alternativas_respeitam_capacidade_e_ordem():
    # Garagem (12) ocupada das 14h as 15h. Livres com capacidade >= 12:
    # fusca (12) e mirante (20), nessa ordem.
    comeco, termino = regras.instante(h("14:00")), regras.instante(h("15:00"))
    assert regras.alternativas(sala_por_id("sala-garagem"), comeco, termino) == [
        "sala-fusca",
        "sala-mirante",
    ]


def test_alternativas_excluem_salas_menores():
    comeco, termino = regras.instante(h("14:00")), regras.instante(h("15:00"))
    escolhidas = regras.alternativas(sala_por_id("sala-garagem"), comeco, termino)
    assert "sala-aquario" not in escolhidas and "sala-porao" not in escolhidas


def test_empate_de_capacidade_desempata_por_id():
    # Aquario (4) pede: todas as outras cabem. Fusca e garagem empatam em 12
    # e saem em ordem alfabetica; o corte e em tres, entao mirante fica fora.
    comeco, termino = regras.instante(h("09:00")), regras.instante(h("10:00"))
    assert regras.alternativas(sala_por_id("sala-aquario"), comeco, termino) == [
        "sala-porao",
        "sala-fusca",
        "sala-garagem",
    ]


def test_no_maximo_tres_alternativas():
    comeco, termino = regras.instante(h("09:00")), regras.instante(h("10:00"))
    assert len(regras.alternativas(sala_por_id("sala-aquario"), comeco, termino)) <= 3


def test_a_sala_pedida_nunca_e_oferecida_como_alternativa():
    # Mesmo livre, a propria sala pedida fica de fora: o que se oferece e
    # alternativa a ela.
    comeco, termino = regras.instante(h("09:00")), regras.instante(h("10:00"))
    assert "sala-aquario" not in regras.alternativas(sala_por_id("sala-aquario"), comeco, termino)


def test_sem_alternativa_quando_so_a_maior_serve():
    # Mirante (20) e a unica com capacidade >= 20, e ela mesma nao conta.
    comeco, termino = regras.instante(h("14:00")), regras.instante(h("15:00"))
    assert regras.alternativas(sala_por_id("sala-mirante"), comeco, termino) == []
