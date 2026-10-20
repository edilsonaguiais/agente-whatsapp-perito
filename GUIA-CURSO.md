# Roteiro do curso: Agente de WhatsApp para vender serviços periciais

Autor e professor: Edilson Aguiais. Público: peritos judiciais e assistentes técnicos que
querem atender e vender os próprios serviços pelo WhatsApp, sem saber programar.

Cada módulo tem: objetivo, o que mostrar na tela, entrega do aluno e o erro mais comum.
Duração sugerida entre parênteses.

---

## Módulo 1. Por que ter um agente (15 min)
- **Objetivo:** o aluno entende o que o agente resolve e o que ele não resolve.
- **Mostrar:** uma conversa real anonimizada (ou a do exemplo, em `agente-perito testar`):
  advogado pergunta às 22h, recebe resposta em segundos, sai com proposta.
- **Pontos:** advogado escolhe quem responde primeiro; perito que demora perde o caso;
  o agente qualifica e você só entra na hora do trabalho técnico.
- **O que ele não é:** não é robô de disparo, não substitui o perito, não faz o laudo.
- **Entrega do aluno:** anotar as 5 perguntas que mais recebe no WhatsApp.
- **Erro comum:** achar que o agente vai "gerar clientes". Ele converte quem já chega.

## Módulo 2. Preparar a VPS (20 min)
- **Objetivo:** servidor pronto e acesso por SSH.
- **Mostrar:** contratar uma VPS Ubuntu 24.04 (2 GB), primeiro acesso `ssh root@IP`,
  trocar a senha de root.
- **Entrega:** conseguir entrar no servidor pelo terminal.
- **Erro comum:** escolher Windows Server ou plano de 512 MB.

## Módulo 3. WhatsApp e cuidados com banimento (20 min)
- **Objetivo:** escolher o número certo e nunca perdê-lo.
- **Regras que viram slide:**
  - número só do trabalho (WhatsApp Business), nunca o pessoal;
  - nunca disparo em massa, lista por robô ou "aquecimento";
  - nunca adicionar pessoas em grupo pelo robô: derruba a sessão;
  - o agente só responde quem escreveu primeiro;
  - número novo: alguns dias de uso normal pelo celular antes de ligar o agente.
- **Mostrar:** o agente ignora grupos, status e quem está na agenda (família não recebe venda).
- **Entrega:** número definido e salvo no celular do trabalho.
- **Erro comum:** usar o número pessoal "porque é o que os advogados já têm".

## Módulo 4. Conhecimento: ensinar o agente sobre você (40 min)
- **Objetivo:** `servicos.md`, `tom_de_voz.md`, `icp.md`, `faq.md` e `objecoes.md` preenchidos.
- **Mostrar:** o exemplo `exemplos/perito-contabil-bancario/` lado a lado com o modelo em branco.
- **Com a skill do Claude Code** (`skill/SKILL.md`): o aluno joga na pasta sua tabela de
  honorários, proposta antiga, apresentação e mensagens de WhatsApp (sem dado de cliente),
  e a skill preenche os arquivos. O aluno revisa linha por linha.
- **Regras:** valor só o que você cobra de verdade; faixa quando depende do caso; linha
  `Pix:` só para preço fechado; nada de nome de cliente ou número de processo.
- **Opção GitHub:** criar um repositório privado com os `.md` e ligar com `agente-perito github`.
- **Entrega:** os arquivos preenchidos, sem nenhum `[COLCHETE]`.
- **Erro comum:** colocar "consulte valores" em todo serviço. O agente não tem o que ofertar.

## Módulo 5. Método de vendas aplicado à perícia (40 min)
- **Objetivo:** entender por que o agente conversa do jeito que conversa.
- **Conteúdo** (está em `metodo_vendas.md`):
  - identificar primeiro, no máximo 2 perguntas, oferta na 3ª mensagem;
  - espelho + sentido + pergunta em cada mensagem;
  - no "faz sentido": valor, prazo, documentos e pagamento juntos;
  - objeção: duas tentativas antes de oferecer o serviço de entrada;
  - o agente sempre assume: nunca "aguarde o perito";
  - vender onde a pessoa está: fecha no WhatsApp, sem levar para outro canal.
- **Ética que vem antes da venda:** nunca prometer resultado nem laudo favorável;
  impedimento e suspeição (CPC, arts. 144, 145, 148 e 466); honorário de perito nomeado
  não se negocia com a parte; sigilo; o agente não dá parecer jurídico.
- **Entrega:** ajustar `objecoes.md` com as 3 objeções que o aluno mais ouve.

## Módulo 6. Instalar (30 min)
- **Objetivo:** agente no ar e WhatsApp pareado.
- **Mostrar ao vivo:**
  1. `claude setup-token` no computador do aluno;
  2. na VPS, `git clone` do kit e `sudo bash agente-whatsapp-perito/instalar.sh`;
  3. as perguntas do configurar (nome, token, número, números de teste, Telegram, Pix);
  4. a leitura do QR em Aparelhos conectados.
- **Entrega:** `agente-perito verificar` com tudo verde.
- **Erro comum:** colar o token com espaço ou quebra de linha; esquecer de abrir o
  WhatsApp do número certo para ler o QR.

## Módulo 7. Testar (30 min)
- **Objetivo:** confiar no agente antes de abrir para todos.
- **Roteiro de teste** (`agente-perito testar` e depois pelo WhatsApp de um número de teste):
  1. advogado com prazo de quesitos em 3 dias;
  2. parte sem advogado achando que o banco cobra demais;
  3. empresa com sócio saindo;
  4. alguém pedindo "um laudo que prove que eu tenho razão";
  5. alguém dizendo "você foi nomeado no meu processo, quer ser meu assistente?";
  6. alguém que só manda "ok" e some (para ver a retomada).
- **O que conferir:** tom, valores certos, nenhuma promessa de resultado, alerta ético no
  Telegram nos casos 4 e 5, Pix só depois do sim.
- **Entrega:** 6 conversas de teste aprovadas; lista de teste esvaziada.

## Módulo 8. Operar e melhorar (20 min)
- **Rotina semanal:** `agente-perito leads` (planilha no Excel), ler 5 conversas, corrigir
  `servicos.md` ou `faq.md` onde o agente errou ou não soube.
- **Assumir uma conversa:** responder pelo celular tira o agente por 24 h.
- **Bloquear alguém:** `#agente bloquear NÚMERO` na "Conversa comigo".
- **Férias e audiência longa:** `AUSENTE` e `AUSENTE_TEXTO` no `.env`.
- **LGPD:** aviso de privacidade (dados no seu servidor, texto passa pelo Claude),
  atender pedido de exclusão, não pôr dado de cliente no conhecimento.
- **Entrega:** primeira revisão semanal feita.

---

## Checklist do aluno no fim do curso
- [ ] VPS contratada e acesso por SSH
- [ ] Número só do trabalho, sem disparo nem grupo por robô
- [ ] `servicos.md`, `tom_de_voz.md`, `icp.md`, `faq.md`, `objecoes.md` sem colchetes
- [ ] `agente-perito verificar` tudo verde
- [ ] 6 conversas de teste aprovadas
- [ ] Lista de teste vazia (agente aberto)
- [ ] Aviso de privacidade publicado e rotina semanal na agenda
