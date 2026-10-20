"""Servidor: recebe os avisos do OpenWA (WhatsApp do perito) e responde com o agente.

Rodar:  uvicorn agente_perito.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Request

from .cerebro import Cerebro, links_permitidos, montar_sistema
from .config import Config
from .memoria import Memoria
from .pix import mensagem_pix, servicos_com_pix
from .whatsapp import ClienteWhatsApp, Evento, dividir, extrair_eventos_wa, fone_normal

log = logging.getLogger("agente_perito")

# Modo ausente: AUSENTE=AAAA-MM-DD..AAAA-MM-DD (o último dia ainda vale) e AUSENTE_TEXTO.
# Responde cada pessoa uma vez só, sem gastar Claude.
AUSENTE_PADRAO = ("Oi! Recebi sua mensagem. Estou fora do escritório nestes dias e respondo "
                  "assim que voltar. Se for prazo processual urgente, escreva URGENTE e a data do prazo.")


def bloqueados_de(cfg: Config, memoria: Memoria) -> set[str]:
    """Bloqueados do .env + os do comando `#agente bloquear` / `agente-perito bloquear`."""
    extra = {x for x in memoria.ajuste("bloqueados_extra", "").split(",") if x}
    return {fone_normal(b) for b in set(cfg.bloqueados) | extra}


class Orquestrador:
    """Agrupa as mensagens de cada cliente, chama o agente e envia a resposta."""

    def __init__(self, cfg: Config, memoria: Memoria, wa: ClienteWhatsApp, cerebro: Cerebro):
        self.cfg, self.memoria, self.wa, self.cerebro = cfg, memoria, wa, cerebro
        self.pix = servicos_com_pix(cfg.pasta_conhecimento) if cfg.pix_chave else {}
        self._timers: dict[str, asyncio.Task] = {}
        self._ocupado: set[str] = set()
        self._pendente: set[str] = set()
        self._tentativas: dict[str, int] = {}
        self._ecos_esperados: set[tuple[str, str]] = set()
        self._trava_ausencia = asyncio.Lock()

    # --- entrada ---------------------------------------------------------
    def receber(self, evento: Evento) -> None:
        if evento.eco:
            self._receber_eco(evento)
            return
        if not self.memoria.registrar(evento.conversa, "user", evento.texto, evento.mid or None):
            return  # o OpenWA reenviou um aviso que já processamos
        if not self.memoria.lead(evento.conversa).get("origem"):
            self.memoria.atualizar_lead(evento.conversa, origem="whatsapp")
        self.agendar(evento.conversa)

    def _receber_eco(self, evento: Evento) -> None:
        if self.cfg.whatsapp_numero and fone_normal(evento.conversa.removeprefix("wa:").split("@")[0]) \
                == fone_normal(self.cfg.whatsapp_numero) and evento.conversa.endswith("@c.us"):
            asyncio.create_task(self._comando_do_dono(evento.texto))  # "Conversa comigo"
            return
        chave = (evento.conversa, evento.texto)
        if chave in self._ecos_esperados:
            self._ecos_esperados.discard(chave)
            return
        if not evento.mid or self.memoria.foi_enviado_pelo_agente(evento.mid):
            return
        # O perito respondeu pelo celular: registra e tira o agente da conversa por um tempo.
        if self.memoria.registrar(evento.conversa, "humano", evento.texto, evento.mid):
            self.memoria.atualizar_lead(evento.conversa, transferido=0)
            self.memoria.pausar(evento.conversa, self.cfg.pausa_humano_horas)
            log.info("O perito respondeu %s pelo celular; agente pausado por %sh.",
                     evento.conversa[-10:], self.cfg.pausa_humano_horas)

    def agendar(self, conversa: str) -> None:
        if conversa in self._ocupado:
            self._pendente.add(conversa)
            return
        anterior = self._timers.get(conversa)
        if anterior and not anterior.done():
            anterior.cancel()
        self._timers[conversa] = asyncio.create_task(self._esperar_e_responder(conversa))

    async def _esperar_e_responder(self, conversa: str) -> None:
        # Espera o cliente terminar de digitar: quem manda 3 mensagens seguidas recebe 1 resposta.
        await asyncio.sleep(self.cfg.espera_agrupar_s)
        self._ocupado.add(conversa)
        try:
            await self.responder(conversa)
        except Exception as erro:
            # O agente sempre assume: erro técnico ou limite do Claude não larga o cliente;
            # tenta de novo em 10 min e só avisa o perito na 3ª falha.
            tentativas = self._tentativas.get(conversa, 0) + 1
            self._tentativas[conversa] = tentativas
            log.warning("Erro ao responder %s (tentativa %s): %s; tento de novo em 10 min.",
                        conversa[-10:], tentativas, str(erro)[:200])
            if tentativas == 3:
                with contextlib.suppress(Exception):
                    await self.notificar(conversa, f"o agente está com erro técnico há 30 min ({type(erro).__name__})")
            asyncio.get_running_loop().call_later(600, self.agendar, conversa)
        finally:
            self._ocupado.discard(conversa)
            if conversa in self._pendente:
                self._pendente.discard(conversa)
                self.agendar(conversa)

    # --- resposta --------------------------------------------------------
    async def responder(self, conversa: str) -> None:
        if self.memoria.esta_pausado(conversa) and not self.ausente_hoje():
            return
        historico = self.memoria.historico(conversa)
        if not historico or historico[-1]["role"] != "user":
            return

        perfil = await self.wa.perfil(conversa)
        lead = self.memoria.lead(conversa)
        if perfil.get("name") and not lead["nome"]:
            self.memoria.atualizar_lead(conversa, nome=perfil["name"])
            lead = self.memoria.lead(conversa)
        if self.ausente_hoje():
            await self._avisar_ausencia(conversa, perfil.get("fone", ""))
            return
        if not self.liberado(conversa, bool(perfil.get("salvo")), perfil.get("fone", "")):
            return
        if self.memoria.enviadas_desde(conversa, time.time() - 86400) >= self.cfg.max_msgs_sessao:
            # Trava contra conversa com outro robô: para e avisa, sem mandar "aguarde".
            self.memoria.atualizar_lead(conversa, transferido=1)
            await self.notificar(conversa, f"conversa longa: {self.cfg.max_msgs_sessao} mensagens em 24 h")
            return

        hoje = datetime.now(ZoneInfo(self.cfg.fuso)).strftime("%d/%m/%Y")
        contexto = ", ".join(f"{k}: {v}" for k, v in (("data de hoje", hoje), ("nome no WhatsApp", lead["nome"])) if v)
        ficha = lead["ficha"] or {}
        sabido = "; ".join(f"{k}: {ficha[k]}" for k in
                           ("resumo_lead", "tipo_cliente", "natureza", "tipo_pericia", "comarca", "prazo",
                            "dor_resumida", "servico_recomendado", "estagio") if ficha.get(k))
        if sabido:  # memória de longo prazo: vale além das 60 últimas mensagens
            contexto += f". O que você já sabe deste cliente: {sabido}"

        await self.wa.digitando(conversa)
        decisao = await self.cerebro.decidir(historico, contexto)

        if decisao.ficha:
            self.memoria.atualizar_lead(conversa, ficha=decisao.ficha)
        for texto in decisao.mensagens:
            if self.memoria.esta_pausado(conversa):
                return  # o perito assumiu a conversa enquanto o agente pensava
            await self.enviar(conversa, texto)
        servico = (decisao.ficha or {}).get("pix_servico", "").strip()
        if decisao.mensagens and servico and servico in self.pix:
            await self.enviar(conversa, mensagem_pix(servico, self.pix[servico], self.cfg.pix_chave,
                                                     self.cfg.pix_nome or self.cfg.dono, self.cfg.pix_cidade))
        elif servico:
            log.warning("pix_servico %r não tem linha Pix: em servicos.md (ou falta PIX_CHAVE); nada enviado.", servico)
        self._tentativas.pop(conversa, None)
        if decisao.transferir:  # só avisa; o agente continua na conversa
            await self.notificar(conversa, decisao.motivo)

    async def enviar(self, conversa: str, texto: str) -> None:
        for pedaco in dividir(texto):
            self._ecos_esperados.add((conversa, pedaco))
        mids = await self.wa.enviar_texto(conversa, texto)
        for mid in mids:
            self.memoria.marcar_enviado(mid)
        self.memoria.registrar(conversa, "assistant", texto, mids[0] if mids else None)

    def retomar_pendentes(self) -> int:
        """Ao subir: responde quem ficou sem resposta (última fala do cliente nas últimas 23 h)."""
        agora, n = time.time(), 0
        for lead in self.memoria.listar_leads():
            conversa = lead["conversa"]
            ultima, ultima_do_lead = self.memoria.ultimas(conversa)
            if (ultima and ultima["papel"] == "user" and agora - ultima_do_lead < 23 * 3600
                    and not self.memoria.esta_pausado(conversa)):
                self.agendar(conversa)
                n += 1
        if n:
            log.info("Retomando %s conversa(s) que ficaram sem resposta.", n)
        return n

    # --- quem o agente atende ----------------------------------------------
    def liberado(self, conversa: str, salvo: bool, fone: str) -> bool:
        """Nunca o próprio número, bloqueados, ou quem está na agenda (família, amigos, clientes
        antigos), salvo CONTATOS_SALVOS=1. Em SANDBOX, só os números da lista."""
        numero = fone_normal(fone)
        if not numero:
            log.info("WhatsApp: não consegui o telefone de %s; não respondo.", conversa[-8:])
            return False
        if numero == fone_normal(self.cfg.whatsapp_numero) or numero in bloqueados_de(self.cfg, self.memoria):
            return False
        sandbox = {fone_normal(s) for s in self.cfg.sandbox}
        if sandbox:
            if numero not in sandbox:
                log.info("SANDBOX: ignorando …%s.", numero[-4:])
            return numero in sandbox
        if salvo and not self.cfg.contatos_salvos:
            log.info("WhatsApp: …%s está na agenda; o agente não responde.", numero[-4:])
            return False
        return True

    async def _comando_do_dono(self, texto: str) -> None:
        """Comandos que o perito manda para si mesmo no WhatsApp ("Conversa comigo"):
        #agente bloquear <número>, #agente liberar <número>, #agente bloqueados."""
        partes = texto.strip().split()
        if len(partes) < 2 or partes[0].lower() != "#agente" or partes[1].lower() not in ("bloquear", "liberar", "bloqueados"):
            return
        acao, alvos = partes[1].lower(), {fone_normal(a) for a in partes[2:] if fone_normal(a)}
        resposta = aplicar_bloqueio(self.memoria, acao, alvos, self.cfg)
        log.info("Comando do perito: %s", acao)
        try:
            dono = f"wa:{self.cfg.whatsapp_numero}@c.us"
            self._ecos_esperados.add((dono, resposta))
            await self.wa.enviar_texto(dono, resposta)
        except Exception:
            log.exception("Não consegui confirmar o comando no WhatsApp")

    # --- ausência ------------------------------------------------------------
    def ausente_hoje(self) -> bool:
        faixa = os.environ.get("AUSENTE", "")
        if ".." not in faixa:
            return False
        de, ate = (x.strip() for x in faixa.split("..", 1))
        return de <= datetime.now(ZoneInfo(self.cfg.fuso)).strftime("%Y-%m-%d") <= ate

    async def _avisar_ausencia(self, conversa: str, fone: str) -> None:
        numero = fone_normal(fone)
        if not numero or numero == fone_normal(self.cfg.whatsapp_numero) \
                or numero in bloqueados_de(self.cfg, self.memoria):
            return
        sandbox = {fone_normal(s) for s in self.cfg.sandbox}
        if sandbox and numero not in sandbox:
            return
        texto = os.environ.get("AUSENTE_TEXTO") or AUSENTE_PADRAO
        # ponytail: "já avisou" = o aviso está no histórico (só é gravado quando o envio dá certo).
        if any(m["role"] == "assistant" and texto in m["content"] for m in self.memoria.historico(conversa)):
            return
        async with self._trava_ausencia:  # um envio por vez: o WhatsApp recusa rajada
            try:
                await self.enviar(conversa, texto)
            except Exception as erro:
                log.warning("Aviso de ausência para …%s falhou (%s); tento em 5 min.", numero[-4:], erro)
                asyncio.get_running_loop().call_later(300, self.agendar, conversa)
            await asyncio.sleep(4)

    # --- retomadas -----------------------------------------------------------
    async def verificar_followups(self, agora: float | None = None) -> int:
        """Até 2 retomadas quando o cliente some: a 1ª ~30 min depois da mensagem do agente
        sem resposta, a 2ª ~2 h depois ("ficou alguma dúvida?"). Só em horário comercial,
        só para quem falou nas últimas 23 h. Se o cliente responde, a contagem zera."""
        agora = agora or time.time()
        hora = datetime.fromtimestamp(agora, ZoneInfo(self.cfg.fuso)).hour
        if not (self.cfg.followup_hora_inicio <= hora < self.cfg.followup_hora_fim) or self.ausente_hoje():
            return 0
        enviados = 0
        for lead in self.memoria.listar_leads():
            conversa = lead["conversa"]
            if self.memoria.esta_pausado(conversa) or conversa in self._ocupado:
                continue
            ultima, ultima_do_lead = self.memoria.ultimas(conversa)
            ficha = lead["ficha"] or {}
            if (not ultima or ultima["papel"] != "assistant" or not ultima_do_lead
                    or ficha.get("estagio") in ("desqualificado", "cliente", "relacionamento")
                    or ficha.get("servico_recomendado") == "nenhum"
                    or agora - ultima_do_lead >= 23.5 * 3600):
                continue
            feitas = (lead.get("retomadas") or 0) if lead.get("retomadas_ref") == ultima_do_lead else 0
            if feitas >= 2:
                continue
            sem_resposta = self.memoria.primeira_sem_resposta(conversa, ultima_do_lead)
            espera = self.cfg.retomada_1_min if feitas == 0 else self.cfg.retomada_2_min
            if not sem_resposta or agora < sem_resposta + espera * 60:
                continue
            if feitas and agora - (lead["followup_em"] or 0) < 30 * 60:
                continue  # depois do silêncio noturno, não manda as duas de uma vez
            texto = await self.texto_retomada(conversa, feitas + 1, lead, ficha)
            try:
                await self.enviar(conversa, texto)
            except Exception as erro:
                log.warning("Retomada de %s falhou (%s); não tento de novo.", conversa[-10:], str(erro)[:160])
                self.memoria.atualizar_lead(conversa, retomadas=2, retomadas_ref=ultima_do_lead)
                continue
            self.memoria.atualizar_lead(conversa, followup_em=agora, retomadas=feitas + 1,
                                        retomadas_ref=ultima_do_lead)
            enviados += 1
        return enviados

    async def texto_retomada(self, conversa: str, numero: int, lead: dict, ficha: dict) -> str:
        """O Claude escreve a retomada a partir da conversa; se falhar, usa o texto padrão."""
        pedido = ("[instrução interna, não é fala do cliente] O cliente não respondeu sua última mensagem. "
                  + ("Escreva UMA retomada curta e natural, que continue de onde a conversa parou "
                     "e termine em uma pergunta simples." if numero == 1 else
                     "Escreva UMA última mensagem curta para conferir se ficou alguma dúvida. "
                     "Sem pressão e sem repetir valor ou link.")
                  + " Não diga que é uma retomada automática. Uma mensagem só.")
        try:
            historico = self.memoria.historico(conversa) + [{"role": "user", "content": pedido}]
            decisao = await self.cerebro.decidir(historico, f"nome: {lead['nome'] or ''}")
            if decisao.mensagens and not decisao.transferir:
                return decisao.mensagens[0]
        except Exception:
            log.exception("Falha ao escrever a retomada de %s; usando o texto padrão", conversa[-10:])
        return texto_followup(lead["nome"], ficha.get("dor_resumida", ""))

    async def laco_followup(self, intervalo_s: float = 120) -> None:
        while True:
            try:
                await self.verificar_followups()
            except Exception:
                log.exception("Erro nas retomadas")
            try:
                await self.relatorio_se_hora()
            except Exception:
                log.exception("Erro no relatório diário")
            await asyncio.sleep(intervalo_s)

    # --- avisos ---------------------------------------------------------------
    async def relatorio_se_hora(self) -> None:
        agora = datetime.now(ZoneInfo(self.cfg.fuso))
        chave = f"relatorio:{agora:%Y-%m-%d}"
        if agora.hour == 20 and not self.memoria.ajuste(chave):
            self.memoria.gravar_ajuste(chave, "1")
            await self.telegram(self.relatorio_do_dia())

    def relatorio_do_dia(self) -> str:
        """Resumo das últimas 24 h, direto do banco do agente."""
        desde = time.time() - 86400
        with self.memoria._trava:  # ponytail: leitura direta; vira método da Memoria se crescer
            db = self.memoria._db
            conversas = db.execute("SELECT COUNT(DISTINCT conversa) FROM mensagens WHERE papel = 'user' "
                                   "AND criado_em > ?", (desde,)).fetchone()[0]
            respostas = db.execute("SELECT COUNT(*) FROM mensagens WHERE papel = 'assistant' AND criado_em > ?",
                                   (desde,)).fetchone()[0]
            fichas = [r[0] for r in db.execute("SELECT ficha FROM leads WHERE atualizado_em > ?", (desde,))]
        estagios: dict[str, int] = {}
        for f in fichas:
            try:
                e = (json.loads(f or "{}") or {}).get("estagio") or "sem ficha"
            except ValueError:
                e = "sem ficha"
            estagios[e] = estagios.get(e, 0) + 1
        return "\n".join([f"Agente do WhatsApp [{self.cfg.dono}], últimas 24 h",
                          f"Conversas: {conversas}", f"Respostas do agente: {respostas}",
                          "Estágios: " + (", ".join(f"{e} {n}" for e, n in sorted(estagios.items(), key=lambda x: -x[1]))
                                          or "nenhum")])

    async def telegram(self, texto: str) -> None:
        if not (self.cfg.telegram_token and self.cfg.telegram_chat_id):
            return
        async with httpx.AsyncClient(timeout=10) as http:
            try:
                await http.post(f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                                json={"chat_id": self.cfg.telegram_chat_id, "text": texto})
            except httpx.HTTPError:
                log.warning("Falha ao mandar aviso no Telegram")  # sem exception(): a URL leva o token

    async def notificar(self, conversa: str, motivo: str) -> None:
        """Avisa o perito que uma conversa precisa da atenção dele (o agente continua atendendo)."""
        lead = self.memoria.lead(conversa)
        ficha = lead["ficha"] or {}
        quem = conversa.removeprefix("wa:").split("@")[0]
        log.warning("AVISO AO PERITO …%s: %s", quem[-4:], motivo)
        await self.telegram(f"📩 [{self.cfg.dono}] {lead['nome'] or 'sem nome'} (…{quem[-4:]}): o agente está "
                            f"atendendo e quer que você saiba.\nPor quê: {motivo or 'ver conversa'}\n"
                            f"Resumo: {ficha.get('resumo_lead', '')}\nServiço: {ficha.get('servico_recomendado', '')}")


def aplicar_bloqueio(memoria: Memoria, acao: str, alvos: set[str], cfg: Config) -> str:
    """Usado pelo comando no WhatsApp e pelo `agente-perito bloquear/liberar`."""
    extra = {x for x in memoria.ajuste("bloqueados_extra", "").split(",") if x}
    if acao == "bloquear":
        extra |= alvos
        resposta = f"#agente Bloqueado: {', '.join(sorted(alvos))}. O agente não responde mais."
    elif acao == "liberar":
        extra -= alvos
        resposta = f"#agente Liberado: {', '.join(sorted(alvos))}."
    else:
        resposta = "#agente Bloqueados: " + (", ".join(sorted(bloqueados_de(cfg, memoria))) or "ninguém")
    memoria.gravar_ajuste("bloqueados_extra", ",".join(sorted(extra)))
    return resposta


def texto_followup(nome: str | None, dor: str) -> str:
    primeiro = (nome or "").split(" ")[0]
    sobre = f" sobre {dor.strip().rstrip('.')}" if dor and dor.strip() else ""
    frase = f"retomo nossa conversa{sobre}. Ficou algum ponto sem resposta para você decidir?"
    return f"{primeiro}, {frase}" if primeiro else frase[0].upper() + frase[1:]


def criar_app(cfg: Config | None = None, orquestrador: Orquestrador | None = None,
              followup: bool = True) -> FastAPI:
    cfg = cfg or Config.do_ambiente()
    if orquestrador is None:
        cerebro = Cerebro(montar_sistema(cfg.pasta_conhecimento, cfg.dono), cfg.modelo, cfg.esforco,
                          links=links_permitidos(cfg.pasta_conhecimento), motor=cfg.motor_claude)
        wa = ClienteWhatsApp(cfg.whatsapp_url, cfg.whatsapp_api_key, cfg.whatsapp_sessao, cfg.modo_teste)
        orquestrador = Orquestrador(cfg, Memoria(cfg.banco), wa, cerebro)
    orq = orquestrador

    @contextlib.asynccontextmanager
    async def ciclo(_app):
        tarefas = [asyncio.create_task(orq.laco_followup())] if followup else []
        if followup:
            orq.retomar_pendentes()
        yield
        for tarefa in tarefas:
            tarefa.cancel()

    app = FastAPI(title=f"Agente WhatsApp — {cfg.dono}", lifespan=ciclo)
    app.state.orquestrador = orq

    @app.get("/saude")
    async def saude():
        return {"ok": True, "modelo": cfg.modelo, "modo_teste": cfg.modo_teste, "sandbox": bool(cfg.sandbox)}

    @app.post("/webhook/wa/{token}")
    async def webhook_whatsapp(token: str, request: Request):
        """Avisos do OpenWA. O token longo no caminho autentica o aviso."""
        if not cfg.whatsapp_webhook_token or token != cfg.whatsapp_webhook_token:
            raise HTTPException(401, "token inválido")
        try:
            dados = await request.json()
        except ValueError:
            raise HTTPException(400, "corpo não é JSON")
        if not isinstance(dados, dict):
            raise HTTPException(400, "formato inesperado")
        for evento in extrair_eventos_wa(dados):
            orq.receber(evento)
        return {"ok": True}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # a URL do Telegram leva o token do bot


def __getattr__(nome: str):
    # `uvicorn agente_perito.app:app` cria o app só quando é pedido (os testes não precisam de .env).
    if nome == "app":
        return criar_app()
    raise AttributeError(nome)
