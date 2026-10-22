# Agente de vendas do assistente técnico

Kit exclusivo dos alunos da **Mentoria Águias da Perícia** e do **Águias ONE**.

Um agente de IA que atende advogados no seu **Instagram** ou **WhatsApp** e vende os seus
serviços de assistência técnica com o método do curso (Victor Damásio + Lucas Fernandes,
Olimpo):
- entende o caso em no máximo 2 perguntas (fase do processo e prazo);
- na 3ª mensagem já oferta o serviço certo e, no "faz sentido", manda valor e pagamento;
- trata as objeções de advogado ("vou falar com o cliente", "está caro", "já tem perito");
- nunca deixa o advogado esperando; quando você precisa saber de algo, ele te avisa e segue;
- escreve como você, porque aprende o seu tom.

## Como instalar
Abra esta pasta no **Claude Code** ou no **Codex** e diga:

> Instale o agente para mim seguindo o INSTALAR.md.

Ele conduz tudo. Você vai precisar de:
- uma conta no **Zernio** (zernio.com) com o Inbox ativo, onde você conecta o Instagram
  ou o WhatsApp com o seu login, sem criar app na Meta;
- o **Claude** ou o **Codex** que você já usa (é o cérebro do agente);
- **Python 3.10+** e o computador ligado enquanto o agente atende.

## Comandos
| Comando | O que faz |
|---|---|
| `python agente.py configurar` | chave do Zernio, seu nome, cérebro e fase de teste |
| `python agente.py verificar` | confere se está tudo pronto |
| `python agente.py testar` | você faz o papel do advogado no terminal |
| `python agente.py` (ou `iniciar.bat`) | liga o agente |

## O que você escreve
Só dois arquivos na pasta `conhecimento/`: `servicos.md` (seus serviços, valores e como
pagar) e `tom_de_voz.md` (como você escreve). O método de venda já vem pronto em
`metodo_vendas.md`. O agente só usa o que está nesses arquivos e só manda os links
que estão neles.

## Licença
Uso exclusivo de alunos ativos. Veja o [LICENSE](LICENSE).
