"""Pix copia e cola (BR Code estático do Banco Central) com valor fixo, sem depender de banco nem de site.

O perito marca em `conhecimento/servicos.md` os serviços de preço fechado com uma linha
`Pix: 497,00` dentro da seção do serviço (`## Nome do serviço`). Quando o cliente diz sim,
o agente devolve o nome do serviço em `pix_servico` e o código é montado aqui, a partir de
PIX_CHAVE, PIX_NOME e PIX_CIDADE do .env. O modelo nunca escreve o código: ele só escolhe o serviço.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _campo(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(dados: str) -> str:
    crc = 0xFFFF
    for byte in dados.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii(texto: str, limite: int) -> str:
    """O BR Code aceita só ASCII simples no nome e na cidade."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", sem_acento).strip().upper()[:limite]


def pix_copia_e_cola(chave: str, valor: Decimal, nome: str, cidade: str, txid: str = "***") -> str:
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    corpo = (_campo("00", "01") + _campo("26", conta) + _campo("52", "0000") + _campo("53", "986")
             + _campo("54", f"{valor:.2f}") + _campo("58", "BR") + _campo("59", _ascii(nome, 25))
             + _campo("60", _ascii(cidade, 15)) + _campo("62", _campo("05", txid[:25] or "***")) + "6304")
    return corpo + _crc16(corpo)


def brl(valor: Decimal) -> str:
    inteiro, centavos = f"{valor:.2f}".split(".")
    return f"R$ {int(inteiro):,}".replace(",", ".") + f",{centavos}"


RE_PIX = re.compile(r"^\s*-?\s*\**pix\**\s*:\s*\**\s*(?:R\$\s*)?([\d.]+,\d{2})", re.IGNORECASE)


def servicos_com_pix(pasta: Path) -> dict[str, Decimal]:
    """{nome do serviço: valor} para cada seção `## ` de servicos.md que tem linha `Pix: 0,00`."""
    arquivo = pasta / "servicos.md"
    if not arquivo.exists():
        return {}
    saida, atual = {}, ""
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        if linha.startswith("## "):
            atual = linha[3:].strip()
        elif atual and (m := RE_PIX.match(linha)):
            try:
                saida[atual] = Decimal(m.group(1).replace(".", "").replace(",", "."))
            except InvalidOperation:
                continue
    return saida


def mensagem_pix(servico: str, valor: Decimal, chave: str, nome: str, cidade: str) -> str:
    txid = re.sub(r"[^A-Za-z0-9]", "", _ascii(servico, 25))[:25] or "***"
    codigo = pix_copia_e_cola(chave, valor, nome, cidade or "BRASIL", txid)
    return (f"Pix de {brl(valor)} ({servico}). Copie o código abaixo e cole no app do seu banco, "
            f"em Pix copia e cola. Chave: {chave}\n\n{codigo}")
