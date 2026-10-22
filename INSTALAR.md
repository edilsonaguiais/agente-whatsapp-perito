# Instalar o agente: roteiro para o Claude ou o Codex conduzir

> Você (Claude ou Codex) está ajudando um assistente técnico que NÃO é programador a ligar
> este agente. Fale em português simples, uma etapa por vez. Rode você mesmo os comandos
> no computador dele, mostre o resultado e só siga quando a etapa estiver ok.
> Nunca peça para ele colar chave ou senha no chat: ele digita direto no
> `python agente.py configurar`. Nunca invente serviço nem valor.

## Etapa 1. Python
Confira com `python --version` (ou `python3 --version`). Precisa ser 3.10 ou mais novo.
Não tem? Windows: `winget install Python.Python.3.12`. Mac: `brew install python`.

## Etapa 2. Zernio (a ponte com o Instagram ou o WhatsApp)
Peça para ele, no navegador:
1. Criar a conta em https://zernio.com e ativar o plano com o **Inbox** (mensagens).
2. Em **Accounts**, conectar o Instagram profissional (ou o WhatsApp) com o login dele.
3. Em **Settings > API Keys**, criar uma chave de leitura e escrita e deixar a tela aberta.

## Etapa 3. Configurar
Rode `python agente.py configurar` e deixe ele responder:
- a chave do Zernio (o programa já confere se funciona e mostra a conta conectada);
- o nome como os advogados conhecem ele;
- o cérebro: `claude` ou `codex` (o que ele já usa);
- a fase de teste: o @ (ou telefone) de uma conta dele, para o agente atender só ela;
- se quer começar pelo exemplo da Dra. Marina só para ver o agente funcionando.

## Etapa 4. Ensinar os serviços dele
Peça os documentos: tabela de honorários, propostas antigas (sem nome de cliente),
apresentação e 20 a 50 mensagens dele para advogados.
1. Leia `modelos/servicos.md` e `exemplo/servicos.md` para entender o formato.
2. Escreva `conhecimento/servicos.md`: um bloco `##` por serviço, do maior para o menor,
   com O que é, O que entrega, Quando cabe, Prazo, Valor e Como contratar (chave Pix ou
   link de pagamento). Só o que está nos documentos; o que faltar, pergunte.
3. Escreva `conhecimento/tom_de_voz.md` com o jeito dele, citando frases reais.
4. Não mexa em `conhecimento/metodo_vendas.md`: é o método de venda do curso.
5. Mostre o resumo dos serviços e valores e peça a aprovação dele.

## Etapa 5. Verificar e testar
1. `python agente.py verificar` até tudo ficar ✅.
2. `python agente.py testar`: peça para ele fazer o papel de advogado em 4 casos:
   "quanto custa um parecer?"; "o perito do juízo fez um laudo ruim e o prazo vence
   sexta"; "tenho uma revisional, ainda não ajuizei"; "vou falar com o meu cliente".
   Confira com ele: oferta até a 3ª mensagem, valor certo, toda mensagem termina em
   pergunta, nada de "aguarde". Ajuste `servicos.md` ou `tom_de_voz.md` se ele não gostar.

## Etapa 6. Ligar
- Windows: dois cliques em `iniciar.bat`. Mac ou Linux: `./iniciar.sh`.
- A janela fica aberta e o computador ligado, sem dormir. Mensagem que chega com o
  computador desligado é respondida quando ele volta (até 10 minutos de atraso).
- Peça para ele mandar uma mensagem da conta de teste e ver a resposta chegar.
- Aprovou? Rode `python agente.py configurar`, apague a fase de teste (deixe vazio) e
  ligue de novo: agora o agente atende todo mundo.

## Depois
- Avisos do agente (documento recebido, pedido fora dos serviços) ficam em
  `dados/avisos.txt`. Para receber no Telegram, ponha `TELEGRAM_TOKEN` e
  `TELEGRAM_CHAT_ID` no arquivo `.env`.
- Quando ele responder um advogado pelo celular, o agente sai daquela conversa por 24 h.
- Família, sócios e amigos: ponha o @ ou telefone em `BLOQUEADOS=` no `.env`.
- Toda semana: ler 5 conversas e corrigir `servicos.md` onde o agente errou.
