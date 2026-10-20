"""Canal WhatsApp pelo OpenWA (WhatsApp Web rodando no servidor, motor Baileys; não é a API oficial).

Cada conversa vira "wa:<id do chat>" na memória. Grupos, listas, canais e status são
ignorados sempre: o agente só atende conversa individual. Mensagens que o perito manda pelo
celular chegam como eco e tiram o agente da conversa por um tempo.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

LIMITE_WA = 3000  # o WhatsApp aceita textos longos; o tom de voz mantém as mensagens curtas


@dataclass
class Evento:
    """Uma mensagem recebida (ou eco de uma enviada) numa conversa individual."""
    conversa: str
    mid: str
    texto: str
    eco: bool  # True quando a mensagem saiu do número do perito (agente ou ele pelo celular)


def dividir(texto: str, limite: int = LIMITE_WA) -> list[str]:
    """Quebra um texto longo em pedaços que cabem no limite de bytes."""
    pedacos, atual = [], ""
    for palavra in texto.split(" "):
        candidato = f"{atual} {palavra}".strip()
        if len(candidato.encode()) > limite and atual:
            pedacos.append(atual)
            atual = palavra
        else:
            atual = candidato
    if atual:
        pedacos.append(atual)
    return pedacos


def numero(chat_id: str) -> str:
    return re.sub(r"\D", "", chat_id.split("@")[0])


def fone_normal(valor: str) -> str:
    """Telefone comparável: só dígitos e, no Brasil, sem o nono dígito do celular
    (o WhatsApp grava 5562999990000 como 556299990000)."""
    d = re.sub(r"\D", "", valor or "")
    if len(d) == 13 and d.startswith("55") and d[4] == "9":
        d = d[:4] + d[5:]
    return d


def chat_de(conversa: str) -> str:
    """A conversa guarda o id do chat como veio (…@c.us ou …@lid); sem sufixo, é telefone."""
    resto = conversa.removeprefix("wa:")
    return resto if "@" in resto else f"{resto}@c.us"


def _id(valor) -> str:
    if isinstance(valor, dict):
        return str(valor.get("_serialized") or valor.get("id") or "")
    return str(valor or "")


def _idade_s(valor) -> float | None:
    """Idade da mensagem em segundos (aceita epoch em s/ms ou data ISO)."""
    try:
        if isinstance(valor, (int, float)) or (isinstance(valor, str) and valor.isdigit()):
            v = float(valor)
            return time.time() - (v / 1000 if v > 1e12 else v)
        if isinstance(valor, str) and valor:
            return time.time() - datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None
    return None


ANEXOS = {"ptt": "um áudio", "audio": "um áudio", "image": "uma imagem", "video": "um vídeo",
          "document": "um documento", "sticker": "uma figurinha", "location": "uma localização"}


def extrair_eventos_wa(payload: dict) -> list[Evento]:
    """Converte o aviso do OpenWA em eventos. Tolerante ao formato (data/message/payload)."""
    evento = str(payload.get("event") or payload.get("type") or "")
    if evento and evento not in ("message.received", "message.sent", "message", "message_create"):
        return []
    dados = payload.get("data") or payload.get("payload") or payload
    msg = dados.get("message") if isinstance(dados.get("message"), dict) else dados
    de, para = _id(msg.get("from")), _id(msg.get("to"))
    eco = (bool(msg.get("fromMe")) or bool((msg.get("key") or {}).get("fromMe"))
           or str(msg.get("direction", "")).lower() == "outgoing" or evento == "message.sent")
    idade = _idade_s(msg.get("timestamp") or msg.get("t") or payload.get("timestamp"))
    if idade is not None and idade > 300:
        return []  # histórico reenviado na (re)conexão: nunca vira conversa nova
    chat = para if eco else de
    if not chat or chat.endswith(("@g.us", "@broadcast", "@newsletter")) or "status@" in chat:
        return []  # grupos, listas, canais e status: nunca
    tipo = str(msg.get("type") or "chat")
    texto = str(msg.get("body") or msg.get("text") or msg.get("caption") or "").strip()
    if tipo in ANEXOS:
        texto = f"[o cliente enviou {ANEXOS[tipo]}] {texto}".strip()
    if not texto:
        return []
    return [Evento(conversa=f"wa:{chat}", mid=_id(msg.get("id") or msg.get("waMessageId")), texto=texto, eco=eco)]


class ClienteWhatsApp:
    def __init__(self, base: str, api_key: str, sessao: str, modo_teste: bool = False,
                 http: httpx.AsyncClient | None = None):
        self.base = base.rstrip("/")
        self.sessao = sessao
        self.modo_teste = modo_teste
        self.http = http or httpx.AsyncClient(timeout=30)
        self.cab = {"X-API-Key": api_key, "Content-Type": "application/json"}
        self._fone: dict[str, str] = {}  # chat …@lid -> telefone, aprendido no perfil

    def destino(self, conversa: str) -> str:
        """Responde no telefone (…@c.us): enviar para o id interno (…@lid) pode não chegar."""
        chat = chat_de(conversa)
        fone = self._fone.get(chat)
        return f"{fone}@c.us" if fone else chat

    def _url(self, rota: str) -> str:
        return f"{self.base}/sessions/{self.sessao}/{rota}"

    async def enviar_texto(self, conversa: str, texto: str) -> list[str]:
        mids = []
        for pedaco in dividir(texto):
            if self.modo_teste:
                log.info("[MODO TESTE] WhatsApp para %s: %s", conversa, pedaco)
                mids.append(f"teste-wa-{time.time_ns()}")
                continue
            for tentativa in range(3):  # o Baileys reconecta sozinho (408/515): espera e tenta de novo
                resp = await self.http.post(self._url("messages/send-text"), headers=self.cab,
                                            json={"chatId": self.destino(conversa), "text": pedaco})
                if resp.status_code != 409:
                    break
                log.warning("WhatsApp reconectando; nova tentativa em 15 s (%s/3)", tentativa + 1)
                await asyncio.sleep(15)
            if resp.status_code >= 400:
                log.error("Falha ao enviar WhatsApp para %s: %s %s", conversa, resp.status_code, resp.text[:300])
                resp.raise_for_status()
            corpo = resp.json() if resp.content else {}
            mids.append(_id(corpo.get("id") or corpo.get("messageId") or (corpo.get("data") or {}).get("id")))
        return mids

    async def digitando(self, conversa: str) -> None:
        if self.modo_teste:
            return
        try:
            await self.http.post(self._url("chats/typing"), headers=self.cab,
                                 json={"chatId": self.destino(conversa), "state": "typing"})
        except httpx.HTTPError:
            pass  # "digitando…" é enfeite: falhar aqui não pode travar a resposta

    async def perfil(self, conversa: str) -> dict:
        """Nome, telefone verdadeiro (o chat pode vir como …@lid) e se está na agenda do perito."""
        chat = chat_de(conversa)
        dados = {"name": "", "salvo": False, "fone": numero(chat) if chat.endswith("@c.us") else ""}
        if self.modo_teste:
            return dados
        try:
            resp = await self.http.get(self._url(f"contacts/{chat}"), headers=self.cab)
            if resp.status_code == 200:
                c = resp.json()
                c = c.get("data", c) if isinstance(c, dict) else {}
                dados["name"] = c.get("pushName") or c.get("pushname") or c.get("name") or ""
                dados["salvo"] = bool(c.get("isMyContact"))
                if str(c.get("id", "")).endswith("@c.us"):
                    dados["fone"] = numero(str(c["id"]))
            if not dados["fone"] and chat.endswith("@lid"):
                resp = await self.http.get(self._url(f"contacts/{chat}/phone"), headers=self.cab)
                if resp.status_code == 200:
                    dados["fone"] = re.sub(r"\D", "", str(resp.json().get("phone", "")))
            if dados["fone"]:
                self._fone[chat] = dados["fone"]
            else:
                log.warning("WhatsApp: sem telefone para %s (OpenWA respondeu %s)", chat[-12:], resp.status_code)
        except httpx.HTTPError as erro:
            log.warning("WhatsApp: consulta do contato %s falhou: %s", chat[-12:], type(erro).__name__)
        return dados


# --- sessão e pareamento (usado pelo comando `agente-perito parear`) --------------
class SessaoOpenWA:
    """Cria a sessão, liga o webhook e busca o QR. Rotas do OpenWA (rmyndharis/OpenWA)."""

    def __init__(self, base: str, api_key: str, http: httpx.AsyncClient | None = None):
        self.base = base.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=30)
        self.cab = {"X-API-Key": api_key, "Content-Type": "application/json"}

    async def _req(self, metodo: str, rota: str, **kw) -> dict:
        resp = await self.http.request(metodo, f"{self.base}/{rota}", headers=self.cab, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenWA {metodo} /{rota}: {resp.status_code} {resp.text[:300]}")
        corpo = resp.json() if resp.content else {}
        return corpo.get("data", corpo) if isinstance(corpo, dict) else {"lista": corpo}

    async def criar(self, nome: str) -> str:
        dados = await self._req("POST", "sessions", json={"name": nome})
        return str(dados.get("id") or dados.get("sessionId") or nome)

    async def ligar_webhook(self, sessao: str, url: str) -> None:
        await self._req("POST", f"sessions/{sessao}/webhooks",
                        json={"url": url, "events": ["message.received", "message.sent"]})

    async def iniciar(self, sessao: str) -> None:
        await self._req("POST", f"sessions/{sessao}/start")

    async def qr(self, sessao: str) -> str:
        dados = await self._req("GET", f"sessions/{sessao}/qr")
        return str(dados.get("qr") or dados.get("qrCode") or dados.get("code") or "")

    async def status(self, sessao: str) -> str:
        dados = await self._req("GET", f"sessions/{sessao}")
        return str(dados.get("status") or dados.get("state") or "").lower()
