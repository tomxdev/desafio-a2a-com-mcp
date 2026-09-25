"""A chave que protege o requestState."""

from __future__ import annotations

import pytest

import seguranca
from seguranca import SegredoInvalido, chave_do_request_state

HEX_DE_32_BYTES = "ab" * 32


def test_aceita_hexadecimal_de_32_bytes():
    assert len(chave_do_request_state({"REQUEST_STATE_SECRET": HEX_DE_32_BYTES})) == 32


def test_aceita_texto_cru_longo_o_bastante():
    bruto = "x" * 40
    assert chave_do_request_state({"REQUEST_STATE_SECRET": bruto}) == bruto.encode()


def test_recusa_ausente():
    with pytest.raises(SegredoInvalido) as capturado:
        chave_do_request_state({})
    assert "nao definido" in str(capturado.value)
    assert "token_hex(32)" in str(capturado.value)


def test_recusa_vazio_ou_so_espacos():
    with pytest.raises(SegredoInvalido):
        chave_do_request_state({"REQUEST_STATE_SECRET": "   "})


def test_recusa_chave_curta():
    with pytest.raises(SegredoInvalido) as capturado:
        chave_do_request_state({"REQUEST_STATE_SECRET": "ab" * 16})  # 16 bytes
    assert "16 bytes" in str(capturado.value)


def test_o_minimo_e_o_do_enunciado():
    assert seguranca.MINIMO_DE_BYTES == 32


def test_nao_ha_chave_embutida_no_modulo():
    # O repositorio e publico: a chave so pode vir do ambiente.
    import inspect

    fonte = inspect.getsource(seguranca)
    assert "os.environ" in fonte or "ambiente" in fonte
    assert 'REQUEST_STATE_SECRET = "' not in fonte
