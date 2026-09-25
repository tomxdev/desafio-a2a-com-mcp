"""A politica de uso, como o resource a expoe."""

from __future__ import annotations

import dominio


def test_versao_vem_da_primeira_linha():
    # O artifact da Task carrega esse valor, e o validador o compara.
    assert dominio.VERSAO_DA_POLITICA == "2026-11-01"


def test_politica_preserva_a_linha_de_versao():
    assert dominio.POLITICA.splitlines()[0] == "versao: 2026-11-01"


def test_politica_sai_com_quebras_lf():
    # Mesmo com o arquivo em CRLF num checkout Windows, o resource precisa
    # sair como exemplos/wire/05-resources-read-politica.json mostra.
    assert "\r" not in dominio.POLITICA


def test_politica_traz_as_tres_regras():
    assert "08:00 e 20:00" in dominio.POLITICA
    assert "maxima de 2 horas" in dominio.POLITICA
    assert "reservas sobrepostas" in dominio.POLITICA
