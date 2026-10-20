#!/usr/bin/env bash
# Instala o Agente de WhatsApp do Perito numa VPS Linux limpa (Ubuntu ou Debian):
#
#   git clone <ENDERECO-DO-REPOSITORIO> agente-whatsapp-perito
#   sudo bash agente-whatsapp-perito/instalar.sh
#
# Pergunta as suas chaves (Claude, número do WhatsApp, Telegram opcional), sobe o OpenWA
# e o agente no Docker e mostra o QR para parear. Para atualizar depois: agente-perito atualizar-kit
set -euo pipefail

PASTA="${AGENTE_PASTA:-/opt/agente-perito}"
ATUALIZAR=0
[ "${1:-}" = "--atualizar" ] && ATUALIZAR=1

passo() { printf '\n\033[1m▶ %s\033[0m\n' "$1"; }
falha() { printf '\n\033[31m✖ %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || falha "Rode como administrador: sudo bash instalar.sh"
[ "$(uname -s)" = "Linux" ] || falha "Este instalador é para servidor Linux (Ubuntu ou Debian)."

passo "1/6 Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || falha "Falta o Docker Compose. Instale o pacote docker-compose-plugin."
echo "Docker pronto."

passo "2/6 Copiando o agente para $PASTA"
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$ORIGEM/docker-compose.yml" ] || falha "Rode o instalar.sh de dentro da pasta do kit."
mkdir -p "$PASTA"
if [ "$ORIGEM" != "$(cd "$PASTA" && pwd)" ]; then
  # .env, conhecimento/ e dados/ não vêm do kit: suas configurações e conversas ficam intactas.
  tar -C "$ORIGEM" --exclude=./.env --exclude=./dados --exclude=./conhecimento --exclude=./.git -cf - . \
    | tar -C "$PASTA" -xf -
fi
cd "$PASTA"
touch .env && chmod 600 .env
mkdir -p dados conhecimento
echo "Arquivos em $PASTA."

passo "3/6 Comando agente-perito"
cat > /usr/local/bin/agente-perito <<WRAPPER
#!/usr/bin/env bash
# Atalho para controlar o Agente de WhatsApp do Perito instalado em $PASTA.
set -e
cd "$PASTA"
rodando() { [ -n "\$(docker compose ps -q --status running agente 2>/dev/null)" ]; }
py() {
  if rodando; then docker compose exec agente python -m agente_perito "\$@"
  else docker compose run --rm --no-deps agente python -m agente_perito "\$@"; fi
}
case "\${1:-ajuda}" in
  logs)        docker compose logs -f --tail 100 "\${2:-agente}" ;;
  reiniciar)   docker compose up -d --force-recreate agente ;;
  parar)       docker compose down ;;
  ligar)       docker compose up -d ;;
  configurar)  py configurar && docker compose up -d && docker compose up -d --force-recreate agente ;;
  parear)      py parear && docker compose up -d --force-recreate agente ;;
  editar)      \${EDITOR:-nano} "conhecimento/\${2:-servicos.md}" && docker compose restart agente && echo "Agente reiniciado com o conhecimento novo." ;;
  github|atualizar) py "\$@" && docker compose restart agente && echo "Agente reiniciado com o conhecimento novo." ;;
  atualizar-kit)
    [ -d "$ORIGEM/.git" ] && git -C "$ORIGEM" pull --ff-only
    sudo bash "$ORIGEM/instalar.sh" --atualizar ;;
  ajuda|-h|--help)
    cat <<'AJUDA'
agente-perito configurar        pergunta e confere as chaves (Claude, WhatsApp, Telegram, Pix)
agente-perito parear            mostra o QR para ligar o WhatsApp
agente-perito verificar         checklist do que está funcionando
agente-perito testar            conversa com o agente no terminal, sem WhatsApp
agente-perito editar [arquivo]  edita conhecimento/servicos.md (ou tom_de_voz.md, faq.md...)
agente-perito github URL        liga o conhecimento ao seu repositório GitHub e puxa
agente-perito atualizar         puxa de novo o conhecimento do GitHub
agente-perito bloquear NÚMERO   o agente nunca mais responde esse número (liberar desfaz)
agente-perito bloqueados        lista os bloqueados
agente-perito leads             lista quem conversou e grava a planilha dados/leads.csv
agente-perito logs [openwa]     acompanha as conversas em tempo real
agente-perito reiniciar | parar | ligar | atualizar-kit
AJUDA
    ;;
  *) py "\$@" ;;
esac
WRAPPER
chmod +x /usr/local/bin/agente-perito
echo "Pronto: digite agente-perito para ver os comandos."

passo "4/6 Montando o agente (alguns minutos na primeira vez)"
docker compose pull -q openwa
docker compose build -q

if [ "$ATUALIZAR" = 1 ]; then
  docker compose up -d --force-recreate
  printf '\n✅ Atualizado. Suas configurações, conhecimento e conversas foram mantidos.\n'
  exit 0
fi

passo "5/6 Suas chaves"
agente-perito configurar </dev/tty

passo "6/6 Ligando o WhatsApp"
agente-perito parear </dev/tty || echo "Sem problema: rode agente-perito parear quando quiser."

cat <<FIM

✅ Instalação concluída.

Agora, nesta ordem:
  1. Preencha seus serviços:      agente-perito editar servicos.md
     (e tom_de_voz.md, icp.md, faq.md, objecoes.md)
  2. Converse com o agente:       agente-perito testar
  3. Confira tudo:                agente-perito verificar
  4. Teste pelo WhatsApp com um número da lista de teste e acompanhe:  agente-perito logs
  5. Só depois abra a todos:      agente-perito configurar (lista de teste vazia, digite -)
FIM
