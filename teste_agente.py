"""Testes do laço do agente com um Zernio de mentira (sem internet, sem IA). Rode: python teste_agente.py"""
import datetime as dt
import shutil
import tempfile
import time
from pathlib import Path

import agente

AGORA = time.time()


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


class ZernioFalso:
    def __init__(self):
        self.msgs = {"c1": [], "c2": []}
        self.enviadas = []
        self.marca = 0

    def chega(self, conv, texto, saida=False, quando=None):
        self.marca += 1
        self.msgs[conv].append({"id": f"m{self.marca}", "direction": "outgoing" if saida else "incoming",
                                "message": texto, "createdAt": iso(quando or time.time() - 30)})

    def __call__(self, metodo, caminho, corpo=None, chave=None):
        if caminho.startswith("/v1/inbox/conversations?"):
            return {"data": [{"id": c, "participantName": nome, "participantUsername": nome.lower(),
                              "lastMessageAt": str(len(self.msgs[c]))}
                             for c, nome in (("c1", "Paulo"), ("c2", "Tia"))]}
        conv = caminho.split("/")[4]
        if metodo == "POST":
            self.enviadas.append((conv, corpo["message"]))
            self.chega(conv, corpo["message"], saida=True, quando=time.time())
            return {}
        return {"messages": list(reversed(self.msgs[conv]))}


def preparar():
    pasta = Path(tempfile.mkdtemp())
    agente.BANCO = pasta / "agente.db"
    agente.AVISOS = pasta / "avisos.txt"
    agente.CONHECIMENTO = pasta / "conhecimento"
    shutil.copytree(Path(__file__).parent / "exemplo", agente.CONHECIMENTO)
    shutil.copy(Path(__file__).parent / "modelos" / "metodo_vendas.md", agente.CONHECIMENTO)
    z = ZernioFalso()
    agente.zernio = z
    respostas = []

    def pensar(conversa, contexto):
        respostas.append(conversa)
        return {"mensagem": "Laudo contra é o momento decisivo.\nQual é o prazo?", "avisar_perito": False,
                "motivo": "", "estagio": "conducao", "servico": "nenhum", "resumo": "advogado"}
    agente.pensar = pensar
    return z, agente.banco(), respostas


CONTA = {"_id": "a1", "platform": "instagram"}


def test_responde_uma_vez_e_reconhece_a_propria_mensagem():
    z, db, respostas = preparar()
    agente.os.environ["BLOQUEADOS"] = "tia"
    z.chega("c1", "O laudo saiu contra o meu cliente.")
    z.chega("c2", "Oi sobrinho!")
    agente.ciclo(db, CONTA, AGORA)
    agente.ciclo(db, CONTA, AGORA)  # a resposta já está lá: não responde de novo
    assert z.enviadas == [("c1", "Laudo contra é o momento decisivo.\nQual é o prazo?")]  # tia bloqueada
    papeis = [p for p, _ in agente.historico(db, "c1")]
    assert papeis == ["user", "assistant"], papeis
    del agente.os.environ["BLOQUEADOS"]


def test_resposta_do_perito_pausa_24h():
    z, db, _ = preparar()
    z.chega("c1", "Quanto custa o parecer?", quando=time.time() - 60)
    z.chega("c1", "Dr. Paulo, te ligo agora.", saida=True, quando=time.time() - 30)  # o perito pelo celular
    z.chega("c1", "Ok, aguardo.", quando=time.time() - 20)
    agente.ciclo(db, CONTA, AGORA)
    assert z.enviadas == []
    assert agente.lead(db, "c1")["pausado_ate"] > time.time() + 80000


def test_modo_teste_so_atende_quem_esta_na_lista():
    z, db, _ = preparar()
    agente.os.environ["TESTE"] = "@tia"
    z.chega("c1", "Oi")
    z.chega("c2", "Oi")
    agente.ciclo(db, CONTA, AGORA)
    assert [c for c, _ in z.enviadas] == ["c2"]
    del agente.os.environ["TESTE"]


def test_historico_antigo_nao_e_respondido():
    z, db, _ = preparar()
    z.chega("c1", "mensagem de ontem", quando=AGORA - 86400)
    agente.ciclo(db, CONTA, AGORA)
    assert z.enviadas == []


def test_link_fora_do_conhecimento_nao_sai():
    preparar()
    ok, aviso = agente.revisar({"mensagem": "Pague aqui: https://golpe.exemplo/pix", "avisar_perito": False})
    assert ok == "" and "golpe" in aviso
    ok, aviso = agente.revisar({"mensagem": "Link: https://pagamento.exemplo.com.br/parecer. Fechamos?",
                                "avisar_perito": False})
    assert ok.startswith("Link") and aviso == ""


def test_retomada_uma_vez_depois_de_2h():
    z, db, respostas = preparar()
    z.chega("c1", "Quero o parecer.", quando=time.time() - 9000)
    agente.ciclo(db, CONTA, time.time() - 9100)  # agente responde (como se tivesse ligado antes)
    agente.ciclo(db, CONTA, time.time() - 9100)  # e registra a própria resposta
    db.execute("UPDATE msgs SET quando=? WHERE papel='assistant'", (time.time() - 8000,))
    db.commit()
    hora = agente.dt.datetime.now().hour
    agente.ciclo(db, CONTA, AGORA)
    agente.ciclo(db, CONTA, AGORA)
    esperado = 2 if 8 <= hora < 21 else 1
    assert len(z.enviadas) == esperado, z.enviadas


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_"):
            f()
            print("ok", nome)
