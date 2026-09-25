"""Exercita o host MCP do agente de ponta a ponta, sem A2A nenhum.

Ferramenta de depuracao: percorre descoberta, leitura do resource, reserva
livre, conflito, pausa e retomada, respondendo a elicitation na mao. Serve
para conferir, no stderr do servidor MCP, que o `tools/list` vem antes do
primeiro `tools/call`, que o `traceparent` e propagado e que o id do retry
difere do id do request inicial.

    python "agente/ciclo_manual.py"
    python "agente/ciclo_manual.py" --traceparent 00-<32 hex>-<16 hex>-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys

from cliente_mcp import HostMCP, resposta_de_aceite, resposta_de_recusa

DIA = "2026-11-03"


def h(hora: str) -> str:
    return f"{DIA}T{hora}:00-03:00"


def titulo(texto: str) -> None:
    print(f"\n{'=' * 6} {texto} {'=' * 6}")


def pedido(sala: str, inicio: str, fim: str, responsavel: str) -> dict[str, str]:
    return {"sala": sala, "inicio": h(inicio), "fim": h(fim), "responsavel": responsavel}


async def executar(traceparent: str | None) -> int:
    async with HostMCP() as host:
        titulo("descoberta")
        print("tools/list devolveu:", host.tools)

        titulo("resource")
        versao = await host.versao_da_politica(traceparent)
        print("versao da politica:", versao)

        titulo("reserva em intervalo livre")
        argumentos = pedido("sala-porao", "09:00", "10:00", "Doc")
        resultado = await host.reservar(argumentos, traceparent)
        print("concluiu:", json.dumps(resultado.dados, ensure_ascii=False))

        titulo("conflito: o servidor pede escolha")
        argumentos = pedido("sala-garagem", "14:00", "15:00", "Marty")
        pausa = await host.reservar(argumentos, traceparent)
        if not hasattr(pausa, "alternativas"):
            print("ERRO: esperava uma pausa, veio", pausa)
            return 1
        print("chave      :", pausa.chave)
        print("campo      :", pausa.campo)
        print("alternativas:", ", ".join(pausa.alternativas))
        print("requestState:", pausa.request_state[:32], "... (opaco, nao interpretado)")

        titulo("retomada com a escolha")
        escolhida = pausa.alternativas[0]
        resultado = await host.retomar(
            argumentos, pausa, resposta_de_aceite(pausa, escolhida), traceparent
        )
        print(f"escolhi {escolhida}; concluiu:", json.dumps(resultado.dados, ensure_ascii=False))

        titulo("recusa")
        argumentos = pedido("sala-garagem", "14:30", "15:30", "Biff")
        pausa = await host.reservar(argumentos, traceparent)
        resultado = await host.retomar(argumentos, pausa, resposta_de_recusa(), traceparent)
        print("recusei; concluiu:", json.dumps(resultado.dados, ensure_ascii=False))

        titulo("erro de execucao da tool")
        argumentos = pedido("sala-delorean", "09:00", "10:00", "Doc")
        resultado = await host.reservar(argumentos, traceparent)
        print("isError:", resultado.erro, "| texto:", resultado.texto)

    print("\nciclo completo. Confira no stderr do servidor MCP:")
    print("  - o tools/list anterior ao primeiro tools/call")
    print("  - o traceparent com o trace-id usado aqui")
    print("  - os dois tools/call da mesma reserva, com ids diferentes")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--traceparent",
        default=f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01",
        help="traceparent de entrada; por padrao gera um novo",
    )
    argumentos = p.parse_args()
    print("trace-id desta execucao:", argumentos.traceparent.split("-")[1])
    return asyncio.run(executar(argumentos.traceparent))


if __name__ == "__main__":
    sys.exit(main())
