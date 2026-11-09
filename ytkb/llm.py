"""Cliente mínimo do Ollama (API nativa /api/generate)."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "16384"))


def normalize_host(raw: str) -> str:
    """Aceita o formato do próprio Ollama (`0.0.0.0:11434`, sem esquema) e devolve uma URL utilizável."""
    raw = (raw or "").strip() or "127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    p = urllib.parse.urlparse(raw)
    host = p.hostname or "127.0.0.1"
    if host in ("0.0.0.0", "::"):  # noqa: S104 - converte bind-all para loopback
        host = "127.0.0.1"
    netloc = f"[{host}]:{p.port or 11434}" if ":" in host else f"{host}:{p.port or 11434}"
    return f"{p.scheme}://{netloc}"


def is_loopback(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


BASE_URL = normalize_host(os.environ.get("OLLAMA_HOST", ""))


def pick_model(models: list[str], preferred: str) -> str:
    chat = [m for m in models if "embed" not in m.lower()]
    if preferred in chat:
        return preferred
    for m in chat:
        if m.lower().startswith("qwen"):
            return m
    if chat:
        return chat[0]
    raise RuntimeError(f"Nenhum modelo de chat instalado no Ollama. Rode: ollama pull {preferred}")


def _tags() -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/api/tags", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_model(log=None) -> str:
    """Garante o Ollama respondendo (inicia `ollama serve` local se preciso) e devolve o modelo a usar."""
    if not is_loopback(BASE_URL) and log:
        log(f"Aviso: OLLAMA_HOST aponta para {BASE_URL}; transcrições e bases serão enviadas para essa máquina.")
    try:
        data = _tags()
    except OSError:
        exe = shutil.which("ollama")
        if not exe or not is_loopback(BASE_URL):
            raise RuntimeError(f"Ollama indisponível em {BASE_URL}. Instale em https://ollama.com e rode 'ollama serve'.") from None
        if log:
            log("Ollama não estava ativo. Iniciando 'ollama serve' em segundo plano...")
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for _ in range(15):
            time.sleep(1)
            try:
                data = _tags()
                break
            except OSError:
                continue
        else:
            raise RuntimeError(f"Ollama não respondeu em {BASE_URL} após 'ollama serve'.") from None
    return pick_model([m.get("name", "") for m in data.get("models", [])], DEFAULT_MODEL)


def _post(payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate(prompt: str, system: str = "", model: str | None = None, timeout: int = 360) -> str:
    payload = {
        "model": model or ensure_model(),
        "prompt": prompt,
        "system": system,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.25, "num_ctx": NUM_CTX},
    }
    try:
        result = _post(payload, timeout)
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        payload.pop("think")  # Ollama antigo não conhece o campo
        result = _post(payload, timeout)
    return re.sub(r"<think>.*?</think>", "", result.get("response", ""), flags=re.DOTALL).strip()
