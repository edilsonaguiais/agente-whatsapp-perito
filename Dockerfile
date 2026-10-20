FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
# Claude Code: o motor "assinatura" chama `claude -p` (login por CLAUDE_CODE_OAUTH_TOKEN).
# git: para puxar o conhecimento de um repositório GitHub do perito.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://claude.ai/install.sh | bash
ENV PATH=/root/.local/bin:$PATH DISABLE_AUTOUPDATER=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agente_perito ./agente_perito
COPY modelos ./modelos
COPY exemplos ./exemplos
EXPOSE 8000
CMD ["python", "-m", "agente_perito", "iniciar"]
