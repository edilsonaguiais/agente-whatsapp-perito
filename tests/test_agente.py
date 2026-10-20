"""Testes sem WhatsApp nem Claude reais: o OpenWA é simulado com httpx.MockTransport e o
cérebro é um falso que devolve respostas prontas."""

import asyncio
import json
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import anthropic
import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

import agente_perito.__main__ as cli
from agente_perito.app import Orquestrador, criar_app, texto_followup
from agente_perito.cerebro import ESQUEMA_RESPOSTA, Cerebro, Decisao, limpar, links_permitidos, montar_sistema
from agente_perito.config import RAIZ, Config
from agente_perito.github import url_valida
from agente_perito.memoria import Memoria
from agente_perito.pix import _crc16, pix_copia_e_cola, servicos_com_pix
from agente_perito.whatsapp import ClienteWhatsApp, dividir, extrair_eventos_wa, fone_normal

DONO = "5562900000000"
CLIENTE = "5511988887777"
CONVERSA = f"wa:{CLIENTE}@c.us"
EXEMPLO = RAIZ / "exemplos" / "perito-contabil-bancario"
MODELO = RAIZ / "modelos" / "conhecimento"


class CerebroFalso:
    def __init__(self, mensagens=("Bom dia, Dr. Me conta o caso: o processo já está correndo?",),
                 transferir=False, ficha=None):
        self.mensagens, self.transferir, self.chamadas = list(mensagens), transferir, []
        self.ficha = ficha or {"servico_recomendado": "indefinido", "estagio": "qualificacao", "pix_servico": ""}

    async def decidir(self, historico, contexto=""):
        self.chamadas.append(historico)
        return Decisao(self.mensagens, dict(self.ficha), self.transferir, "ver" if self.transferir else "")


def montar(cerebro=None, salvo=False, **cfg_extra):
    cfg = Config(whatsapp_url="http://openwa/api", whatsapp_api_key="k", whatsapp_sessao="s1",
                 whatsapp_webhook_token="tok", whatsapp_numero=DONO, espera_agrupar_s=0.05,
                 pasta_conhecimento=EXEMPLO, **cfg_extra)
    enviados = []

    def handler(request: httpx.Request):
        if request.url.path.endswith("send-text"):
            corpo = json.loads(request.content)
            enviados.append(corpo["text"])
            return httpx.Response(200, json={"id": f"bot_{len(enviados)}"})
        if "/contacts/" in request.url.path:
            return httpx.Response(200, json={"id": f"{CLIENTE}@c.us", "pushName": "Carlos Advogado",
                                             "isMyContact": salvo})
        return httpx.Response(200, json={})

    wa = ClienteWhatsApp("http://openwa/api", "k", "s1", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return cfg, Orquestrador(cfg, Memoria(":memory:"), wa, cerebro or CerebroFalso()), enviados


def aviso(texto, mid, eco=False, de=CLIENTE, idade=0):
    msg = {"id": mid, "body": texto, "type": "chat", "timestamp": int(time.time() - idade)}
    if eco:
        msg.update({"fromMe": True, "from": f"{DONO}@c.us", "to": f"{de}@c.us"})
    else:
        msg.update({"from": f"{de}@c.us", "to": f"{DONO}@c.us"})
    return {"event": "message.sent" if eco else "message.received", "data": msg}


def receber(orq, *avisos):
    for a in avisos:
        for ev in extrair_eventos_wa(a):
            orq.receber(ev)


# --- fluxo principal ------------------------------------------------------
def test_agrupa_mensagens_e_responde_uma_vez():
    async def cenario():
        _, orq, enviados = montar()
        receber(orq, aviso("bom dia", "m1"), aviso("sou advogado", "m2"), aviso("tenho uma revisional", "m3"))
        await asyncio.sleep(0.3)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(orq.cerebro.chamadas) == 1
    assert orq.cerebro.chamadas[0][-1]["content"] == "bom dia\nsou advogado\ntenho uma revisional"
    assert len(enviados) == 1
    assert orq.memoria.lead(CONVERSA)["nome"] == "Carlos Advogado"


def test_aviso_repetido_nao_gera_segunda_resposta():
    async def cenario():
        _, orq, enviados = montar()
        receber(orq, aviso("oi", "dup"), aviso("oi", "dup"))
        await asyncio.sleep(0.2)
        return enviados

    assert len(asyncio.run(cenario())) == 1


def test_eco_do_agente_ignorado_e_resposta_do_perito_pausa():
    async def cenario():
        _, orq, enviados = montar()
        receber(orq, aviso("oi", "m1"))
        await asyncio.sleep(0.2)
        receber(orq, aviso(enviados[0], "bot_1", eco=True))      # eco do próprio agente
        assert not orq.memoria.esta_pausado(CONVERSA)
        receber(orq, aviso("Oi Carlos, aqui é a perita.", "humano1", eco=True))  # perito pelo celular
        assert orq.memoria.esta_pausado(CONVERSA)
        receber(orq, aviso("que bom!", "m2"))
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(enviados) == 1
    assert "[resposta enviada manualmente pelo perito]" in orq.memoria.historico(CONVERSA)[1]["content"]


def test_grupo_status_e_historico_antigo_sao_ignorados():
    grupo = aviso("alguém indica perito?", "g1")
    grupo["data"]["from"] = "120363000000000000@g.us"
    assert extrair_eventos_wa(grupo) == []
    assert extrair_eventos_wa(aviso("oi", "velha", idade=3600)) == []
    status = aviso("story", "st")
    status["data"]["from"] = "status@broadcast"
    assert extrair_eventos_wa(status) == []


def test_anexo_vira_descricao():
    a = aviso("", "doc1")
    a["data"].update({"type": "document", "caption": "contrato.pdf"})
    assert extrair_eventos_wa(a)[0].texto == "[o cliente enviou um documento] contrato.pdf"


def test_quem_esta_na_agenda_nao_e_atendido():
    async def cenario():
        _, orq, enviados = montar(salvo=True)
        receber(orq, aviso("oi, é a sua tia", "m1"))
        await asyncio.sleep(0.2)
        return enviados

    assert asyncio.run(cenario()) == []


def test_sandbox_e_bloqueados():
    async def cenario(**extra):
        _, orq, enviados = montar(**extra)
        receber(orq, aviso("oi", "m1"))
        await asyncio.sleep(0.2)
        return enviados

    assert asyncio.run(cenario(sandbox=frozenset({"5562911112222"}))) == []
    assert len(asyncio.run(cenario(sandbox=frozenset({CLIENTE})))) == 1
    assert asyncio.run(cenario(bloqueados=frozenset({CLIENTE}))) == []


def test_comando_bloquear_no_conversa_comigo():
    async def cenario():
        _, orq, enviados = montar()
        receber(orq, aviso(f"#agente bloquear {CLIENTE}", "cmd1", eco=True, de=DONO))
        await asyncio.sleep(0.1)
        receber(orq, aviso("oi", "m1"))
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados and enviados[0].startswith("#agente Bloqueado")  # só a confirmação do comando
    assert len(enviados) == 1


def test_transferencia_so_avisa_e_agente_continua():
    async def cenario():
        _, orq, enviados = montar(CerebroFalso(["Recebi o contrato. A proposta sai em até 1 dia útil."], transferir=True))
        receber(orq, aviso("[o cliente enviou um documento]", "m1"))
        await asyncio.sleep(0.2)
        receber(orq, aviso("e aí?", "m2"))
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(enviados) == 2  # o agente sempre assume
    assert orq.memoria.lead(CONVERSA)["transferido"] == 0


def test_pix_vai_depois_do_sim_com_valor_do_servicos_md():
    ficha = {"servico_recomendado": "Análise prévia de contrato bancário", "estagio": "fechamento",
             "pix_servico": "Análise prévia de contrato bancário"}

    async def cenario():
        _, orq, enviados = montar(CerebroFalso(["Fechado. Segue o Pix."], ficha=ficha),
                                  pix_chave="perita@exemplo.com", pix_nome="Marina Exemplo", pix_cidade="Goiania")
        receber(orq, aviso("pode mandar o pix", "m1"))
        await asyncio.sleep(0.2)
        return enviados

    enviados = asyncio.run(cenario())
    assert len(enviados) == 2
    assert "R$ 890,00" in enviados[1] and "br.gov.bcb.pix" in enviados[1]


def test_pix_de_servico_sem_preco_fechado_nao_e_enviado():
    ficha = {"pix_servico": "Assistência técnica em ação revisional", "estagio": "fechamento"}

    async def cenario():
        _, orq, enviados = montar(CerebroFalso(["A proposta sai amanhã."], ficha=ficha), pix_chave="perita@exemplo.com")
        receber(orq, aviso("quero contratar", "m1"))
        await asyncio.sleep(0.2)
        return enviados

    assert asyncio.run(cenario()) == ["A proposta sai amanhã."]


def test_teto_de_mensagens_para_sem_mandar_aguarde():
    async def cenario():
        _, orq, enviados = montar(max_msgs_sessao=1)
        for i in range(2):
            receber(orq, aviso(f"msg {i}", f"m{i}"))
            await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert len(enviados) == 1
    assert orq.memoria.lead(CONVERSA)["transferido"] == 1


def test_erro_no_claude_tenta_de_novo_sem_largar_o_cliente():
    class Quebrado:
        async def decidir(self, historico, contexto=""):
            raise RuntimeError("Claude fora do ar")

    async def cenario():
        _, orq, enviados = montar(Quebrado())
        receber(orq, aviso("oi", "m1"))
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados == [] and orq.memoria.lead(CONVERSA)["transferido"] == 0


def test_modo_ausente_responde_uma_vez_sem_claude(monkeypatch):
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")
    monkeypatch.setenv("AUSENTE", f"{hoje}..{hoje}")
    monkeypatch.setenv("AUSENTE_TEXTO", "Estou em audiência hoje.")

    async def cenario():
        _, orq, enviados = montar()
        receber(orq, aviso("oi", "m1"))
        await asyncio.sleep(4.5)
        receber(orq, aviso("alô?", "m2"))
        await asyncio.sleep(0.2)
        return orq, enviados

    orq, enviados = asyncio.run(cenario())
    assert enviados == ["Estou em audiência hoje."]
    assert orq.cerebro.chamadas == []


# --- retomadas ----------------------------------------------------------------
def _parada(t_cliente, **ficha):
    async def preparar():
        _, orq, enviados = montar()
        receber(orq, aviso("quero saber da análise do contrato", "m1"))
        await asyncio.sleep(0.2)
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE papel = 'user'", (t_cliente,))
        orq.memoria._db.execute("UPDATE mensagens SET criado_em = ? WHERE papel = 'assistant'", (t_cliente + 60,))
        orq.memoria.atualizar_lead(CONVERSA, ficha={"servico_recomendado": "Análise prévia", "estagio": "apresentacao", **ficha})
        return orq, enviados
    return preparar


def test_retomadas_30_min_e_2_h_no_maximo_duas():
    t = datetime(2026, 10, 14, 14, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()

    async def cenario():
        orq, enviados = await _parada(t)()
        r = [await orq.verificar_followups(t + 60 + m * 60) for m in (10, 31, 40, 121, 125, 300)]
        return r, enviados

    r, enviados = asyncio.run(cenario())
    assert r == [0, 1, 0, 1, 0, 0]
    assert len(enviados) == 3


def test_retomada_respeita_noite_e_quem_nao_e_cliente():
    noite = datetime(2026, 10, 14, 23, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()
    tarde = datetime(2026, 10, 14, 14, 0, tzinfo=ZoneInfo("America/Sao_Paulo")).timestamp()

    async def cenario():
        orq, _ = await _parada(noite)()
        a = await orq.verificar_followups(noite + 60 + 31 * 60)
        orq2, _ = await _parada(tarde, estagio="relacionamento")()
        b = await orq2.verificar_followups(tarde + 60 + 31 * 60)
        return a, b

    assert asyncio.run(cenario()) == (0, 0)


def test_texto_followup_padrao():
    assert texto_followup(None, "") == "Retomo nossa conversa. Ficou algum ponto sem resposta para você decidir?"
    assert texto_followup("Carlos Silva", "os quesitos.").startswith("Carlos, retomo nossa conversa sobre os quesitos.")


# --- cérebro e conhecimento -------------------------------------------------------
def _sem_propriedades_soltas(no):
    if isinstance(no, dict):
        if no.get("type") == "object":
            assert no.get("additionalProperties") is False
            assert set(no["required"]) == set(no["properties"])
        for v in no.values():
            _sem_propriedades_soltas(v)


def test_esquema_valido_para_saida_estruturada():
    _sem_propriedades_soltas(ESQUEMA_RESPOSTA)


def test_prompt_tem_conhecimento_e_regras_eticas():
    sistema = montar_sistema(EXEMPLO, "Dra. Marina Exemplo")
    for marca in ("<servicos>", "<tom_de_voz>", "<metodo_vendas>", "<icp>", "<faq>", "<objecoes>",
                  "Impedimento e suspeição", "Nunca prometa resultado", "Dra. Marina Exemplo"):
        assert marca in sistema
    assert "{dono}" not in sistema


def test_extra_do_github_entra_no_prompt(tmp_path):
    for p in EXEMPLO.glob("*.md"):
        (tmp_path / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "jurisprudencia.md").write_text("Tema 27 do STJ.", encoding="utf-8")
    (tmp_path / "README.md").write_text("não entra", encoding="utf-8")
    sistema = montar_sistema(tmp_path)
    assert '<extra arquivo="jurisprudencia.md">' in sistema and "não entra" not in sistema


def test_falta_arquivo_obrigatorio_da_erro_claro(tmp_path):
    with pytest.raises(FileNotFoundError, match="servicos.md"):
        montar_sistema(tmp_path)


def _cliente_claude(mensagens, **extra):
    corpo = {"mensagens": mensagens,
             "bant": {k: {"status": "desconhecido", "evidencia": ""} for k in ("budget", "authority", "need", "timing")},
             "tipo_cliente": "advogado", "natureza": "assistencia_tecnica", "tipo_pericia": "revisional",
             "area": "bancário", "comarca": "", "prazo": "", "servico_recomendado": "indefinido",
             "estagio": "qualificacao", "alerta_etico": "", "pix_servico": "", "transferir_para_humano": False,
             "motivo_transferencia": "", "resumo_lead": "", "dor_resumida": "", **extra}

    def handler(request):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(corpo)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
    return anthropic.AsyncAnthropic(api_key="x", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_link_fora_do_conhecimento_e_bloqueado():
    cerebro = Cerebro("sistema", cliente=_cliente_claude(["Pague aqui: https://golpe.example/pix"]),
                      links=links_permitidos(EXEMPLO), motor="api")
    d = asyncio.run(cerebro.decidir([{"role": "user", "content": "manda o link"}]))
    assert d.mensagens == [] and d.transferir


def test_alerta_etico_sempre_avisa_o_perito():
    cerebro = Cerebro("sistema", cliente=_cliente_claude(
        ["Como a Dra. já foi nomeada pelo juiz nesse processo, ela não pode atuar para uma das partes."],
        alerta_etico="perita já nomeada no mesmo processo"), links=set(), motor="api")
    d = asyncio.run(cerebro.decidir([{"role": "user", "content": "quero que ela seja minha assistente"}]))
    assert d.transferir and "alerta ético" in d.motivo and d.mensagens


def test_tira_travessao():
    assert limpar("Não é opinião — é cálculo") == "Não é opinião, é cálculo"


# --- Pix, WhatsApp, GitHub e CLI ----------------------------------------------------
def test_pix_copia_e_cola_tem_crc_valido():
    codigo = pix_copia_e_cola("perita@exemplo.com", Decimal("350.00"), "Marina Exemplo", "Goiânia")
    assert codigo.startswith("000201") and "5406350.00" in codigo and "6007GOIANIA" in codigo
    assert _crc16(codigo[:-4]) == codigo[-4:]


def test_servicos_com_pix_le_so_preco_fechado():
    pix = servicos_com_pix(EXEMPLO)
    assert pix == {"Consulta técnica inicial": Decimal("350.00"),
                   "Análise prévia de contrato bancário": Decimal("890.00")}
    assert servicos_com_pix(MODELO) == {}  # modelo em branco não tem valor


def test_nono_digito_e_dividir():
    assert fone_normal("+55 (62) 99999-0000") == fone_normal("556299990000")
    partes = dividir("perícia " * 800)
    assert all(len(p.encode()) <= 3000 for p in partes)


def test_url_do_github():
    assert url_valida("https://github.com/perito/conhecimento")
    assert url_valida("https://github.com/perito/conhecimento.git")
    assert not url_valida("https://exemplo.com/perito/conhecimento")
    assert not url_valida("https://github.com/perito/conhecimento; rm -rf /")


def test_webhook_exige_token():
    cfg, orq, _ = montar()
    cliente = TestClient(criar_app(cfg, orq, followup=False))
    assert cliente.post("/webhook/wa/errado", json={}).status_code == 401
    assert cliente.post("/webhook/wa/tok", json={"event": "session.status"}).status_code == 200
    assert cliente.get("/saude").json()["ok"] is True


def test_env_ida_e_volta(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ENV", tmp_path / ".env")
    cli.gravar_env({"DONO_NOME": "Maria Silva", "WHATSAPP_NUMERO": "5562900000000", "EXTRA": "x"})
    lido = cli.ler_env()
    assert lido["DONO_NOME"] == "Maria Silva" and lido["MODELO"] == "sonnet" and lido["EXTRA"] == "x"


def test_numero_valido():
    assert cli.numero_valido("(62) 99999-0000") == "5562999990000"
    assert cli.numero_valido("123") == ""


def test_modelo_tem_pendencias_e_exemplo_nao():
    assert cli.placeholders(MODELO)
    assert cli.placeholders(EXEMPLO) == []


def test_preparar_conhecimento_copia_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONHECIMENTO", tmp_path / "conhecimento")
    monkeypatch.setattr("builtins.input", lambda _: "1")
    cli.preparar_conhecimento({})
    for nome in cli.ARQUIVOS:
        assert (tmp_path / "conhecimento" / nome).exists()


def test_bloquear_pelo_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("BANCO", str(tmp_path / "a.sqlite3"))
    assert cli.bloquear("bloquear", ["(11) 98888-7777"]) == 0
    assert fone_normal(CLIENTE) in Memoria(tmp_path / "a.sqlite3").ajuste("bloqueados_extra")
