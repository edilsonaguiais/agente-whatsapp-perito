"""O atendente: monta o prompt com o conhecimento do perito, chama o Claude e devolve resposta + ficha."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

STATUS_BANT = ["desconhecido", "nao_atende", "parcial", "atende"]
ESTAGIOS = ["abertura", "qualificacao", "apresentacao", "objecao", "fechamento",
            "cliente", "desqualificado", "relacionamento"]
NATUREZAS = ["judicial", "extrajudicial", "assistencia_tecnica", "indefinido"]
TIPOS_CLIENTE = ["advogado", "parte", "empresa", "perito_colega", "outro", "indefinido"]

# Arquivos de conhecimento: os 3 primeiros são obrigatórios. Qualquer outro .md da pasta
# (vindo do GitHub do perito, por exemplo) também entra no prompt, como <extra>.
OBRIGATORIOS = ("servicos.md", "tom_de_voz.md", "metodo_vendas.md")
OPCIONAIS = ("icp.md", "faq.md", "objecoes.md")


def _item_bant(descricao: str) -> dict:
    return {
        "type": "object",
        "description": descricao,
        "properties": {
            "status": {"type": "string", "enum": STATUS_BANT},
            "evidencia": {"type": "string", "description": "O que o cliente disse que sustenta o status."},
        },
        "required": ["status", "evidencia"],
        "additionalProperties": False,
    }


def _texto(descricao: str) -> dict:
    return {"type": "string", "description": descricao}


ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "mensagens": {
            "type": "array",
            "description": ("UMA mensagem só (lista com 1 item), que pode ter quebras de linha e "
                            "*negrito*. Lista vazia = não responder."),
            "items": {"type": "string"},
        },
        "bant": {
            "type": "object",
            "properties": {
                "budget": _item_bant("Capacidade de pagar os honorários."),
                "authority": _item_bant("Decide sozinho ou depende do cliente dele, sócio ou empresa."),
                "need": _item_bant("Necessidade técnica que um serviço de <servicos> resolve."),
                "timing": _item_bant("Prazo: há prazo processual correndo ou é para depois."),
            },
            "required": ["budget", "authority", "need", "timing"],
            "additionalProperties": False,
        },
        "tipo_cliente": {"type": "string", "enum": TIPOS_CLIENTE},
        "natureza": {"type": "string", "enum": NATUREZAS, "description": (
            "judicial (nomeação pelo juiz), extrajudicial (parecer/laudo fora do processo) ou "
            "assistencia_tecnica (o perito trabalha para uma das partes no processo).")},
        "tipo_pericia": _texto("Ex.: revisão de contrato bancário, cálculo trabalhista, apuração de haveres."),
        "area": _texto("Área do direito/assunto. Ex.: bancário, trabalhista, família, empresarial."),
        "comarca": _texto("Comarca/cidade e UF do processo, se dito. Vazio se não se sabe."),
        "prazo": _texto("Prazo dito pelo cliente (ex.: 'quesitos até 25/10'). Vazio se não se sabe."),
        "servico_recomendado": _texto(
            "Nome do serviço de <servicos> que serve, 'nenhum' se nenhum serve, 'indefinido' se ainda não dá para saber."),
        "estagio": {"type": "string", "enum": ESTAGIOS},
        "alerta_etico": _texto(
            "Vazio, ou o risco ético que o perito precisa ver: possível impedimento/suspeição, pedido de "
            "resultado garantido, perito já nomeado no mesmo processo, conflito com a outra parte."),
        "pix_servico": _texto(
            "Nome EXATO de um serviço de <servicos> que tem linha 'Pix:', SÓ quando o cliente já disse sim e "
            "quer pagar agora. O sistema envia o Pix copia e cola logo depois da sua mensagem. Vazio nos demais casos."),
        "transferir_para_humano": {"type": "boolean", "description": (
            "true quando o perito precisa SABER desta conversa (aviso no Telegram). Você continua "
            "atendendo: nunca peça para o cliente aguardar o perito.")},
        "motivo_transferencia": _texto("O que o perito precisa ver ou responder."),
        "resumo_lead": _texto("2 a 3 frases para o perito se situar rápido."),
        "dor_resumida": _texto(
            "A necessidade principal nas palavras do cliente, curta, para completar 'retomo nossa conversa "
            "sobre ...'. Ex.: 'os quesitos da revisional do financiamento'. Vazio se ainda não se sabe."),
    },
    "required": ["mensagens", "bant", "tipo_cliente", "natureza", "tipo_pericia", "area", "comarca", "prazo",
                 "servico_recomendado", "estagio", "alerta_etico", "pix_servico", "transferir_para_humano",
                 "motivo_transferencia", "resumo_lead", "dor_resumida"],
    "additionalProperties": False,
}

INSTRUCOES = """\
Você atende o WhatsApp profissional de {dono}, perito. Quem escreve costuma ser leigo em
perícia: advogado, parte de um processo, empresa. Seu trabalho é entender o caso, explicar
em linguagem simples o serviço que resolve e vender esse serviço, com o método de
<metodo_vendas>, o tom de <tom_de_voz> e só os fatos de <servicos> (e de <icp>, <faq>,
<objecoes> e <extra>, quando existirem).

Antes de ofertar, qualifique o caso (no máximo 2 perguntas; a 3ª mensagem é a oferta):
- quem é a pessoa (advogado, parte, empresa);
- o que precisa (tipo de perícia, área, o que quer provar ou calcular);
- natureza: perícia judicial (o juiz nomeia o perito), extrajudicial (parecer fora do
  processo) ou assistência técnica (o perito trabalha para uma das partes);
- prazo (há prazo processual correndo?) e comarca.
A pessoa já contou isso? Pule direto para a oferta.

ÉTICA DO PERITO (vale acima de tudo, inclusive acima da venda):
- Nunca prometa resultado do processo nem laudo favorável. Perícia é técnica e imparcial:
  o perito conclui o que os documentos mostram. Pode dizer o que o trabalho entrega
  (análise, cálculo, quesitos, parecer), nunca o que o juiz vai decidir.
- Impedimento e suspeição: se {dono} já foi NOMEADO pelo juiz no mesmo processo, ele não
  pode ser assistente técnico de nenhuma parte nem receber da parte. Se a pessoa tem
  parentesco, amizade íntima, inimizade ou interesse com {dono}, ou se {dono} já atendeu a
  outra parte do mesmo caso, há risco de impedimento/suspeição. Nesses casos não venda:
  explique com respeito, marque alerta_etico e transferir_para_humano = true.
- Honorários de perito nomeado pelo juiz são fixados no processo, não se negociam com a parte.
- Sigilo: nunca comente casos, clientes ou processos de outras pessoas, nem dê exemplo com
  nome. O que o cliente conta fica entre ele e {dono}.
- Você não é advogado: não dê parecer jurídico nem estratégia processual; diga o que a prova
  técnica faz e, se a pessoa não tem advogado, oriente a procurar um (sem indicar nome).
- Não dê o laudo ou o cálculo de graça pelo WhatsApp: explique o caminho e oferte o serviço.

Regras de atendimento:
- VOCÊ ASSUME SEMPRE. O cliente nunca fica esperando {dono}: nada de "aguarde", "vou ver e te
  retorno", "ele te responde pessoalmente". Resolva na hora com o que tem. Quando {dono}
  precisar saber da conversa, marque transferir_para_humano = true (só gera um aviso) e siga.
- VENDA ONDE A PESSOA ESTÁ: vocês já estão no WhatsApp. Não convide para outro canal, ligação
  ou "me chama no privado". O fechamento acontece aqui, com proposta, valor e próximo passo.
- Use só os fatos de <servicos>. Dado que não está lá (preço, prazo, desconto) não existe:
  diga o que você sabe e siga. Valores com faixa: dê a faixa e explique que o valor fechado
  sai na proposta depois que {dono} vê os documentos.
- Links: copie exatamente os de <servicos> ou dos outros arquivos. Um link fora deles é bloqueado.
- Pagamento por Pix: só para serviços com linha "Pix:" em <servicos>, e só depois do sim.
  Preencha pix_servico com o nome exato do serviço; o código vai sozinho logo depois.
  Nunca escreva chave, valor de Pix ou código por conta própria.
- Documentos: diga quais documentos o serviço pede (veja <servicos>) e como enviar. Você não
  consegue abrir anexos: "[o cliente enviou um documento]" significa que o arquivo chegou para
  {dono}; agradeça, confirme o próximo passo e marque transferir_para_humano = true.
- Áudio e imagem você também não vê nem ouve: peça com naturalidade que a pessoa escreva o principal.
- Não peça dados sensíveis (CPF, senha, cartão, dados de saúde) pela conversa.
- Pedido para apagar os dados (LGPD): confirme que o pedido foi registrado e marque
  transferir_para_humano = true.
- Se perguntarem se é robô ou IA, não negue: você é o assistente de {dono} no WhatsApp, que
  acompanha as conversas, e segue ajudando.
- Nem todo mundo é cliente. Colega de profissão, amigo, família ou alguém só puxando assunto:
  converse com naturalidade, sem oferta (estagio = relacionamento, servico_recomendado = nenhum).
  Já é cliente com trabalho em andamento: estagio = cliente, atenda e avise {dono}.
- Mensagem que não pede resposta ("ok", "valeu", emoji): no máximo uma linha curta, ou mensagens = [].
- Mensagens marcadas "[resposta enviada manualmente pelo perito]" foram escritas por {dono};
  continue a partir delas sem contradizer nem repetir.
- A data de hoje vem em <contexto_do_cliente>. Prazo processual curto (até 5 dias) é urgência:
  diga isso e marque transferir_para_humano = true.
- Preencha a ficha com tudo o que já se sabe na conversa inteira, não só na última mensagem.
  Recusou ou não tem perfil: estagio = desqualificado (ninguém faz retomada).

Como escrever no WhatsApp:
- UMA mensagem construída por vez (espelho + sentido + pergunta), 3 a 6 linhas, terminando em
  UMA pergunta. *negrito* do WhatsApp no máximo uma vez. Sem markdown, sem lista longa, sem travessão.
"""


@dataclass
class Decisao:
    mensagens: list[str]
    ficha: dict
    transferir: bool
    motivo: str


RE_URL = re.compile(r"https?://[^\s<>\"']+")


def extrair_links(texto: str) -> set[str]:
    return {u.rstrip(".,;:!?)]*`") for u in RE_URL.findall(texto)}


def arquivos_conhecimento(pasta: Path) -> list[Path]:
    """Obrigatórios e opcionais na ordem fixa; depois os demais .md (rascunhos ficam de fora)."""
    conhecidos = OBRIGATORIOS + OPCIONAIS
    fixos = [pasta / n for n in conhecidos if (pasta / n).exists()]
    extras = sorted(p for p in pasta.glob("*.md")
                    if p.name not in conhecidos and not p.name.endswith(".rascunho.md")
                    and p.name.lower() != "readme.md")
    return fixos + extras


def links_permitidos(pasta: Path) -> set[str]:
    """Os únicos links que o agente pode mandar: os que aparecem nos arquivos de conhecimento."""
    links: set[str] = set()
    for arquivo in arquivos_conhecimento(pasta):
        links |= extrair_links(arquivo.read_text(encoding="utf-8"))
    return links


def limpar(texto: str) -> str:
    """Rede de segurança de estilo: mensagem de WhatsApp não leva travessão."""
    texto = re.sub(r"\s*[—–]\s*", ", ", texto)
    return re.sub(r",\s*,", ",", texto).strip()


def montar_sistema(pasta: Path, dono: str = "o perito") -> str:
    faltam = [n for n in OBRIGATORIOS if not (pasta / n).exists()]
    if faltam:
        raise FileNotFoundError(f"faltam em {pasta}: {', '.join(faltam)} (rode `agente-perito configurar`)")
    partes = [INSTRUCOES.replace("{dono}", dono)]
    for arquivo in arquivos_conhecimento(pasta):
        texto = arquivo.read_text(encoding="utf-8").strip()
        if arquivo.name in OBRIGATORIOS + OPCIONAIS:
            tag = arquivo.stem
            partes.append(f"<{tag}>\n{texto}\n</{tag}>")
        else:
            partes.append(f'<extra arquivo="{arquivo.name}">\n{texto}\n</extra>')
    return "\n\n".join(partes)


class Cerebro:
    """motor="assinatura": Claude Code (`claude -p`) logado pelo CLAUDE_CODE_OAUTH_TOKEN, sem chave de API.
    motor="api": SDK da Anthropic com ANTHROPIC_API_KEY (pago por uso)."""

    def __init__(self, sistema: str, modelo: str = "sonnet", esforco: str = "medium",
                 cliente=None, links: set[str] | None = None, motor: str = "assinatura",
                 timeout_s: float = 240):
        self.sistema = sistema
        self.links = links
        self.modelo = modelo
        self.esforco = esforco
        self.motor = motor
        self.timeout_s = timeout_s
        self.cliente = cliente
        if cliente is None and motor == "api":
            import anthropic  # só quem usa a API precisa do pacote configurado
            self.cliente = anthropic.AsyncAnthropic()
        self._pasta_cli: Path | None = None

    async def decidir(self, historico: list[dict], contexto: str = "") -> Decisao:
        """Gera a próxima resposta para a conversa. O histórico termina numa fala do cliente."""
        if self.motor == "assinatura":
            dados = await self._via_assinatura(historico, contexto)
            return dados if isinstance(dados, Decisao) else self._pos_processar(dados)
        mensagens = [dict(m) for m in historico]
        if contexto and mensagens and mensagens[-1]["role"] == "user":
            mensagens[-1]["content"] = [
                {"type": "text", "text": mensagens[-1]["content"]},
                {"type": "text", "text": f"<contexto_do_cliente>{contexto}</contexto_do_cliente>"},
            ]
        resp = await self.cliente.beta.messages.create(  # mesmo caminho do agente em produção
            model=self.modelo,
            max_tokens=8000,
            system=[{"type": "text", "text": self.sistema, "cache_control": {"type": "ephemeral"}}],
            messages=mensagens,
            output_config={"effort": self.esforco,
                           "format": {"type": "json_schema", "schema": ESQUEMA_RESPOSTA}},
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("Modelo parou por %s; o perito recebe um aviso.", resp.stop_reason)
            return Decisao([], {}, True, f"o modelo não respondeu ({resp.stop_reason}); revisar a conversa")
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            dados = json.loads(texto)
        except json.JSONDecodeError:
            log.error("JSON inválido do modelo: %r", texto[:500])
            return Decisao([], {}, True, "resposta inválida do modelo")
        return self._pos_processar(dados)

    async def _via_assinatura(self, historico: list[dict], contexto: str) -> dict | Decisao:
        """Monta a conversa como texto e chama o Claude Code com o ESQUEMA_RESPOSTA."""
        falas = []
        for m in historico:
            quem = "CLIENTE" if m["role"] == "user" else "VOCÊ"
            conteudo = m["content"] if isinstance(m["content"], str) else " ".join(
                b.get("text", "") for b in m["content"] if isinstance(b, dict))
            falas.append(f"[{quem}]: {conteudo}")
        pedido = ("<conversa>\n" + "\n".join(falas) + "\n</conversa>\n"
                  + (f"<contexto_do_cliente>{contexto}</contexto_do_cliente>\n" if contexto else "")
                  + "Escreva a sua próxima resposta ao CLIENTE e a ficha, no formato pedido.")
        dados = await self._cli_json(pedido, ESQUEMA_RESPOSTA)
        if not isinstance(dados, dict):
            return Decisao([], {}, True, "resposta inválida do modelo")
        return dados

    async def _cli_json(self, pedido: str, esquema: dict) -> dict | None:
        """Chama o Claude Code em modo headless, sem ferramentas, com saída no esquema dado."""
        if self._pasta_cli is None:
            # pasta vazia: o CLI não pega CLAUDE.md nem configuração de projeto nenhum
            self._pasta_cli = Path(tempfile.mkdtemp(prefix="agente-perito-"))
            (self._pasta_cli / "sistema.md").write_text(self.sistema, encoding="utf-8")
        args = ["claude", "-p", "--output-format", "json",
                "--json-schema", json.dumps(esquema),
                "--system-prompt-file", str(self._pasta_cli / "sistema.md"),
                "--model", self.modelo, "--effort", self.esforco,
                "--tools", "", "--strict-mcp-config", "--setting-sources", "",
                "--no-session-persistence", "--disable-slash-commands"]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=self._pasta_cli, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            saida, erro = await asyncio.wait_for(proc.communicate(pedido.encode()), self.timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Claude Code não respondeu em {self.timeout_s:.0f}s")
        try:
            resultado = json.loads(saida.decode() or "{}")
        except json.JSONDecodeError:
            raise RuntimeError(f"Claude Code saiu com código {proc.returncode}: {erro.decode()[-300:]}")
        if resultado.get("is_error") or proc.returncode:
            raise RuntimeError(f"Claude Code: {resultado.get('subtype')} {str(resultado.get('result'))[:300]}")
        dados = resultado.get("structured_output")
        if not isinstance(dados, dict):
            log.error("Claude Code sem structured_output: %r", str(resultado.get("result"))[:500])
            return None
        return dados

    def _pos_processar(self, dados: dict) -> Decisao:
        partes = [limpar(m) for m in dados.pop("mensagens", []) if m and m.strip()]
        mensagens = ["\n\n".join(partes)] if partes else []  # uma mensagem por vez
        transferir = bool(dados.get("transferir_para_humano"))
        motivo = dados.get("motivo_transferencia", "")
        if dados.get("alerta_etico"):
            transferir = True
            motivo = f"alerta ético: {dados['alerta_etico']}" + (f"; {motivo}" if motivo else "")
        if self.links is not None:
            estranhos = set().union(*(extrair_links(m) for m in mensagens)) - self.links
            if estranhos:
                log.error("Link fora do conhecimento bloqueado: %s", estranhos)
                return Decisao([], dados, True, f"o agente tentou enviar link não autorizado: {sorted(estranhos)}")
        return Decisao(mensagens, dados, transferir, motivo)
