import pytest

from ytkb import llm, paths, synth, youtube
from ytkb.agent import Agent


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """Agente com dados em tmp e toda rede (Ollama/YouTube) desligada."""
    monkeypatch.setattr(llm, "ensure_model", lambda log=None: "fake-model")
    monkeypatch.setattr(youtube, "search", lambda q, max_seconds=1800: [])
    monkeypatch.setattr(synth, "next_query", lambda topic, g, used, model: f"{topic} {len(used)}")
    p = paths.Paths(tmp_path / "data")
    p.ensure()
    (p.rules).write_text("## Assunto\nAssunto Alfa\n", encoding="utf-8")
    ag = Agent(p)
    ag.between_videos_sec = 0.01
    ag.idle_backoff_min = 0.01
    ag.idle_backoff_max = 0.02
    yield ag
    ag.stop()
    if ag._thread:
        ag._thread.join(timeout=5)
