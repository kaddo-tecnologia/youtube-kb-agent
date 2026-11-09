"""Onde ficam os dados do usuário. O código (npx/cache) nunca guarda estado."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"
EXAMPLE_RULES = PKG_DIR / "REGRAS.example.md"


def default_data_dir() -> Path:
    return Path(os.environ.get("YTKB_DATA_DIR") or Path.home() / ".youtube-kb-agent")


def safe_join(base: Path, *parts: str) -> Path:
    """Junta caminhos e garante que o resultado continua dentro de `base`."""
    root = base.resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"Caminho fora da pasta de dados: {target}")
    return target


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def rules(self) -> Path:
        return self.root / "REGRAS.md"

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def skills(self) -> Path:
        return self.root / "skills"

    @property
    def state(self) -> Path:
        return self.knowledge / "state.json"

    def ensure(self) -> None:
        self.knowledge.mkdir(parents=True, exist_ok=True)
        self.skills.mkdir(parents=True, exist_ok=True)

    def kb_file(self, slug: str) -> Path:
        return safe_join(self.knowledge, f"{slug}.md")

    def skill_file(self, slug: str) -> Path:
        return safe_join(self.skills, slug, "SKILL.md")
