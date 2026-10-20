"""Converse com o agente no terminal, sem WhatsApp, para testar o tom e o método.

    agente-perito testar
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

from .cerebro import Cerebro, links_permitidos, montar_sistema
from .config import Config
from .pix import mensagem_pix, servicos_com_pix


async def main() -> None:
    cfg = Config.do_ambiente()
    cerebro = Cerebro(montar_sistema(cfg.pasta_conhecimento, cfg.dono), cfg.modelo, cfg.esforco,
                      links=links_permitidos(cfg.pasta_conhecimento), motor=cfg.motor_claude)
    pix = servicos_com_pix(cfg.pasta_conhecimento)
    historico: list[dict] = []
    print("Você é o cliente (advogado, parte, empresa). Escreva como no WhatsApp. Ctrl+C sai.\n")
    while True:
        try:
            fala = input("cliente> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not fala:
            continue
        if historico and historico[-1]["role"] == "user":
            historico[-1]["content"] += "\n" + fala
        else:
            historico.append({"role": "user", "content": fala})
        decisao = await cerebro.decidir(historico, f"data de hoje: {date.today():%d/%m/%Y}")
        for texto in decisao.mensagens:
            print(f"\nagente> {texto}\n")
        if decisao.mensagens:
            historico.append({"role": "assistant", "content": "\n".join(decisao.mensagens)})
        servico = decisao.ficha.get("pix_servico", "")
        if servico in pix:
            print("agente> " + mensagem_pix(servico, pix[servico], cfg.pix_chave or "SUA-CHAVE-PIX",
                                            cfg.pix_nome or cfg.dono, cfg.pix_cidade) + "\n")
        print("   ficha:", json.dumps(decisao.ficha, ensure_ascii=False))
        if decisao.transferir:
            print(f"   >>> AVISO AO PERITO (Telegram): {decisao.motivo}")


if __name__ == "__main__":
    asyncio.run(main())
