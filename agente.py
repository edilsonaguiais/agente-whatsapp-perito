#!/usr/bin/env python3
"""Agente de vendas do assistente técnico, para advogados, no Instagram ou no WhatsApp.

Conecta pelo Zernio (zernio.com) e pensa com o Claude ou com o Codex que você já usa.
Só biblioteca padrão do Python: nada para instalar além do Python 3.10+.

    python agente.py configurar   pergunta a chave do Zernio, o seu nome e o cérebro
    python agente.py verificar    confere se está tudo pronto
    python agente.py testar       conversa com o agente no terminal (você é o advogado)
    python agente.py              liga o agente (deixe a janela aberta)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
ENV = RAIZ / ".env"
CONHECIMENTO = RAIZ / "conhecimento"
MODELOS = RAIZ / "modelos"
BANCO = RAIZ / "dados" / "agente.db"
AVISOS = RAIZ / "dados" / "avisos.txt"
ZERNIO = "https://zernio.com/api"
CANAL_PADRAO = "whatsapp"  # instagram, whatsapp ou facebook; pode ser trocado por CANAL= no .env
OBRIGATORIOS = ("servicos.md", "tom_de_voz.md", "metodo_vendas.md")
RE_LINK = re.compile(r"https?://[^\s<>\"')\]]+")
RE_MOLDE = re.compile(r"\[(?:ex\.:|[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3})[^\]]*\]")  # campo de modelo não preenchido

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --- configuração -------------------------------------------------------------
def ler_env() -> dict[str, str]:
    v: dict[str, str] = {}
    if ENV.exists():
        for linha in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, _, val = linha.partition("=")
                v[k.strip()] = val.strip()
    return v


def gravar_env(v: dict[str, str]) -> None:
    ENV.write_text("".join(f"{k}={val}\n" for k, val in v.items()), encoding="utf-8")


def cfg(chave: str, padrao: str = "") -> str:
    return os.environ.get(chave) or ler_env().get(chave) or padrao


def lista(chave: str) -> set[str]:
    return {x.strip().lstrip("@").lower() for x in cfg(chave).split(",") if x.strip()}


# --- Zernio -------------------------------------------------------------------
class ErroZernio(Exception):
    pass


def zernio(metodo: str, caminho: str, corpo: dict | None = None, chave: str | None = None) -> dict:
    req = urllib.request.Request(
        ZERNIO + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"Authorization": f"Bearer {chave or cfg('ZERNIO_API_KEY')}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise ErroZernio(f"Zernio {e.code} em {caminho}: {e.read().decode(errors='replace')[:200]}") from None
    except urllib.error.URLError as e:
        raise ErroZernio(f"sem conexão com o Zernio: {e.reason}") from None


def canais() -> list[str]:
    return [c.strip() for c in cfg("CANAL", CANAL_PADRAO).split(",") if c.strip()]


def contas(canal: str, chave: str | None = None) -> list[dict]:
    q = urllib.parse.urlencode({"platform": canal, "status": "connected"})
    return zernio("GET", f"/v1/accounts?{q}", chave=chave).get("accounts", [])


def conversas(conta: dict) -> list[dict]:
    q = urllib.parse.urlencode({"accountId": conta["_id"], "platform": conta["platform"],
                                "status": "active", "limit": 50})
    return zernio("GET", f"/v1/inbox/conversations?{q}").get("data", [])


def mensagens(conversa: str, conta: str) -> list[dict]:
    """Últimas mensagens, da mais antiga para a mais nova, num formato único."""
    q = urllib.parse.urlencode({"accountId": conta, "limit": 30, "sortOrder": "desc"})
    brutas = zernio("GET", f"/v1/inbox/conversations/{conversa}/messages?{q}").get("messages", [])
    saida = []
    for m in reversed(brutas):
        texto = (m.get("message") or m.get("text") or "").strip()
        for a in m.get("attachments") or []:
            texto = (texto + f" [enviou um anexo: {a.get('type', 'arquivo')}]").strip()
        saida.append({"id": str(m.get("id")), "entrada": m.get("direction") == "incoming", "texto": texto,
                      "quando": _epoch(m.get("createdAt") or m.get("sentAt"))})
    return saida


def enviar(conversa: str, conta: str, texto: str) -> None:
    zernio("POST", f"/v1/inbox/conversations/{conversa}/messages", {"accountId": conta, "message": texto})


def _epoch(iso: str | None) -> float:
    try:
        return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


# --- memória ------------------------------------------------------------------
def banco() -> sqlite3.Connection:
    BANCO.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(BANCO)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS msgs (id TEXT PRIMARY KEY, conversa TEXT, papel TEXT, texto TEXT, quando REAL);
        CREATE TABLE IF NOT EXISTS leads (conversa TEXT PRIMARY KEY, nome TEXT, ficha TEXT DEFAULT '{}',
            pausado_ate REAL DEFAULT 0, respondido TEXT DEFAULT '', retomadas INTEGER DEFAULT 0, visto TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS enviados (hash TEXT, conversa TEXT, quando REAL);
    """)
    return db


def _hash(texto: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", texto).strip().encode()).hexdigest()


def lead(db: sqlite3.Connection, conversa: str, nome: str = "") -> dict:
    db.execute("INSERT OR IGNORE INTO leads(conversa, nome) VALUES (?, ?)", (conversa, nome))
    c = db.execute("SELECT nome, ficha, pausado_ate, respondido, retomadas, visto FROM leads WHERE conversa=?",
                   (conversa,)).fetchone()
    return {"nome": c[0], "ficha": json.loads(c[1] or "{}"), "pausado_ate": c[2], "respondido": c[3],
            "retomadas": c[4], "visto": c[5]}


def historico(db: sqlite3.Connection, conversa: str) -> list[tuple[str, str]]:
    ultimas = db.execute("SELECT papel, texto FROM msgs WHERE conversa=? ORDER BY quando DESC, rowid DESC LIMIT 40",
                         (conversa,)).fetchall()
    return ultimas[::-1]


def foi_o_agente(db: sqlite3.Connection, conversa: str, texto: str, quando: float) -> bool:
    """Mensagem de saída é do agente se o texto bate ou se ele enviou nessa conversa até 3 min antes."""
    return bool(db.execute("SELECT 1 FROM enviados WHERE hash=? OR (conversa=? AND ABS(quando-?)<180)",
                           (_hash(texto), conversa, quando)).fetchone())


# --- cérebro ------------------------------------------------------------------
ESQUEMA = {
    "type": "object",
    "properties": {
        "mensagem": {"type": "string", "description": "A próxima mensagem, pronta para enviar. Vazia = não responder."},
        "avisar_perito": {"type": "boolean", "description": "true quando o assistente técnico precisa SABER desta conversa."},
        "motivo": {"type": "string", "description": "O que ele precisa saber, em uma frase. Vazio se não precisa."},
        "estagio": {"type": "string", "enum": ["abertura", "conducao", "oferta", "objecao", "fechado",
                                               "nao_cliente", "recusou"]},
        "servico": {"type": "string", "description": "Serviço de <servicos> indicado, ou 'nenhum'."},
        "resumo": {"type": "string", "description": "2 frases sobre o advogado e o caso, para a ficha."},
    },
    "required": ["mensagem", "avisar_perito", "motivo", "estagio", "servico", "resumo"],
    "additionalProperties": False,
}

INSTRUCOES = """\
Você atende o {canal} de {nome}, assistente técnico (o perito contratado pela parte para
dar apoio técnico ao advogado). Quem escreve é, quase sempre, ADVOGADO. Seu trabalho é
VENDER os serviços de <servicos> para esse advogado, seguindo à risca o método de
<metodo_vendas> (Victor Damásio + Lucas Fernandes, do Olimpo) e o tom de <tom_de_voz>.

- UMA mensagem por vez, de 3 a 6 linhas, terminando em UMA pergunta (só a recusa expressa
  termina sem pergunta). Sem markdown, sem negrito, sem lista.
- No máximo 2 perguntas de diagnóstico; a sua 3ª mensagem já é a oferta. No "faz
  sentido", valor e forma de pagamento na MESMA mensagem.
- Venda aqui mesmo, nesta conversa. Não mande o advogado para outro canal.
- Só existe o que está nos arquivos: serviço, valor, prazo ou condição que não estão lá,
  não invente. Links: só os que aparecem nos arquivos.
- Você assume sempre. Nunca "aguarde", "vou ver e te retorno" ou "{nome} te responde".
  Quando {nome} precisa saber de algo (documento enviado, pedido fora dos serviços,
  advogado irritado), marque avisar_perito = true e siga a conversa.
- Perguntaram se é robô ou IA: você é o assistente de {nome} e segue ajudando.
- Quem não é cliente (colega, amigo, família): converse com naturalidade, sem oferta.
- "[enviou um anexo: ...]" você não vê nem ouve. Áudio: peça para escrever o principal.
  Documento: agradeça, diga o próximo passo e marque avisar_perito = true.
- Mensagem que não pede resposta ("ok", "valeu", emoji): mensagem vazia ou uma linha curta.
"""


def conhecimento() -> str:
    faltam = [n for n in OBRIGATORIOS if not (CONHECIMENTO / n).exists()]
    if faltam:
        raise SystemExit(f"Faltam arquivos em conhecimento/: {', '.join(faltam)}. Rode: python agente.py configurar")
    partes = []
    for arq in sorted(CONHECIMENTO.glob("*.md"), key=lambda p: (p.name not in OBRIGATORIOS, p.name)):
        partes.append(f"<{arq.stem}>\n{arq.read_text(encoding='utf-8').strip()}\n</{arq.stem}>")
    return "\n\n".join(partes)


def sistema() -> str:
    canal = {"instagram": "direct do Instagram", "whatsapp": "WhatsApp",
             "facebook": "Messenger"}.get(canais()[0], canais()[0])
    return INSTRUCOES.format(canal=canal, nome=cfg("NOME", "o assistente técnico")) + "\n" + conhecimento()


def links_permitidos() -> set[str]:
    texto = " ".join(p.read_text(encoding="utf-8") for p in CONHECIMENTO.glob("*.md"))
    return {u.rstrip(".,;:!?") for u in RE_LINK.findall(texto)}


def executavel(nome: str) -> str | None:
    """No Windows o npm instala um atalho .cmd que estraga argumentos com aspas; usa o .exe de verdade."""
    caminho = shutil.which(nome)
    if caminho and caminho.lower().endswith(".cmd"):
        alvo = re.search(r'"%dp0%\\([^"]+)"', Path(caminho).read_text(errors="ignore"))
        if alvo and alvo.group(1).lower().endswith(".exe") and (Path(caminho).parent / alvo.group(1)).exists():
            return str(Path(caminho).parent / alvo.group(1))
    return caminho


def pensar(conversa: list[tuple[str, str]], contexto: str) -> dict:
    falas = "\n".join(f"[{ {'user': 'ADVOGADO', 'assistant': 'VOCÊ', 'humano': cfg('NOME', 'PERITO')}.get(p, p)}]: {t}"
                      for p, t in conversa)
    pedido = (f"<conversa>\n{falas}\n</conversa>\n<contexto>{contexto}</contexto>\n"
              "Escreva a sua próxima mensagem e a ficha, no formato pedido.")
    motor, modelo = cfg("MOTOR", "claude"), cfg("MODELO")
    with tempfile.TemporaryDirectory(prefix="agente-") as pasta:
        p = Path(pasta)
        if motor == "codex":
            (p / "esquema.json").write_text(json.dumps(ESQUEMA), encoding="utf-8")
            args = [executavel("codex") or "codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                    "--output-schema", str(p / "esquema.json"), "-o", str(p / "saida.json")]
            args += ["-m", modelo] if modelo else []
            r = subprocess.run(args, input=sistema() + "\n\n" + pedido, cwd=pasta, capture_output=True,
                               text=True, encoding="utf-8", timeout=300)
            if r.returncode or not (p / "saida.json").exists():
                raise RuntimeError(f"Codex falhou: {(r.stderr or r.stdout)[-300:]}")
            return json.loads((p / "saida.json").read_text(encoding="utf-8"))
        (p / "sistema.md").write_text(sistema(), encoding="utf-8")
        args = [executavel("claude") or "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(ESQUEMA),
                "--system-prompt-file", str(p / "sistema.md"), "--tools", "", "--strict-mcp-config",
                "--setting-sources", "", "--no-session-persistence", "--disable-slash-commands"]
        args += ["--model", modelo] if modelo else []
        r = subprocess.run(args, input=pedido, cwd=pasta, capture_output=True, text=True, encoding="utf-8", timeout=300)
        try:
            dados = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            dados = {}
        if r.returncode or dados.get("is_error") or not isinstance(dados.get("structured_output"), dict):
            raise RuntimeError(f"Claude falhou: {str(dados.get('result') or r.stderr)[-300:]}")
        return dados["structured_output"]


def revisar(decisao: dict) -> tuple[str, str]:
    """Devolve (mensagem a enviar, motivo do aviso). Link fora do conhecimento não sai."""
    msg = re.sub(r"\s*[—–]\s*", ", ", decisao.get("mensagem", "")).replace("**", "").strip()
    aviso = decisao.get("motivo", "") if decisao.get("avisar_perito") else ""
    estranhos = {u.rstrip(".,;:!?") for u in RE_LINK.findall(msg)} - links_permitidos()
    if estranhos:
        return "", f"o agente tentou mandar um link que não está no conhecimento: {', '.join(sorted(estranhos))}"
    return msg, aviso


def avisar(quem: str, motivo: str) -> None:
    linha = f"{dt.datetime.now():%d/%m %H:%M} | {quem} | {motivo}"
    print(f"  🔔 AVISO: {linha}")
    AVISOS.parent.mkdir(exist_ok=True)
    with AVISOS.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")
    token, chat = cfg("TELEGRAM_TOKEN"), cfg("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage", method="POST",
                data=json.dumps({"chat_id": chat, "text": f"🔔 {quem}: {motivo}"}).encode(),
                headers={"Content-Type": "application/json"}), timeout=15)
        except OSError as e:
            print(f"  (Telegram falhou: {e})")


# --- o laço ------------------------------------------------------------------
def liberado(conv: dict) -> bool:
    quem = {str(conv.get(k) or "").lstrip("@").lower() for k in ("participantUsername", "participantName", "participantId")}
    quem.discard("")
    if quem & lista("BLOQUEADOS"):
        return False
    teste = lista("TESTE")
    return not teste or bool(quem & teste)


def contexto_de(info: dict, nome: str) -> str:
    hoje = dt.datetime.now().strftime("%d/%m/%Y")
    ficha = "; ".join(f"{k}: {v}" for k, v in info["ficha"].items() if v)
    return f"data de hoje: {hoje}; nome: {nome or 'não informado'}" + (f"; o que você já sabe: {ficha}" if ficha else "")


def responder(db: sqlite3.Connection, conta: dict, conv: dict, retomada: bool = False) -> None:
    cid, nome = conv["id"], conv.get("participantName") or conv.get("participantUsername") or ""
    info = lead(db, cid, nome)
    conversa = historico(db, cid)
    if retomada:
        conversa = conversa + [("user", "(o advogado não respondeu há 2 horas: escreva UMA retomada curta "
                                          "que continue de onde parou e termine em pergunta; sem repetir preço)")]
    decisao = pensar(conversa, contexto_de(info, nome))
    msg, aviso = revisar(decisao)
    ficha = {k: decisao.get(k, "") for k in ("estagio", "servico", "resumo")}
    db.execute("UPDATE leads SET ficha=? WHERE conversa=?", (json.dumps(ficha, ensure_ascii=False), cid))
    if msg:
        enviar(cid, conta["_id"], msg)
        db.execute("INSERT INTO enviados VALUES (?, ?, ?)", (_hash(msg), cid, time.time()))
        print(f"  → {nome or cid}: {msg[:90]}{'…' if len(msg) > 90 else ''}")
    if aviso:
        avisar(f"{nome or cid} ({conta['platform']})", aviso)
    db.commit()


def ciclo(db: sqlite3.Connection, conta: dict, inicio: float) -> None:
    agora = time.time()
    for conv in conversas(conta):
        cid = conv["id"]
        if not liberado(conv):
            continue
        info = lead(db, cid, conv.get("participantName") or "")
        marca = str(conv.get("lastMessageAt") or conv.get("updatedTime") or "")
        novas = []
        if not marca or marca != info["visto"]:  # só abre a conversa que mudou
            novas = [m for m in mensagens(cid, conta["_id"])
                     if not db.execute("SELECT 1 FROM msgs WHERE id=?", (m["id"],)).fetchone()]
            db.execute("UPDATE leads SET visto=? WHERE conversa=?", (marca, cid))
        for m in novas:
            papel = "user" if m["entrada"] else ("assistant" if foi_o_agente(db, cid, m["texto"], m["quando"]) else "humano")
            db.execute("INSERT OR IGNORE INTO msgs VALUES (?, ?, ?, ?, ?)", (m["id"], cid, papel, m["texto"], m["quando"]))
            if papel == "humano" and m["quando"] > agora - 86400:  # você respondeu pelo celular: o agente sai por 24 h
                db.execute("UPDATE leads SET pausado_ate=? WHERE conversa=?", (m["quando"] + 86400, cid))
                info["pausado_ate"] = m["quando"] + 86400
            if papel == "user":
                db.execute("UPDATE leads SET retomadas=0 WHERE conversa=?", (cid,))
                info["retomadas"] = 0
        db.commit()
        ultima = db.execute("SELECT id, papel, quando FROM msgs WHERE conversa=? ORDER BY quando DESC, rowid DESC LIMIT 1",
                            (cid,)).fetchone()
        if not ultima or info["pausado_ate"] > agora:
            continue
        mid, papel, quando = ultima
        if papel == "user" and mid != info["respondido"] and quando > inicio - 600 and agora - quando > 8:
            db.execute("UPDATE leads SET respondido=? WHERE conversa=?", (mid, cid))
            responder(db, conta, conv)
        elif (papel == "assistant" and info["retomadas"] == 0 and 7200 < agora - quando < 72000
              and 8 <= dt.datetime.now().hour < 21 and info["ficha"].get("estagio") not in ("recusou", "nao_cliente", "fechado")):
            db.execute("UPDATE leads SET retomadas=1 WHERE conversa=?", (cid,))
            responder(db, conta, conv, retomada=True)


def rodar() -> int:
    if not cfg("ZERNIO_API_KEY"):
        print("Falta configurar. Rode: python agente.py configurar")
        return 1
    db = banco()
    minhas = [c for canal in canais() for c in contas(canal)]
    if not minhas:
        print(f"Nenhuma conta de {', '.join(canais())} conectada no Zernio. Conecte em zernio.com e rode de novo.")
        return 1
    inicio = time.time()
    print(f"Agente ligado para {', '.join('@' + c.get('username', '?') for c in minhas)}"
          f"{' (modo TESTE: só ' + cfg('TESTE') + ')' if cfg('TESTE') else ''}. Deixe esta janela aberta.")
    while True:
        for conta in minhas:
            try:
                ciclo(db, conta, inicio)
            except (ErroZernio, RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"  ! {e} (tento de novo no próximo ciclo)")
        time.sleep(int(cfg("INTERVALO", "20")))


# --- comandos ----------------------------------------------------------------
def perguntar(texto: str, atual: str = "") -> str:
    r = input(f"{texto}{f' [{atual}]' if atual else ''}: ").strip()
    return r or atual


def configurar() -> int:
    v = ler_env()
    print("Configuração do agente (Enter mantém o valor entre colchetes).\n")
    while True:
        v["ZERNIO_API_KEY"] = perguntar("Chave da API do Zernio (zernio.com > Settings > API Keys)", v.get("ZERNIO_API_KEY", ""))
        try:
            achadas = contas(v.get("CANAL", CANAL_PADRAO).split(",")[0], v["ZERNIO_API_KEY"])
            print(f"  ok, chave aceita. Contas conectadas: {', '.join('@' + a.get('username', '?') for a in achadas) or 'nenhuma ainda'}")
            break
        except ErroZernio as e:
            print(f"  essa chave não funcionou ({e}). Tente de novo.")
    v["NOME"] = perguntar("Seu nome como os advogados conhecem (ex.: Dra. Marina Silva)", v.get("NOME", ""))
    motores = [m for m in ("claude", "codex") if executavel(m)]
    v["MOTOR"] = perguntar(f"Cérebro: claude ou codex (achei: {', '.join(motores) or 'nenhum'})", v.get("MOTOR", motores[0] if motores else "claude"))
    v["TESTE"] = perguntar("Fase de teste: @ ou telefone que o agente pode atender (vazio = todos)", v.get("TESTE", ""))
    v.setdefault("CANAL", CANAL_PADRAO)
    gravar_env(v)
    CONHECIMENTO.mkdir(exist_ok=True)
    if not (CONHECIMENTO / "servicos.md").exists() and perguntar(
            "Começar com o exemplo pronto da Dra. Marina, só para testar? (s/n)", "n").lower().startswith("s"):
        for exemplo in (RAIZ / "exemplo").glob("*.md"):
            shutil.copy(exemplo, CONHECIMENTO / exemplo.name)
    for modelo in MODELOS.glob("*.md"):
        if not (CONHECIMENTO / modelo.name).exists():
            shutil.copy(modelo, CONHECIMENTO / modelo.name)
    print("\nPronto. Agora preencha conhecimento/servicos.md e conhecimento/tom_de_voz.md "
          "(peça ao Claude ou ao Codex: 'preencha meu conhecimento') e rode: python agente.py verificar")
    return 0


def verificar() -> int:
    ok = True

    def linha(bom: bool, texto: str) -> None:
        nonlocal ok
        ok &= bom
        print(f"  {'✅' if bom else '❌'} {texto}")

    linha(bool(cfg("ZERNIO_API_KEY")), "chave do Zernio no .env")
    try:
        achadas = [c for canal in canais() for c in contas(canal)]
        linha(bool(achadas), f"conta conectada no Zernio: {', '.join('@' + c.get('username', '?') for c in achadas) or 'nenhuma'}")
        if achadas:
            conversas(achadas[0])
            linha(True, "inbox do Zernio liberado")
    except ErroZernio as e:
        linha(False, str(e) + (" (o inbox do Zernio precisa estar ativo no seu plano)" if "inbox" in str(e) else ""))
    for n in OBRIGATORIOS:
        linha((CONHECIMENTO / n).exists(), f"conhecimento/{n}")
    moldes = [f"{p.name}: {m}" for p in CONHECIMENTO.glob("*.md") for m in RE_MOLDE.findall(p.read_text(encoding="utf-8"))]
    linha(not moldes, "conhecimento preenchido" if not moldes else f"ainda falta preencher: {'; '.join(moldes[:4])}")
    linha(bool(executavel(cfg("MOTOR", "claude"))), f"cérebro instalado: {cfg('MOTOR', 'claude')}")
    print("\nTudo certo: rode `python agente.py testar` e depois `python agente.py`." if ok else "\nCorrija os itens ❌.")
    return 0 if ok else 1


def testar() -> int:
    print(f"Você é o advogado. Escreva como no {canais()[0]} (Ctrl+C para sair).\n")
    conversa: list[tuple[str, str]] = []
    while True:
        try:
            fala = input("ADVOGADO> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if not fala:
            continue
        conversa.append(("user", fala))
        decisao = pensar(conversa, f"data de hoje: {dt.datetime.now():%d/%m/%Y}")
        msg, aviso = revisar(decisao)
        print(f"AGENTE> {msg or '(não respondeu)'}")
        print(f"        [{decisao.get('estagio')} | {decisao.get('servico')}{' | AVISO: ' + aviso if aviso else ''}]\n")
        conversa.append(("assistant", msg or "(silêncio)"))


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else "rodar"
    acoes = {"configurar": configurar, "verificar": verificar, "testar": testar, "rodar": rodar}
    if comando not in acoes:
        print(__doc__)
        sys.exit(1)
    try:
        sys.exit(acoes[comando]())
    except KeyboardInterrupt:
        print("\nAgente desligado.")
