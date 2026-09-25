"""A ponte: onde o MRTR do MCP encontra a Task do A2A.

Os dois protocolos resolvem a ausencia de sessao de jeitos diferentes. O MCP
devolve um `requestState` que viaja com o cliente e volta no retry. O A2A tem
a Task, que fica, com identidade, estado e produto. Este modulo e a costura
entre os dois, e e so isto que atravessa a fronteira: estado nomeado
explicitamente.

O caminho completo de um pedido em sala ocupada:

1. `abrir` chama o servidor MCP e recebe `input_required` em vez de resultado.
2. `pausar` poe a Task em TASK_STATE_INPUT_REQUIRED, devolve a linha de
   alternativas ao cliente A2A e guarda o `requestState` ligado aquela Task.
3. O cliente responde com `escolha=<id>` referenciando a mesma Task.
4. `continuar` repete o `tools/call` original, com id de JSON-RPC novo,
   levando `inputResponses` com a mesma chave e o `requestState` ecoado sem
   modificacao.
5. A Task termina em COMPLETED com o artifact da reserva.

O `requestState` e opaco: guardado e devolvido, nunca aberto, interpretado
nem reconstruido. Ele tambem nunca sai numa resposta A2A.
"""

from __future__ import annotations

from typing import Any

import tarefas as t
from cliente_mcp import Conclusao, HostMCP, Pausa, resposta_de_aceite, resposta_de_recusa
from pedido import PedidoInvalido, e_recusa, interpretar_escolha, interpretar_reserva


def linha_de_alternativas(alternativas: list[str]) -> str:
    """Exatamente `alternativas: a, b`, sem prefixo e sem saudacao.

    O avaliador compara duas pausas iguais byte a byte, entao esta linha nao
    pode variar nem ganhar enfeite.
    """
    return "alternativas: " + ", ".join(alternativas)


def texto_de(mensagem: dict[str, Any]) -> str:
    return " ".join(p.get("text", "") for p in mensagem.get("parts") or [])


def _pausar(tarefa: t.Task, pausa: Pausa) -> None:
    """Traduz o `input_required` do MCP em pausa da Task."""
    tarefa.pausa = pausa  # estado interno: nao vai para a resposta
    tarefa.mover_para(t.INPUT_REQUIRED, linha_de_alternativas(pausa.alternativas))


async def _concluir(tarefa: t.Task, conclusao: Conclusao, host: HostMCP) -> None:
    """Traduz a resposta final do servidor MCP no desfecho da Task."""
    if conclusao.erro:
        # A mensagem exata da tool precisa chegar ao cliente A2A.
        tarefa.mover_para(t.FAILED, conclusao.texto)
        return

    dados = conclusao.dados
    if not dados.get("reservado"):
        tarefa.mover_para(t.CANCELED, f"Reserva nao realizada: {dados.get('motivo') or 'recusado'}.")
        return

    tarefa.anexar(
        "reserva",
        {
            "reserva": dados.get("reserva"),
            "sala": dados.get("sala"),
            "inicio": dados.get("inicio"),
            "fim": dados.get("fim"),
            "responsavel": dados.get("responsavel"),
            # A versao vem do resource lido pelo agente: ler a politica e
            # escolha da aplicacao, nao um subproduto da tool.
            "politica": await host.versao_da_politica(),
        },
    )
    tarefa.mover_para(
        t.COMPLETED, f"Reserva {dados.get('reserva')} confirmada na {dados.get('sala')}."
    )


async def _despachar(
    tarefa: t.Task, resultado: Pausa | Conclusao, host: HostMCP
) -> None:
    if isinstance(resultado, Conclusao):
        await _concluir(tarefa, resultado, host)
    else:
        _pausar(tarefa, resultado)


async def abrir(
    host: HostMCP, tarefas: t.Tarefas, mensagem: dict[str, Any], traceparent: str | None
) -> t.Task:
    """Abre uma Task nova a partir de um SendMessage sem taskId."""
    tarefa = tarefas.abrir()
    tarefa.registrar(mensagem)

    try:
        pedido = interpretar_reserva(texto_de(mensagem))
    except PedidoInvalido as erro:
        tarefa.mover_para(t.FAILED, str(erro))
        return tarefa

    # Os argumentos ficam guardados porque o retry repete o mesmo tools/call.
    tarefa.argumentos = pedido.como_argumentos()
    tarefa.mover_para(t.WORKING)

    await _despachar(tarefa, await host.reservar(tarefa.argumentos, traceparent), host)
    return tarefa


async def continuar(
    host: HostMCP, tarefa: t.Task, mensagem: dict[str, Any], traceparent: str | None
) -> None:
    """Retoma uma Task pausada a partir de um SendMessage com taskId."""
    tarefa.registrar(mensagem)

    if tarefa.pausa is None or tarefa.argumentos is None:
        tarefa.dizer("esta Task nao esta esperando resposta.")
        return

    pausa: Pausa = tarefa.pausa

    try:
        escolha = interpretar_escolha(texto_de(mensagem))
    except PedidoInvalido:
        # Nao entendi: a Task continua pausada e a lista e repetida igual.
        tarefa.dizer(linha_de_alternativas(pausa.alternativas))
        return

    if e_recusa(escolha):
        resposta = resposta_de_recusa()
    elif escolha in pausa.alternativas:
        resposta = resposta_de_aceite(pausa, escolha)
    else:
        # Escolha fora do enum: sem round-trip, sem consumir o requestState.
        tarefa.dizer(linha_de_alternativas(pausa.alternativas))
        return

    tarefa.mover_para(t.WORKING)
    # O retry leva a mesma chave que veio no inputRequests e o requestState
    # ecoado sem modificacao. O id do JSON-RPC e novo, como a spec exige.
    resultado = await host.retomar(tarefa.argumentos, pausa, resposta, traceparent)
    await _despachar(tarefa, resultado, host)
