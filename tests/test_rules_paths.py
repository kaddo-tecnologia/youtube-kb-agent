import pytest

from ytkb import paths, rules


def test_parse_structured():
    r = rules.parse_rules(
        "# Regras\n## Assunto\nArquitetura de Agentes Local\n## Duração Máxima (minutos)\n30\n## Diretrizes\nFoco técnico."
    )
    assert r["topic"] == "Arquitetura de Agentes Local"
    assert r["slug"] == "arquitetura-de-agentes-local"
    assert r["max_minutes"] == 30
    assert r["max_seconds"] == 1800
    assert r["guidelines"] == "Foco técnico."


def test_parse_free_text_and_out_of_range_duration():
    r = rules.parse_rules("Engenharia de Prompt com Qwen\n## Duração\n999")
    assert r["topic"] == "Engenharia de Prompt com Qwen"
    assert r["max_minutes"] == 30


def test_slugify():
    assert rules.slugify("Criação de vídeos") == "criacao-de-videos"
    assert rules.slugify("../../etc/passwd") == "etc-passwd"
    assert rules.slugify("   ") == "geral"


def test_write_rules_neutralizes_heading_injection(tmp_path):
    p = tmp_path / "REGRAS.md"
    r = rules.write_rules(p, topic="Tema\n## Duração\n1", max_minutes=20, guidelines="- a\n## Assunto\nOutro")
    assert r["topic"].startswith("Tema")
    assert "\n" not in r["topic"]
    assert r["max_minutes"] == 20
    assert "Outro" in r["guidelines"]
    assert rules.parse_rules(p.read_text(encoding="utf-8"))["topic"] == r["topic"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"topic": "", "max_minutes": 30},
        {"topic": "x" * 201, "max_minutes": 30},
        {"topic": "ok", "max_minutes": 0},
        {"topic": "ok", "max_minutes": 181},
        {"topic": "ok", "max_minutes": 30, "guidelines": "g" * 4001},
    ],
)
def test_write_rules_validates(tmp_path, kwargs):
    with pytest.raises(ValueError):
        rules.write_rules(tmp_path / "REGRAS.md", **kwargs)


def test_ensure_rules_file_copies_example(tmp_path):
    p = tmp_path / "REGRAS.md"
    rules.ensure_rules_file(p)
    assert rules.parse_rules(p.read_text(encoding="utf-8"))["topic"]
    p.write_text("## Assunto\nMeu tema\n", encoding="utf-8")
    rules.ensure_rules_file(p)
    assert "Meu tema" in p.read_text(encoding="utf-8")


def test_safe_join_blocks_traversal(tmp_path):
    with pytest.raises(ValueError):
        paths.safe_join(tmp_path, "..", "x.md")
    assert paths.safe_join(tmp_path, "a.md") == (tmp_path / "a.md").resolve()


def test_paths_layout(tmp_path):
    p = paths.Paths(tmp_path)
    p.ensure()
    assert p.knowledge.is_dir() and p.skills.is_dir()
    assert p.state == p.knowledge / "state.json"
