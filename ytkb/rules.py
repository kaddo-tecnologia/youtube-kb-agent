"""REGRAS.md: assunto, duração máxima e diretrizes de estudo."""
from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

from .paths import EXAMPLE_RULES

DEFAULT_MINUTES = 30
MAX_MINUTES = 180
MAX_TOPIC_LEN = 200
MAX_GUIDELINES_LEN = 4000
DEFAULT_GUIDELINES = (
    "- Extrair apenas conhecimento útil, técnico ou conceitual sobre o assunto.\n"
    "- Consolidar tudo em um documento único organizado por seções claras, sem duplicar tópicos."
)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(text.strip().lower())).strip("-")
    return slug[:80].strip("-") or "geral"


def parse_rules(raw_text: str) -> dict:
    """Extrai assunto, duração máxima (min) e diretrizes. Aceita Markdown com seções ou texto livre."""
    text = raw_text.strip()
    sections: dict[str, list[str]] = {"_top": []}
    current = "_top"
    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if m:
            heading = _ascii(m.group(1).lower())
            if any(k in heading for k in ("assunto", "tema", "conteudo", "topico")):
                current = "topic"
            elif any(k in heading for k in ("duracao", "tempo", "minuto")):
                current = "duration"
            elif any(k in heading for k in ("diretriz", "regra", "instruc")):
                current = "guidelines"
            else:
                current = heading
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)

    topic = "\n".join(sections.get("topic", [])).strip()
    if not topic:
        non_empty = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        topic = non_empty[0] if non_empty else ""
    topic = " ".join(topic.split())

    dur_match = re.search(r"(\d+)", "\n".join(sections.get("duration", [])))
    max_minutes = int(dur_match.group(1)) if dur_match else DEFAULT_MINUTES
    if not 0 < max_minutes <= MAX_MINUTES:
        max_minutes = DEFAULT_MINUTES

    guidelines = "\n".join(sections.get("guidelines", [])).strip() or DEFAULT_GUIDELINES
    return {
        "topic": topic,
        "slug": slugify(topic) if topic else "",
        "max_minutes": max_minutes,
        "max_seconds": max_minutes * 60,
        "guidelines": guidelines,
    }


def write_rules(path: Path, topic: str, max_minutes: int, guidelines: str = "") -> dict:
    """Valida e grava REGRAS.md. Levanta ValueError para entrada inválida."""
    if not isinstance(topic, str) or not isinstance(guidelines, str):
        raise ValueError("Assunto e diretrizes devem ser texto.")
    if isinstance(max_minutes, bool) or not isinstance(max_minutes, int):
        raise ValueError("Duração máxima deve ser um número inteiro de minutos.")
    topic = " ".join(topic.split())
    if not topic or len(topic) > MAX_TOPIC_LEN:
        raise ValueError(f"Informe um assunto entre 1 e {MAX_TOPIC_LEN} caracteres.")
    if not 0 < max_minutes <= MAX_MINUTES:
        raise ValueError(f"Duração máxima deve estar entre 1 e {MAX_MINUTES} minutos.")
    if len(guidelines) > MAX_GUIDELINES_LEN:
        raise ValueError(f"Diretrizes com no máximo {MAX_GUIDELINES_LEN} caracteres.")
    # Linha começando com '#' viraria uma nova seção e sequestraria assunto/duração.
    guidelines = re.sub(r"^(\s*)#", r"\1\\#", guidelines.strip(), flags=re.MULTILINE) or DEFAULT_GUIDELINES
    content = (
        "# Regras do Agente de Conhecimento YouTube\n\n"
        f"## Assunto\n{topic}\n\n"
        f"## Duração Máxima (minutos)\n{max_minutes}\n\n"
        f"## Diretrizes de Estudo\n{guidelines}\n"
    )
    path.write_text(content, encoding="utf-8")
    return parse_rules(content)


def ensure_rules_file(path: Path) -> None:
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXAMPLE_RULES, path)


def read_rules(path: Path) -> dict:
    ensure_rules_file(path)
    return parse_rules(path.read_text(encoding="utf-8"))
