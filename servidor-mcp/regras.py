"""As regras de `dados/politica-de-uso.md`, em um lugar so.

O servidor MCP e o unico dono do dominio: conflito, politica e alternativas
sao decisao daqui, nunca do agente. As mensagens de erro sao as do enunciado,
ao pe da letra, e viajam em `ToolError` porque so ela preserva o texto ate o
cliente (uma excecao comum vira um generico "Error executing tool <nome>").

Nenhuma regra depende da data de hoje: reservar no passado e permitido.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from mcp.server.mcpserver.exceptions import ToolError

from dominio import RESERVAS, SALAS, Reserva, SalaOut, sala_por_id

# Fuso de Sao Paulo, em que a janela de uso e declarada.
FUSO = timezone(timedelta(hours=-3))
ABERTURA = 8
FECHAMENTO = 20
DURACAO_MAXIMA = timedelta(hours=2)
MAXIMO_DE_ALTERNATIVAS = 3

ERRO_JANELA = "Fora da janela de uso: a politica permite reservas entre 08:00 e 20:00"
ERRO_DURACAO = "Duracao acima do limite: a politica permite no maximo 2 horas"
ERRO_INTERVALO = "Intervalo invalido: fim deve ser posterior a inicio"
ERRO_SEM_ALTERNATIVAS = "Sem alternativas disponiveis no intervalo"
ERRO_DATA = "Data invalida: use ISO 8601 com offset, por exemplo 2026-11-03T14:00:00-03:00"


def erro_de_sala(identificador: str) -> str:
    return f"Sala inexistente: {identificador}"


def instante(texto: str) -> datetime:
    """Converte um ISO 8601 com offset para o fuso da politica."""
    try:
        momento = datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ToolError(ERRO_DATA) from None
    if momento.tzinfo is None:
        # Sem offset explicito, o horario e lido como de Sao Paulo.
        momento = momento.replace(tzinfo=FUSO)
    return momento.astimezone(FUSO)


def _dentro_da_janela(momento: datetime) -> bool:
    hora = momento.time()
    return time(ABERTURA) <= hora <= time(FECHAMENTO)


def validar_pedido(sala: str, inicio: str, fim: str) -> tuple[SalaOut, datetime, datetime]:
    """Aplica sala, intervalo, janela e duracao, nessa ordem.

    A ordem importa: um intervalo invertido dentro da janela precisa acusar
    intervalo invalido, nao duracao.
    """
    encontrada = sala_por_id(sala)
    if encontrada is None:
        raise ToolError(erro_de_sala(sala))

    comeco, termino = instante(inicio), instante(fim)
    if termino <= comeco:
        raise ToolError(ERRO_INTERVALO)
    if not _dentro_da_janela(comeco) or not _dentro_da_janela(termino):
        raise ToolError(ERRO_JANELA)
    if termino - comeco > DURACAO_MAXIMA:
        raise ToolError(ERRO_DURACAO)

    return encontrada, comeco, termino


def _sobrepoe(reserva: Reserva, comeco: datetime, termino: datetime) -> bool:
    return comeco < instante(reserva.fim) and instante(reserva.inicio) < termino


def conflitos(sala: str, comeco: datetime, termino: datetime) -> list[Reserva]:
    """As reservas da sala que colidem com o intervalo."""
    return [r for r in RESERVAS if r.sala == sala and _sobrepoe(r, comeco, termino)]


def esta_livre(sala: str, comeco: datetime, termino: datetime) -> bool:
    return not conflitos(sala, comeco, termino)


def alternativas(pedida: SalaOut, comeco: datetime, termino: datetime) -> list[str]:
    """Salas livres no intervalo, com capacidade igual ou maior que a pedida.

    No maximo tres, por capacidade crescente e, em empate, por id alfabetico.
    A sala pedida fica de fora por definicao: o que se oferece e alternativa
    a ela. Na pratica ela ja cairia no filtro de livres, porque so se procura
    alternativa quando ela esta ocupada, mas depender disso seria fragil.
    """
    livres = [
        s for s in SALAS
        if s.id != pedida.id
        and s.capacidade >= pedida.capacidade
        and esta_livre(s.id, comeco, termino)
    ]
    livres.sort(key=lambda s: (s.capacidade, s.id))
    return [s.id for s in livres[:MAXIMO_DE_ALTERNATIVAS]]
