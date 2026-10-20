"""agente-perito: configura, pareia e confere o agente de WhatsApp do perito.

    agente-perito configurar        pergunta as chaves, confere cada uma e grava o .env
    agente-perito parear            mostra o QR para ligar o WhatsApp do perito
    agente-perito verificar         checklist: o que está funcionando e o que falta
    agente-perito testar            conversa com o agente no terminal, sem WhatsApp
    agente-perito bloquear NÚMERO   o agente nunca mais responde esse número
    agente-perito liberar NÚMERO    desfaz o bloqueio
    agente-perito leads             lista quem conversou e grava dados/leads.csv
    agente-perito github URL        liga o conhecimento a um repositório GitHub seu e puxa
    agente-perito atualizar         puxa de novo o conhecimento do GitHub
    agente-perito iniciar           sobe o servidor (o Docker já faz isso por você)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import getpass
import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

import httpx

from .cerebro import OBRIGATORIOS, OPCIONAIS, links_permitidos
from .config import RAIZ, Config
from .memoria import Memoria
from .whatsapp import SessaoOpenWA, fone_normal

ENV = RAIZ / ".env"
CONHECIMENTO = RAIZ / "conhecimento"
ARQUIVOS = OBRIGATORIOS + OPCIONAIS
OK, ERRO, AVISO = "✅", "❌", "⚠️ "

ORDEM_ENV = [
    ("# Quem é você", None),
    ("DONO_NOME", ""),
    ("# Claude pela assinatura: `claude setup-token` gera o token (sk-ant-oat...)", None),
    ("CLAUDE_MOTOR", "assinatura"), ("CLAUDE_CODE_OAUTH_TOKEN", ""),
    ("# Ou por chave de API (CLAUDE_MOTOR=api; MODELO com id completo, ex.: claude-opus-5-5)", None),
    ("ANTHROPIC_API_KEY", ""), ("MODELO", "sonnet"), ("ESFORCO", "medium"),
    ("# WhatsApp (OpenWA). A chave e o token são gerados pelo configurar; não precisa mexer.", None),
    ("WHATSAPP_NUMERO", ""), ("WHATSAPP_URL", "http://openwa:2785/api"), ("WHATSAPP_API_KEY", ""),
    ("WHATSAPP_SESSAO", ""), ("WHATSAPP_WEBHOOK_TOKEN", ""),
    ("# Quem o agente atende (números com DDI, separados por vírgula)", None),
    ("SANDBOX", ""), ("BLOQUEADOS", ""), ("CONTATOS_SALVOS", "0"),
    ("# Aviso no Telegram (opcional)", None),
    ("TELEGRAM_TOKEN", ""), ("TELEGRAM_CHAT_ID", ""),
    ("# Pix copia e cola (opcional; vale para serviços com 'Pix:' em servicos.md)", None),
    ("PIX_CHAVE", ""), ("PIX_NOME", ""), ("PIX_CIDADE", ""),
    ("# Conhecimento no GitHub (opcional; token só de leitura para repositório privado)", None),
    ("GITHUB_REPO", ""), ("GITHUB_TOKEN", ""),
    ("# Freios e horários", None),
    ("MAX_MSGS_SESSAO", "40"), ("RETOMADA_1_MIN", "30"), ("RETOMADA_2_MIN", "120"),
    ("AUSENTE", ""), ("AUSENTE_TEXTO", ""), ("FUSO", "America/Sao_Paulo"), ("MODO_TESTE", "0"),
]


# --- .env ------------------------------------------------------------------
def ler_env() -> dict[str, str]:
    valores: dict[str, str] = {}
    if ENV.exists():
        for linha in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip()
    return valores


def gravar_env(valores: dict[str, str]) -> None:
    linhas, usadas = [], set()
    for chave, padrao in ORDEM_ENV:
        if padrao is None:
            linhas.append(f"\n{chave}")
            continue
        linhas.append(f"{chave}={valores.get(chave, padrao)}")
        usadas.add(chave)
    extras = [f"{k}={v}" for k, v in valores.items() if k not in usadas]
    if extras:
        linhas += ["\n# Outros"] + extras
    # escreve no mesmo arquivo (no Docker o .env é montado como arquivo)
    with open(ENV, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas).lstrip() + "\n")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def mascarar(valor: str) -> str:
    return f"…{valor[-4:]}" if len(valor) > 8 else ("definido" if valor else "")


def perguntar(rotulo: str, atual: str = "", segredo: bool = False, opcional: bool = False) -> str:
    dica = f" [Enter mantém {mascarar(atual) if segredo else atual}]" if atual else (" [opcional]" if opcional else "")
    while True:
        valor = (getpass.getpass if segredo else input)(f"{rotulo}{dica}: ").strip()
        if valor:
            return valor
        if atual or opcional:
            return atual
        print("   Esse campo é obrigatório.")


def titulo(texto: str) -> None:
    print(f"\n── {texto} " + "─" * max(0, 60 - len(texto)))


def numero_valido(valor: str) -> str:
    """Só dígitos, com DDI. 62999990000 vira 5562999990000."""
    d = re.sub(r"\D", "", valor)
    if len(d) in (10, 11):
        d = "55" + d
    return d if 12 <= len(d) <= 13 else ""


# --- checagens ----------------------------------------------------------------
async def checar_claude_assinatura(modelo: str) -> str | None:
    """Uma chamada mínima pelo Claude Code, com o login da assinatura."""
    if not shutil.which("claude"):
        return "o Claude Code (comando claude) não está instalado"
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "falta CLAUDE_CODE_OAUTH_TOKEN (gere com `claude setup-token` no seu computador)"
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", "--output-format", "json", "--model", modelo, "--tools", "",
        "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    saida, erro = await proc.communicate(b"Responda apenas: ok")
    try:
        dados = json.loads(saida.decode() or "{}")
    except json.JSONDecodeError:
        return f"Claude Code falhou: {erro.decode()[-200:]}"
    return None if not dados.get("is_error") and proc.returncode == 0 else f"Claude Code: {str(dados.get('result'))[:200]}"


async def checar_claude_api(chave: str, modelo: str) -> str | None:
    import anthropic
    try:
        await anthropic.AsyncAnthropic(api_key=chave).models.retrieve(modelo)
        return None
    except anthropic.AuthenticationError:
        return "chave do Claude recusada"
    except anthropic.NotFoundError:
        return f"o modelo {modelo} não está disponível para esta chave"
    except anthropic.APIError as e:
        return f"erro ao falar com o Claude: {e}"


def placeholders(pasta: Path) -> list[str]:
    """Trechos de modelo ainda não preenchidos, tipo [SEU NOME]."""
    achados = []
    for nome in ARQUIVOS:
        arquivo = pasta / nome
        if arquivo.exists():
            achados += [f"{nome}: {m}" for m in re.findall(r"\[[A-ZÁÉÍÓÚÂÊÔÃÕÇ@ /_.]{4,}[^\]]*\]",
                                                        arquivo.read_text(encoding="utf-8"))]
    return achados


# --- configurar ---------------------------------------------------------------
async def configurar() -> int:
    v = ler_env()
    print("Vou te fazer algumas perguntas e conferir cada chave na hora.\n"
          "Enter mantém o valor atual. Senha e token não aparecem na tela enquanto você digita.")

    titulo("1/6 Quem é você")
    v["DONO_NOME"] = perguntar("Seu nome, como o agente vai se referir a você (ex.: Dr. João Souza)",
                               v.get("DONO_NOME", ""))

    titulo("2/6 Claude (o cérebro do agente)")
    print("   1) pela sua assinatura do Claude (Pro/Max): no SEU computador rode\n"
          "      `claude setup-token` e cole aqui o token que começa com sk-ant-oat\n"
          "   2) por chave de API (console.anthropic.com), paga por uso")
    padrao = "2" if v.get("CLAUDE_MOTOR") == "api" else "1"
    if (input(f"   Escolha [{padrao}]: ").strip() or padrao) == "1":
        v["CLAUDE_MOTOR"] = "assinatura"
        modelo = v.get("MODELO") or "sonnet"
        while True:
            v["CLAUDE_CODE_OAUTH_TOKEN"] = perguntar("Token da assinatura (sk-ant-oat...)",
                                                     v.get("CLAUDE_CODE_OAUTH_TOKEN", ""), segredo=True)
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = v["CLAUDE_CODE_OAUTH_TOKEN"]
            erro = await checar_claude_assinatura(modelo)
            if not erro:
                print(f"   {OK} assinatura aceita (modelo {modelo})")
                break
            print(f"   {ERRO} {erro}. Gere outro com `claude setup-token` e cole de novo.")
            v["CLAUDE_CODE_OAUTH_TOKEN"] = ""
    else:
        v["CLAUDE_MOTOR"] = "api"
        if v.get("MODELO", "sonnet") in ("sonnet", "opus", ""):
            v["MODELO"] = "claude-opus-5-5"
        while True:
            v["ANTHROPIC_API_KEY"] = perguntar("Chave da API (sk-ant-...)", v.get("ANTHROPIC_API_KEY", ""), segredo=True)
            erro = await checar_claude_api(v["ANTHROPIC_API_KEY"], v["MODELO"])
            if not erro:
                print(f"   {OK} chave aceita (modelo {v['MODELO']})")
                break
            print(f"   {ERRO} {erro}. Tente de novo.")
            v["ANTHROPIC_API_KEY"] = ""

    titulo("3/6 WhatsApp")
    print("   O número que vai atender os clientes. Use um WhatsApp Business só do trabalho,\n"
          "   nunca o seu número pessoal com família e amigos.")
    while True:
        n = numero_valido(perguntar("Número com DDD (ex.: 62999990000)", v.get("WHATSAPP_NUMERO", "")))
        if n:
            v["WHATSAPP_NUMERO"] = n
            break
        print(f"   {ERRO} número inválido. Digite DDD + número.")
    v["WHATSAPP_API_KEY"] = v.get("WHATSAPP_API_KEY") or secrets.token_urlsafe(32)
    v["WHATSAPP_WEBHOOK_TOKEN"] = v.get("WHATSAPP_WEBHOOK_TOKEN") or secrets.token_urlsafe(24)
    print("\n   Fase de teste (recomendado): o agente só responde os números que você listar aqui.\n"
          "   Coloque o seu celular pessoal e o de alguém de confiança. Para abrir a todos depois,\n"
          "   rode `agente-perito configurar` de novo e deixe este campo vazio (digite -).")
    teste = perguntar("Números de teste, separados por vírgula", v.get("SANDBOX", ""), opcional=True)
    v["SANDBOX"] = "" if teste.strip() == "-" else ",".join(
        x for x in (numero_valido(t) for t in teste.split(",")) if x)
    print(f"   {OK} " + (f"modo teste: só {v['SANDBOX']}" if v["SANDBOX"] else "o agente atende todo mundo fora da sua agenda"))

    titulo("4/6 Aviso no Telegram (opcional)")
    print("   Você recebe um aviso quando uma conversa precisar de você (documento chegou,\n"
          "   prazo urgente, alerta ético). Crie um bot com o @BotFather e cole o token. Enter pula.")
    v["TELEGRAM_TOKEN"] = perguntar("Token do bot do Telegram", v.get("TELEGRAM_TOKEN", ""), segredo=True, opcional=True)
    if v["TELEGRAM_TOKEN"] and not v.get("TELEGRAM_CHAT_ID"):
        v["TELEGRAM_CHAT_ID"] = await descobrir_chat_telegram(v["TELEGRAM_TOKEN"])

    titulo("5/6 Pix (opcional)")
    print("   Para serviços de preço fechado (marcados com 'Pix:' em servicos.md), o agente manda\n"
          "   o Pix copia e cola com o valor certo depois que o cliente aceita. Enter pula.")
    v["PIX_CHAVE"] = perguntar("Sua chave Pix", v.get("PIX_CHAVE", ""), opcional=True)
    if v["PIX_CHAVE"]:
        v["PIX_NOME"] = perguntar("Nome do recebedor, como está no banco", v.get("PIX_NOME", "") or v["DONO_NOME"])
        v["PIX_CIDADE"] = perguntar("Cidade do recebedor", v.get("PIX_CIDADE", ""))

    gravar_env(v)  # grava já: o passo 6 pode usar o token do GitHub
    titulo("6/6 Conhecimento (seus serviços, tom de voz, método)")
    preparar_conhecimento(v)
    gravar_env(v)
    print(f"\n{OK} Configuração gravada em {ENV}.")
    return 0


async def descobrir_chat_telegram(token: str) -> str:
    base = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=40) as http:
        try:
            eu = (await http.get(f"{base}/getMe")).json()
        except httpx.HTTPError:
            print(f"   {ERRO} não consegui falar com o Telegram. Pulei esta etapa.")
            return ""
        if not eu.get("ok"):
            print(f"   {ERRO} token do Telegram recusado. Pulei esta etapa.")
            return ""
        print(f"   Abra o Telegram, procure @{eu['result']['username']} e mande /start. Esperando…")
        for _ in range(6):
            dados = (await http.get(f"{base}/getUpdates", params={"timeout": 25})).json()
            for item in reversed(dados.get("result", [])):
                chat = (item.get("message") or {}).get("chat", {})
                if chat.get("id"):
                    await http.post(f"{base}/sendMessage", json={
                        "chat_id": chat["id"], "text": "✅ Pronto! Aviso aqui quando uma conversa do WhatsApp precisar de você."})
                    print(f"   {OK} Telegram ligado (mandei uma mensagem de teste).")
                    return str(chat["id"])
    print(f"   {AVISO}não recebi o /start. Rode `agente-perito configurar` de novo depois.")
    return ""


def preparar_conhecimento(v: dict | None = None) -> None:
    CONHECIMENTO.mkdir(exist_ok=True)
    if all((CONHECIMENTO / n).exists() for n in OBRIGATORIOS):
        print(f"   {OK} a pasta conhecimento/ já tem os arquivos (não mexi).")
        return
    exemplos = sorted(p.name for p in (RAIZ / "exemplos").iterdir() if p.is_dir()) if (RAIZ / "exemplos").exists() else []
    print("   Com o que você quer começar?\n   1) modelo em branco para preencher\n"
          "   2) puxar do meu repositório no GitHub")
    for i, nome in enumerate(exemplos, start=3):
        print(f"   {i}) EXEMPLO pronto para estudar: {nome} (troque tudo pelos seus dados antes de abrir)")
    escolha = input("   Escolha [1]: ").strip() or "1"
    if escolha == "2" and v is not None:
        v["GITHUB_REPO"] = perguntar("Endereço do repositório (https://github.com/usuario/repo)", v.get("GITHUB_REPO", ""))
        v["GITHUB_TOKEN"] = perguntar("Token do GitHub só de leitura (Enter se o repositório é público)",
                                      v.get("GITHUB_TOKEN", ""), segredo=True, opcional=True)
        if sincronizar_github(v["GITHUB_REPO"], v["GITHUB_TOKEN"]) == 0:
            completar_com_modelo()
            return
        print("   Vou começar pelo modelo em branco; rode `agente-perito atualizar` depois.")
        escolha = "1"
    origem = RAIZ / "modelos" / "conhecimento"
    if escolha.isdigit() and 3 <= int(escolha) < 3 + len(exemplos):
        origem = RAIZ / "exemplos" / exemplos[int(escolha) - 3]
    for p in origem.glob("*.md"):
        if not (CONHECIMENTO / p.name).exists():
            shutil.copy(p, CONHECIMENTO / p.name)
    print(f"   {OK} copiei {origem.relative_to(RAIZ)} para conhecimento/.")


def completar_com_modelo() -> None:
    """Repositório sem algum arquivo obrigatório: completa com o modelo em branco."""
    for nome in ARQUIVOS:
        if not (CONHECIMENTO / nome).exists():
            shutil.copy(RAIZ / "modelos" / "conhecimento" / nome, CONHECIMENTO / nome)
            print(f"   {AVISO}{nome} não veio do GitHub; copiei o modelo em branco.")


def sincronizar_github(url: str, token: str = "") -> int:
    from .github import sincronizar
    try:
        nomes = sincronizar(url, CONHECIMENTO, RAIZ / "dados" / "repo-conhecimento", token)
    except (RuntimeError, ValueError, OSError) as erro:
        print(f"   {ERRO} {erro}")
        return 1
    print(f"   {OK} {len(nomes)} arquivo(s) do GitHub em conhecimento/: {', '.join(nomes)}")
    return 0


# --- parear -------------------------------------------------------------------
def mostrar_qr(qr: str) -> None:
    if qr.startswith("data:image"):
        destino = RAIZ / "dados" / "qr.png"
        destino.parent.mkdir(exist_ok=True)
        destino.write_bytes(base64.b64decode(qr.split(",", 1)[1]))
        print(f"   O OpenWA mandou o QR como imagem (gravei em {destino}).\n"
              "   Abra o painel do OpenWA no seu computador para ler: veja o README, 'Parear pelo painel'.")
        return
    import qrcode
    q = qrcode.QRCode(border=1)
    q.add_data(qr)
    q.print_ascii(invert=True)


async def parear() -> int:
    v = ler_env()
    cfg = Config.do_ambiente()
    if not (cfg.whatsapp_api_key and cfg.whatsapp_webhook_token):
        print(f"{ERRO} Rode `agente-perito configurar` primeiro.")
        return 1
    s = SessaoOpenWA(cfg.whatsapp_url, cfg.whatsapp_api_key)
    titulo("1/3 OpenWA no ar?")
    for _ in range(30):
        try:
            await s.http.get(cfg.whatsapp_url.removesuffix("/api") + "/api/health")
            break
        except httpx.HTTPError:
            await asyncio.sleep(2)
    else:
        print(f"{ERRO} o OpenWA não respondeu em {cfg.whatsapp_url}. Rode `agente-perito logs openwa`.")
        return 1
    print(f"   {OK} OpenWA respondendo")

    titulo("2/3 Sessão do WhatsApp")
    sessao = cfg.whatsapp_sessao
    try:
        if not sessao:
            sessao = await s.criar("perito")
            await s.ligar_webhook(sessao, f"http://agente:8000/webhook/wa/{cfg.whatsapp_webhook_token}")
            v["WHATSAPP_SESSAO"] = sessao
            gravar_env(v)
            print(f"   {OK} sessão criada e ligada ao agente")
        await s.iniciar(sessao)
    except RuntimeError as erro:
        print(f"{ERRO} {erro}")
        return 1

    titulo("3/3 Leia o QR com o celular do perito")
    print("   No celular: WhatsApp > Configurações > Aparelhos conectados > Conectar aparelho.")
    ultimo = ""
    for _ in range(90):  # ~3 min
        try:
            estado = await s.status(sessao)
            if estado in ("ready", "connected", "authenticated", "open", "working"):
                print(f"\n{OK} WhatsApp conectado. O agente já pode atender.")
                return 0
            qr = await s.qr(sessao)
        except RuntimeError:
            qr = ""
        if qr and qr != ultimo:
            ultimo = qr
            print("\n   QR novo (ele troca a cada ~20 s):")
            mostrar_qr(qr)
        await asyncio.sleep(2)
    print(f"{AVISO}não vi a conexão em 3 minutos. Rode `agente-perito parear` de novo.")
    return 1


# --- verificar ----------------------------------------------------------------
async def verificar() -> int:
    cfg = Config.do_ambiente()
    v = ler_env()
    falhas = 0

    def linha(ok: bool, texto: str, conserto: str = "") -> None:
        nonlocal falhas
        falhas += 0 if ok else 1
        print(f"{OK if ok else ERRO} {texto}" + ("" if ok or not conserto else f"\n     → {conserto}"))

    chave_claude = "CLAUDE_CODE_OAUTH_TOKEN" if cfg.motor_claude == "assinatura" else "ANTHROPIC_API_KEY"
    faltando = [k for k in ("DONO_NOME", chave_claude, "WHATSAPP_NUMERO", "WHATSAPP_API_KEY", "WHATSAPP_WEBHOOK_TOKEN")
                if not v.get(k) and not os.environ.get(k)]
    linha(not faltando, "configuração completa" if not faltando else f"faltam no .env: {', '.join(faltando)}",
          "rode `agente-perito configurar`")

    pasta = cfg.pasta_conhecimento
    existentes = [n for n in OBRIGATORIOS if (pasta / n).exists()]
    linha(len(existentes) == len(OBRIGATORIOS), f"conhecimento em {pasta}",
          f"faltam {', '.join(set(OBRIGATORIOS) - set(existentes))}; rode `agente-perito configurar`")
    if len(existentes) == len(OBRIGATORIOS):
        pendentes = placeholders(pasta)
        linha(not pendentes, "conhecimento preenchido" if not pendentes else
              f"ainda há campos do modelo para preencher: {'; '.join(pendentes[:5])}",
              "edite os arquivos: agente-perito editar servicos.md")
        if "EXEMPLO" in (pasta / "servicos.md").read_text(encoding="utf-8")[:400]:
            linha(False, "servicos.md ainda é o EXEMPLO do curso", "troque pelos seus serviços antes de abrir ao público")
        print(f"   {len(links_permitidos(pasta))} link(s) autorizados no conhecimento")

    if cfg.motor_claude == "assinatura":
        erro = await checar_claude_assinatura(cfg.modelo)
        linha(erro is None, f"Claude pela assinatura ({cfg.modelo})" if not erro else erro,
              "gere um token novo com `claude setup-token` e rode `agente-perito configurar`")
    elif v.get("ANTHROPIC_API_KEY"):
        erro = await checar_claude_api(v["ANTHROPIC_API_KEY"], cfg.modelo)
        linha(erro is None, f"Claude pela API ({cfg.modelo})" if not erro else erro, "confira a chave")

    if cfg.whatsapp_sessao:
        try:
            estado = await SessaoOpenWA(cfg.whatsapp_url, cfg.whatsapp_api_key).status(cfg.whatsapp_sessao)
            linha(estado in ("ready", "connected", "authenticated", "open", "working"),
                  f"WhatsApp: sessão {estado or 'sem status'}", "rode `agente-perito parear`")
        except (RuntimeError, httpx.HTTPError) as erro:
            linha(False, f"OpenWA não respondeu: {str(erro)[:120]}", "rode `agente-perito logs openwa`")
    else:
        linha(False, "WhatsApp ainda não pareado", "rode `agente-perito parear`")

    try:
        async with httpx.AsyncClient(timeout=5) as http:
            ok = (await http.get("http://localhost:8000/saude")).status_code == 200
    except httpx.HTTPError:
        ok = False
    linha(ok, "agente no ar", "rode `agente-perito reiniciar` e veja `agente-perito logs`")
    print(f"   modo teste (SANDBOX): {', '.join(sorted(cfg.sandbox))}" if cfg.sandbox
          else "   aberto: atende todo mundo fora da sua agenda")

    print("\nTudo certo! 🎉" if not falhas else f"\n{falhas} item(ns) para resolver.")
    return 1 if falhas else 0


# --- bloquear, leads, github --------------------------------------------------
def bloquear(acao: str, numeros: list[str]) -> int:
    from .app import aplicar_bloqueio
    cfg = Config.do_ambiente()
    alvos = {fone_normal(numero_valido(n) or n) for n in numeros if re.sub(r"\D", "", n)}
    if acao != "bloqueados" and not alvos:
        print(f"{ERRO} informe o número, ex.: agente-perito {acao} 62999990000")
        return 1
    print(aplicar_bloqueio(Memoria(cfg.banco), acao, alvos, cfg).removeprefix("#agente "))
    return 0


def listar_leads() -> int:
    """Quem conversou: tipo de cliente, perícia, serviço indicado e resumo. Grava dados/leads.csv."""
    cfg = Config.do_ambiente()
    linhas = []
    for l in Memoria(cfg.banco).listar_leads():
        f = l["ficha"] or {}
        linhas.append({
            "telefone": l["conversa"].removeprefix("wa:").split("@")[0], "nome": l["nome"] or "",
            "tipo_cliente": f.get("tipo_cliente", ""), "natureza": f.get("natureza", ""),
            "pericia": f.get("tipo_pericia", ""), "comarca": f.get("comarca", ""), "prazo": f.get("prazo", ""),
            "servico": f.get("servico_recomendado", ""), "estagio": f.get("estagio", ""),
            "alerta_etico": f.get("alerta_etico", ""), "resumo": f.get("resumo_lead", ""),
            "atualizado": time.strftime("%d/%m/%Y %H:%M", time.localtime(l["atualizado_em"] or 0))})
    destino = cfg.banco.parent / "leads.csv"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8-sig", newline="") as arq:
        escritor = csv.DictWriter(arq, fieldnames=list(linhas[0]) if linhas else ["telefone"], delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)
    for x in linhas:
        print(f"{x['nome'][:24]:<24} {x['tipo_cliente']:<12} {x['estagio']:<14} {x['servico'][:30]}\n    {x['resumo'][:150]}")
    print(f"\n{len(linhas)} contato(s). Planilha (abre no Excel): {destino}")
    return 0


def github(url: str | None) -> int:
    v = ler_env()
    if url:
        v["GITHUB_REPO"] = url.strip()
        if not v.get("GITHUB_TOKEN"):
            v["GITHUB_TOKEN"] = perguntar("Token do GitHub só de leitura (Enter se o repositório é público)",
                                          segredo=True, opcional=True)
        gravar_env(v)
    if not v.get("GITHUB_REPO"):
        print(f"{ERRO} nenhum repositório ligado. Use: agente-perito github https://github.com/usuario/repo")
        return 1
    codigo = sincronizar_github(v["GITHUB_REPO"], v.get("GITHUB_TOKEN", ""))
    if codigo == 0:
        completar_com_modelo()
    return codigo


def iniciar() -> int:
    import uvicorn
    uvicorn.run("agente_perito.app:app", host="0.0.0.0", port=int(os.environ.get("PORTA", "8000")), workers=1,
                access_log=False)  # sem log de acesso: o caminho do webhook leva o token
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agente-perito", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)
    for nome in ("configurar", "parear", "verificar", "testar", "iniciar", "leads", "atualizar", "bloqueados"):
        sub.add_parser(nome)
    for nome in ("bloquear", "liberar"):
        sub.add_parser(nome).add_argument("numeros", nargs="+")
    sub.add_parser("github").add_argument("url", nargs="?")
    args = parser.parse_args(argv)

    try:
        if args.comando == "iniciar":
            return iniciar()
        if args.comando == "testar":
            from .simular import main as simular
            asyncio.run(simular())
            return 0
        if args.comando in ("bloquear", "liberar", "bloqueados"):
            return bloquear(args.comando, getattr(args, "numeros", []))
        if args.comando == "leads":
            return listar_leads()
        if args.comando in ("github", "atualizar"):
            return github(getattr(args, "url", None))
        return asyncio.run({"configurar": configurar, "parear": parear, "verificar": verificar}[args.comando]())
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
