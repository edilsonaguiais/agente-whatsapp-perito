"""Conhecimento vindo de um repositório GitHub do próprio perito.

    agente-perito github https://github.com/usuario/meu-conhecimento   (liga e puxa a 1ª vez)
    agente-perito atualizar                                              (puxa de novo)

O repositório pode ter os .md na raiz ou numa pasta `conhecimento/`. Todo .md entra
(menos README e LICENSE). A versão anterior de cada arquivo substituído fica guardada em
dados/conhecimento-anterior/<data-hora>/, para voltar atrás se precisar.
Repositório privado: o token (GITHUB_TOKEN no .env, só leitura) vai no cabeçalho da
requisição e nunca é gravado na pasta do clone.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import time
from pathlib import Path

RE_REPO = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$")
FORA = {"readme.md", "license.md", "licenca.md", "changelog.md"}


def url_valida(url: str) -> bool:
    return bool(RE_REPO.match(url.strip()))


def _git(args: list[str], token: str = "", cwd: Path | None = None) -> None:
    extra = []
    if token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        extra = ["-c", f"http.extraHeader=Authorization: Basic {cred}"]
    proc = subprocess.run(["git", *extra, *args], cwd=cwd, capture_output=True, text=True, timeout=180)
    if proc.returncode:
        erro = proc.stderr.replace(token, "***") if token else proc.stderr
        raise RuntimeError(f"git {args[0]} falhou: {erro.strip()[-300:]}")


def sincronizar(url: str, destino: Path, pasta_clone: Path, token: str = "") -> list[str]:
    """Clona (ou atualiza) o repositório e copia os .md para `destino`. Devolve os nomes copiados."""
    if not url_valida(url):
        raise ValueError("use o endereço https://github.com/usuario/repositorio")
    if (pasta_clone / ".git").exists():
        _git(["pull", "--ff-only", "-q"], token, cwd=pasta_clone)
    else:
        pasta_clone.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--depth", "1", "-q", url.strip(), str(pasta_clone)], token)
    origem = pasta_clone / "conhecimento" if (pasta_clone / "conhecimento").is_dir() else pasta_clone
    arquivos = sorted(p for p in origem.glob("*.md") if p.name.lower() not in FORA)
    if not arquivos:
        raise RuntimeError("o repositório não tem nenhum .md (na raiz ou em conhecimento/)")
    destino.mkdir(parents=True, exist_ok=True)
    guarda = pasta_clone.parent / "conhecimento-anterior" / time.strftime("%Y%m%d-%H%M%S")
    copiados = []
    for arq in arquivos:
        alvo = destino / arq.name
        if alvo.exists() and alvo.read_bytes() != arq.read_bytes():
            guarda.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alvo, guarda / arq.name)
        shutil.copy2(arq, alvo)
        copiados.append(arq.name)
    return copiados
