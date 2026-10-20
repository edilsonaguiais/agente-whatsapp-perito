"""Configuração lida do arquivo .env (criado por `agente-perito configurar`)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _carregar_dotenv(caminho: Path) -> None:
    """Carrega um .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _sim(valor: str) -> bool:
    return valor.strip().lower() in ("1", "true", "sim")


def _fones(valor: str) -> frozenset:
    return frozenset(v.strip().lstrip("+") for v in valor.split(",") if v.strip())


@dataclass(frozen=True)
class Config:
    # Quem é o perito (como o agente se refere a ele)
    dono: str = "o perito"

    # Claude
    modelo: str = "sonnet"  # apelido do Claude Code; no motor "api" use o id completo (ex.: claude-opus-5-5)
    esforco: str = "medium"
    motor_claude: str = "assinatura"  # "assinatura" (CLAUDE_CODE_OAUTH_TOKEN) ou "api" (ANTHROPIC_API_KEY)

    # WhatsApp pelo OpenWA (motor Baileys, número do próprio perito; não é a API oficial)
    whatsapp_url: str = "http://openwa:2785/api"
    whatsapp_api_key: str = ""
    whatsapp_sessao: str = ""
    whatsapp_webhook_token: str = ""     # vai no caminho /webhook/wa/<token>
    whatsapp_numero: str = ""            # o número do perito, só dígitos com DDI (55...)
    sandbox: frozenset = frozenset()     # se preenchido, o agente SÓ atende estes números (fase de teste)
    bloqueados: frozenset = frozenset()  # números que o agente nunca atende
    contatos_salvos: bool = False        # False: não fala com quem está na agenda do celular

    # Pix copia e cola (opcional): o agente manda o código dos serviços com "Pix:" em servicos.md
    pix_chave: str = ""
    pix_nome: str = ""
    pix_cidade: str = ""

    # Comportamento
    espera_agrupar_s: float = 8.0
    pausa_humano_horas: float = 24.0
    max_msgs_sessao: int = 40           # mensagens do agente por conversa em 24 h (trava anti-robô)
    retomada_1_min: float = 30          # 1ª retomada, minutos depois da mensagem sem resposta
    retomada_2_min: float = 120         # 2ª retomada ("ficou alguma dúvida?")
    followup_hora_inicio: int = 8
    followup_hora_fim: int = 21
    fuso: str = "America/Sao_Paulo"
    banco: Path = field(default_factory=lambda: RAIZ / "dados" / "agente.sqlite3")
    pasta_conhecimento: Path = field(default_factory=lambda: RAIZ / "conhecimento")

    # Avisos (opcional)
    telegram_token: str = ""
    telegram_chat_id: str = ""
    modo_teste: bool = False  # True: não envia nada ao WhatsApp, só registra no log

    @classmethod
    def do_ambiente(cls) -> "Config":
        _carregar_dotenv(RAIZ / ".env")
        e = os.environ.get
        return cls(
            dono=e("DONO_NOME", "o perito"),
            modelo=e("MODELO", "sonnet"),
            esforco=e("ESFORCO", "medium"),
            motor_claude=e("CLAUDE_MOTOR") or ("api" if e("ANTHROPIC_API_KEY") and not e("CLAUDE_CODE_OAUTH_TOKEN")
                                               else "assinatura"),
            whatsapp_url=e("WHATSAPP_URL", "http://openwa:2785/api"),
            whatsapp_api_key=e("WHATSAPP_API_KEY", ""),
            whatsapp_sessao=e("WHATSAPP_SESSAO", ""),
            whatsapp_webhook_token=e("WHATSAPP_WEBHOOK_TOKEN", ""),
            whatsapp_numero=e("WHATSAPP_NUMERO", ""),
            sandbox=_fones(e("SANDBOX", "")),
            bloqueados=_fones(e("BLOQUEADOS", "")),
            contatos_salvos=_sim(e("CONTATOS_SALVOS", "0")),
            pix_chave=e("PIX_CHAVE", ""),
            pix_nome=e("PIX_NOME", ""),
            pix_cidade=e("PIX_CIDADE", ""),
            espera_agrupar_s=float(e("ESPERA_AGRUPAR_S", "8")),
            pausa_humano_horas=float(e("PAUSA_HUMANO_HORAS", "24")),
            max_msgs_sessao=int(e("MAX_MSGS_SESSAO", "40")),
            retomada_1_min=float(e("RETOMADA_1_MIN", "30")),
            retomada_2_min=float(e("RETOMADA_2_MIN", "120")),
            fuso=e("FUSO", "America/Sao_Paulo"),
            banco=Path(e("BANCO", str(RAIZ / "dados" / "agente.sqlite3"))),
            pasta_conhecimento=Path(e("PASTA_CONHECIMENTO", str(RAIZ / "conhecimento"))),
            telegram_token=e("TELEGRAM_TOKEN", ""),
            telegram_chat_id=e("TELEGRAM_CHAT_ID", ""),
            modo_teste=_sim(e("MODO_TESTE", "0")),
        )
