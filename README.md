# Agente de WhatsApp do Perito

Um assistente que atende o WhatsApp profissional do perito 24 horas por dia. Ele
conversa com quem chega (advogado, parte, empresa), entende o caso, explica o serviço
em linguagem simples, qualifica (tipo de perícia, área, prazo, comarca, se é judicial,
extrajudicial ou assistência técnica) e conduz até a proposta de honorários ou o Pix.
Cada cliente ganha uma ficha com o histórico da conversa, e o agente retoma quem sumiu.

Material do curso de **Edilson Aguiais** para peritos judiciais e assistentes técnicos.

> Você não precisa saber programar. Precisa de: um servidor Linux (VPS), um número de
> WhatsApp só do trabalho, uma assinatura do Claude (Pro ou Max) e 1 hora.

---

## O que ele faz e o que ele nunca faz

**Faz**
- Responde em segundos, no seu tom de voz, uma mensagem por vez.
- Junta as mensagens seguidas do cliente e responde uma vez só.
- Explica o serviço certo para o caso, com valor (ou faixa) e prazo que você definiu.
- Manda o Pix copia e cola com o valor exato, só para serviços de preço fechado.
- Guarda a ficha de cada cliente: quem é, natureza, perícia, comarca, prazo, serviço, estágio.
- Retoma quem parou de responder: uma vez depois de 30 min e outra depois de 2 h, só em
  horário comercial.
- Avisa você no Telegram quando a conversa precisa de você: documento chegou, prazo
  urgente, alerta ético, pedido de apagar dados.
- Sai da conversa sozinho por 24 h quando você responde pelo celular.

**Nunca faz**
- Prometer resultado do processo ou laudo favorável.
- Aceitar trabalho com risco de impedimento ou suspeição (avisa você).
- Mandar link que não esteja nos seus arquivos de conhecimento.
- Falar com quem está na sua agenda do celular, em grupos ou em status.
- Disparar mensagem em massa ou adicionar gente em grupo.
- Deixar o cliente "aguardando o perito": ele resolve ou mostra o próximo passo.

---

## Antes de começar: cuidados com o WhatsApp

O agente usa o WhatsApp Web (programa OpenWA, motor Baileys), não a API oficial da Meta.
Funciona bem para **atender quem te procura**. Usado errado, o número é banido.

- Use um número **só do trabalho** (de preferência WhatsApp Business), nunca o pessoal.
- **Nunca** faça disparo em massa, lista de transmissão por robô ou "aquecimento".
- **Nunca** adicione pessoas em grupo pelo robô. Isso derruba a sessão na hora.
- O agente só responde quem escreveu primeiro. Mantenha assim.
- Número novo: use alguns dias pelo celular, normalmente, antes de ligar o agente.

---

## Instalação (1 comando)

### 1. Prepare no seu computador
1. Instale o Claude Code (claude.ai/code) e faça login com a sua assinatura.
2. No terminal do seu computador, rode `claude setup-token`. Guarde o token que começa com
   `sk-ant-oat`. Ele é a chave do agente; não mande para ninguém.
3. (Opcional) No Telegram, fale com o @BotFather, crie um bot e guarde o token.

### 2. Contrate uma VPS
Ubuntu 24.04, 2 GB de RAM, 1 vCPU (qualquer provedor). Anote o IP e a senha de root.

> **Acesso:** o repositório é privado e exclusivo para alunos da Mentoria Águias da Perícia e do
> Águias ONE. O GitHub pede seu usuário e um token de acesso no `git clone`; o seu usuário precisa
> ter sido liberado pela equipe do curso.

### Sem VPS: rodar no seu próprio computador
Dá, e funciona igual: o WhatsApp do agente se conecta para fora, então não precisa de endereço
público nem de porta aberta. O preço é este: **o computador fica ligado 24 horas, sem dormir.**
- Windows: instale o Docker Desktop (com WSL 2) e o Ubuntu pela Microsoft Store; abra o Ubuntu e
  rode os mesmos dois comandos do passo 3 (sem `ssh`). Mac: Docker Desktop e o Terminal.
- Desligue a suspensão e a hibernação (Windows: Configurações > Sistema > Energia; Mac: Ajustes >
  Bateria > impedir repouso) e deixe no carregador.
- Mensagens que chegarem com o computador desligado **não são respondidas** quando ele volta: o
  agente ignora o que tem mais de 5 minutos, para não responder conversa velha fora de contexto.
  Atualização do Windows que reinicia de madrugada e queda de energia derrubam o atendimento.
- Recomendação do curso: comece no computador para testar e aprender; quando o agente estiver
  vendendo, passe para uma VPS (a partir de uns R$ 30/mês), que não dorme nem atualiza sozinha.

### 3. Instale
Entre no servidor (`ssh root@SEU_IP`) e rode:

```bash
git clone https://github.com/edilsonaguiais/agente-whatsapp-perito.git agente-whatsapp-perito
sudo bash agente-whatsapp-perito/instalar.sh
```

O instalador:
1. instala o Docker;
2. copia o agente para `/opt/agente-perito` e cria o comando `agente-perito`;
3. pergunta seu nome, o token do Claude, o número do WhatsApp, os números de teste, o
   Telegram e a chave Pix (os dois últimos são opcionais) e confere cada um na hora;
4. pergunta de onde vem o seu conhecimento: modelo em branco, seu GitHub ou o exemplo do curso;
5. sobe o OpenWA e o agente e mostra o **QR Code**.

No celular do trabalho: WhatsApp > Configurações > Aparelhos conectados > Conectar
aparelho, e leia o QR que apareceu no terminal.

**Parear pelo painel** (se o QR não aparecer no terminal): no SEU computador rode
`ssh -L 2785:127.0.0.1:2785 root@SEU_IP`, abra `http://localhost:2785` no navegador,
entre com a chave `WHATSAPP_API_KEY` do arquivo `/opt/agente-perito/.env` e leia o QR da sessão.

---

## Preencha o seu conhecimento

O agente só sabe o que está na pasta `/opt/agente-perito/conhecimento/`:

| Arquivo | O que vai nele | Obrigatório |
|---|---|---|
| `servicos.md` | Seus serviços: o que é, para quem, quando cabe, prazo, honorários, documentos, como contratar | sim |
| `tom_de_voz.md` | Como você escreve: tratamento, expressões, o que nunca diz | sim |
| `metodo_vendas.md` | O método de venda do curso. **Já vem pronto** | sim |
| `icp.md` | Quem é seu cliente ideal e que serviço serve para cada um | não |
| `faq.md` | Perguntas frequentes com a sua resposta | não |
| `objecoes.md` | Objeções comuns e como você responde | não |

Edite com `agente-perito editar servicos.md` (o agente reinicia sozinho ao salvar).
Troque tudo entre `[COLCHETES]`. O `agente-perito verificar` mostra o que falta.

**Exemplo pronto:** `exemplos/perito-contabil-bancario/` traz uma perita contábil
fictícia (revisão de contrato bancário, assistência técnica em revisional, cálculo
trabalhista). Serve para estudar. Os valores são ilustrativos: troque tudo antes de abrir.

**Pix:** no `servicos.md`, um serviço de preço fechado leva a linha `- Pix: 350,00`. Quando o
cliente aceita, o agente manda o Pix copia e cola desse valor, com a chave que você deu na
instalação. Serviço com faixa de preço não leva Pix: o agente pede os documentos e diz
quando sai a proposta.

### Conhecimento no GitHub (opcional)
Se você prefere guardar os arquivos num repositório GitHub seu (dá para editar pelo site
e ter histórico de versões):

```bash
agente-perito github https://github.com/SEU_USUARIO/SEU_REPOSITORIO
agente-perito atualizar      # depois de cada mudança no GitHub
```

Os `.md` podem ficar na raiz ou numa pasta `conhecimento/`. Todo `.md` entra no agente
(menos README). Repositório privado pede um token do GitHub **só de leitura**
(Settings > Developer settings > Fine-grained tokens > Contents: Read). A versão anterior
de cada arquivo substituído fica em `dados/conhecimento-anterior/`.

---

## Teste antes de abrir

1. `agente-perito testar`: você faz o papel do cliente no terminal, sem WhatsApp. Teste um
   advogado com prazo, uma parte sem advogado, alguém pedindo "laudo favorável", alguém
   que diz que você já é o perito nomeado no processo dele.
2. Mande mensagem pelo WhatsApp a partir de um **número de teste** e acompanhe com
   `agente-perito logs`. Enquanto a lista de teste estiver preenchida, ninguém mais recebe resposta.
3. `agente-perito verificar`: tudo verde? Rode `agente-perito configurar` e deixe a lista
   de teste vazia (digite `-`). Pronto, está aberto.

---

## Comandos do dia a dia

| Comando | Para quê |
|---|---|
| `agente-perito verificar` | checklist do que está funcionando |
| `agente-perito testar` | conversa no terminal, sem WhatsApp |
| `agente-perito logs` | acompanha as conversas ao vivo (`logs openwa` mostra o WhatsApp) |
| `agente-perito editar ARQUIVO` | edita um arquivo de conhecimento |
| `agente-perito leads` | lista quem conversou e grava `dados/leads.csv` (abre no Excel) |
| `agente-perito bloquear NÚMERO` | o agente nunca mais responde esse número (`liberar` desfaz) |
| `agente-perito parear` | mostra o QR de novo (trocou de celular, sessão caiu) |
| `agente-perito configurar` | muda chaves, número de teste, Telegram, Pix |
| `agente-perito reiniciar` / `parar` / `ligar` | controla o serviço |

**Pelo próprio WhatsApp**, na conversa "Conversa comigo" (mensagem para você mesmo):
`#agente bloquear 62999990000`, `#agente liberar 62999990000`, `#agente bloqueados`.

**Você assume quando quiser:** responda o cliente pelo celular e o agente sai da conversa
por 24 h. **Ausência:** no `.env`, `AUSENTE=2026-12-20..2027-01-05` e `AUSENTE_TEXTO=...`;
depois `agente-perito reiniciar`. O agente responde cada pessoa uma vez com esse texto e não vende nesse período.

---

## LGPD e ética do perito

- **Base legal:** quem escreve para o seu WhatsApp profissional pede atendimento; você
  trata nome, telefone e o conteúdo da conversa para responder e prestar o serviço
  (execução de contrato e procedimentos preliminares, art. 7º, V, da LGPD).
- **Onde ficam os dados:** no seu servidor (`/opt/agente-perito/dados/`). O texto da
  conversa passa pela Anthropic (Claude) para gerar a resposta. Diga isso no seu aviso de
  privacidade.
- **Apagar dados:** se o cliente pedir, o agente registra e te avisa. Você atende o pedido.
- **Sigilo:** o agente não comenta caso de ninguém. Não coloque nome de cliente, número de
  processo ou dado pessoal nos arquivos de conhecimento nem no GitHub.
- **Documentos:** o agente não abre anexos. O documento chega no seu WhatsApp e ele te avisa.
- **Ética pericial:** perícia é atividade-meio. O agente não promete resultado, não negocia
  honorário de perito nomeado com a parte e trava (te avisando) quando há sinal de
  impedimento ou suspeição (CPC, arts. 144, 145, 148 e 466). Revise sempre o seu
  `servicos.md` com o código de ética do seu conselho.
- **Responsabilidade:** o agente fala em seu nome. Leia as conversas toda semana
  (`agente-perito leads`) e ajuste o conhecimento.

---

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Não responde ninguém | `agente-perito verificar`. Lista de teste preenchida? O número está na agenda? |
| "WhatsApp: sessão disconnected" | `agente-perito parear` e leia o QR de novo |
| "Claude Code: ... token" | gere outro com `claude setup-token` e rode `agente-perito configurar` |
| Respondeu algo errado | corrija `servicos.md` ou `faq.md`; o agente só sabe o que está lá |
| Mandou link e foi bloqueado | o link não está em nenhum arquivo de conhecimento; acrescente |

---

## Para quem programa

```
agente_perito/
  app.py        orquestra: recebe o aviso do OpenWA, agrupa, chama o cérebro, envia, retoma
  cerebro.py    prompt + Claude (`claude -p` pela assinatura, ou API) com saída em JSON
  memoria.py    SQLite: histórico, ficha, pausa de 24 h, bloqueados
  whatsapp.py   cliente do OpenWA: eco, LID → telefone, 9º dígito, sessão e QR
  pix.py        Pix copia e cola (BR Code) a partir de servicos.md
  github.py     puxa o conhecimento de um repositório GitHub
  __main__.py   comando agente-perito
```

Testes (sem WhatsApp nem Claude reais): `pip install -r requirements.txt pytest && pytest -q`.
