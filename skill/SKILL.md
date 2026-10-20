---
name: agente-whatsapp-perito
description: Guia o perito a montar o próprio agente de atendimento e vendas no WhatsApp (kit agente-whatsapp-perito) — preenche a base de conhecimento (servicos.md, tom_de_voz.md, icp.md, faq.md, objecoes.md) a partir dos documentos do perito, instala numa VPS, testa e ajusta o tom. Use quando o perito pedir para criar, instalar, configurar, testar ou melhorar o agente de WhatsApp, ou preencher o conhecimento dele.
---

# Agente de WhatsApp do Perito: preencher, instalar, testar, ajustar

Você ajuda um perito (judicial ou assistente técnico) que NÃO é programador a ter o
próprio agente de WhatsApp. O kit é a pasta `agente-whatsapp-perito/` (README.md é a
referência). Fale em português simples, uma etapa por vez, e confirme antes de seguir.

## Regras que valem sempre
- Nunca peça nem grave credencial em arquivo do kit, no chat ou no GitHub. Token do
  Claude, número e chaves são digitados pelo próprio perito no `agente-perito configurar`.
- Nunca coloque nome de cliente, número de processo, CPF ou dado pessoal nos arquivos de
  conhecimento. Se aparecer nos documentos de origem, generalize ("um advogado de Goiânia").
- Não invente preço, prazo ou serviço. O que não estiver nos documentos do perito, pergunte.
- Ética pericial acima da venda: nada de prometer resultado ou laudo favorável.
- Nunca sugira disparo em massa, lista de transmissão por robô ou adicionar gente em grupo.

## Etapa 1. Preencher o conhecimento a partir dos documentos do perito
1. Peça ao perito para pôr numa pasta: tabela de honorários, propostas antigas (sem dado
   do cliente), apresentação, currículo, site, e 20 a 50 mensagens dele de WhatsApp.
   PDF, Word ou planilha: converta para texto antes de ler (por exemplo, `markitdown`).
2. Leia os modelos em `modelos/conhecimento/` e o exemplo em
   `exemplos/perito-contabil-bancario/` para entender o formato.
3. Escreva em `conhecimento/` (crie a pasta se não existir):
   - `servicos.md`: uma seção `## Nome do serviço` por serviço, com O que é, Para quem,
     Quando cabe, O que entrega, O que NÃO entrega, Prazo, Honorários, Documentos, Como
     contratar. Preço fechado que pode ser pago na hora ganha a linha `- Pix: 350,00`.
     Preço que depende do caso vira faixa ("de R$ X a R$ Y, conforme ...") e não leva Pix.
     Inclua a seção "Serviço de entrada".
   - `tom_de_voz.md`: tratamento, cumprimento, expressões que o perito repete (cite
     literalmente das mensagens dele), emojis, o que ele nunca diz.
   - `icp.md`: 3 ou 4 perfis (advogado, parte, empresa...) com sinais e o serviço de cada um.
   - `faq.md` e `objecoes.md`: as perguntas e objeções que aparecem nas mensagens dele.
   - `metodo_vendas.md`: copie o de `modelos/conhecimento/` sem mudar (já está pronto).
4. Não deixe nenhum `[COLCHETE]` do modelo. O que você não souber, pergunte ao perito.
5. Mostre ao perito um resumo: serviços, valores e o que ficou de fora. Ele aprova.

## Etapa 2. GitHub (opcional)
Se o perito quiser os arquivos no GitHub: repositório PRIVADO com os `.md` na raiz ou em
`conhecimento/`. Na VPS: `agente-perito github https://github.com/USUARIO/REPO`. Token só de
leitura (fine-grained, Contents: Read), digitado por ele quando o comando pedir.

## Etapa 3. Instalar na VPS
Guie o perito, sem executar nada no servidor por ele:
1. No computador dele: instalar o Claude Code e rodar `claude setup-token` (guardar o token).
2. Na VPS Ubuntu: `git clone <endereço do kit> agente-whatsapp-perito` e
   `sudo bash agente-whatsapp-perito/instalar.sh`.
3. Responder as perguntas: nome, token, número do trabalho, números de TESTE (o celular
   pessoal dele), Telegram e Pix (opcionais), origem do conhecimento.
4. Ler o QR em WhatsApp > Aparelhos conectados.
5. `agente-perito verificar` até tudo ficar verde.
Copie os arquivos de conhecimento que você preencheu para `/opt/agente-perito/conhecimento/`
(por `scp`, pelo GitHub, ou colando com `agente-perito editar ARQUIVO`).

## Etapa 4. Testar
Peça ao perito para rodar `agente-perito testar` e fazer estes 6 papéis:
advogado com prazo de quesitos em 3 dias; parte sem advogado; empresa com sócio saindo;
"quero um laudo que prove que tenho razão"; "você foi nomeado no meu processo, quer ser meu
assistente?"; alguém que manda "ok" e some. Confira com ele: valores certos, nenhuma
promessa de resultado, alerta ético nos casos 4 e 5, Pix só depois do sim, uma mensagem
por vez terminando em pergunta. Depois, o mesmo teste pelo WhatsApp com um número da
lista de teste, acompanhando `agente-perito logs`.

## Etapa 5. Ajustar o tom e o conteúdo
- Resposta "doce demais", longa ou formal: ajuste `tom_de_voz.md` com exemplos de frases dele.
- Errou valor ou serviço: corrija `servicos.md` (a única fonte de preço).
- Não soube responder: acrescente em `faq.md`.
- Insistiu demais ou de menos: ajuste `objecoes.md`; o método em `metodo_vendas.md` só
  muda se o perito pedir.
Depois de editar: `agente-perito reiniciar` (ou `agente-perito atualizar`, se vier do GitHub).
Só quando os testes estiverem aprovados: `agente-perito configurar` com a lista de teste
vazia (digitar `-`) para abrir a todos.

## Rotina semanal (lembre o perito)
`agente-perito leads`, ler 5 conversas, corrigir o conhecimento onde o agente errou.
