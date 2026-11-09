import json
import threading
import time

import pytest

from ytkb import synth, youtube
from ytkb.agent import Agent, BusyError


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def video(vid):
    return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": vid, "channel": "", "duration_sec": 600}


def ok_transcript(url, max_seconds=1800):
    return {"ok": True, "title": "T", "channel": "C", "duration_sec": 600, "transcript": "texto " * 50}


def test_corrupt_state_is_backed_up_not_silently_reset(agent):
    agent.paths.state.write_text("{ quebrado", encoding="utf-8")
    ag2 = Agent(agent.paths)
    backups = list(agent.paths.knowledge.glob("state.json.corrupt-*"))
    assert backups and backups[0].read_text(encoding="utf-8") == "{ quebrado"
    assert any("corrompido" in line for line in ag2.logs)


def test_concurrent_records_keep_state_valid(agent):
    entry = agent.get_topic_entry("assunto-alfa", "Assunto Alfa")
    threads = [
        threading.Thread(target=agent._record_processed_video, args=(entry, video(f"vid{i:08d}"))) for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    agent._record_processed_video(entry, video("vid00000000"))
    data = json.loads(agent.paths.state.read_text(encoding="utf-8"))
    assert len(data["topics"]["assunto-alfa"]["processed_videos"]) == 20


def test_topic_switch_creates_separate_kb(agent):
    from ytkb.rules import parse_rules

    a = agent.ensure_kb_initialized(parse_rules("## Assunto\nAssunto Alfa"))
    b = agent.ensure_kb_initialized(parse_rules("## Assunto\nAssunto Beta"))
    assert a.name == "assunto-alfa.md" and b.name == "assunto-beta.md"
    assert a.is_file() and b.is_file()


def test_status_is_read_only(agent):
    agent.paths.rules.write_text("## Assunto\nTema Novo\n", encoding="utf-8")
    st = agent.status()
    assert st["active_kb_slug"] == "tema-novo"
    assert not (agent.paths.knowledge / "tema-novo.md").exists()
    json.dumps(st)


def test_loop_survives_error_in_one_video(agent, monkeypatch):
    monkeypatch.setattr(youtube, "search", lambda q, max_seconds=1800: [video("aaaaaaaaaaa"), video("bbbbbbbbbbb")])

    def flaky(url, max_seconds=1800):
        if "aaaaaaaaaaa" in url:
            raise RuntimeError("timeout de rede")
        return ok_transcript(url)

    monkeypatch.setattr(youtube, "fetch_transcript", flaky)
    monkeypatch.setattr(synth, "synthesize", lambda *a, **k: {"status": "updated", "body": "# Assunto Alfa\nnovo"})
    agent.start()
    assert wait_for(lambda: agent.state["topics"].get("assunto-alfa", {}).get("processed_videos"))
    agent.stop()
    entry = agent.state["topics"]["assunto-alfa"]
    assert [v["id"] for v in entry["processed_videos"]] == ["bbbbbbbbbbb"]
    assert "aaaaaaaaaaa" not in entry["skipped_ids"], "erro transitório não pode virar skip permanente"
    assert any("timeout de rede" in line for line in agent.logs)


def test_start_after_stop_does_not_spawn_second_loop(agent, monkeypatch):
    release = threading.Event()
    entered = threading.Event()
    monkeypatch.setattr(youtube, "search", lambda q, max_seconds=1800: [video("aaaaaaaaaaa")])

    def blocking(url, max_seconds=1800):
        entered.set()
        release.wait(5)
        return {"ok": False, "reason": "x", "transient": True}

    monkeypatch.setattr(youtube, "fetch_transcript", blocking)
    agent.start()
    assert entered.wait(5)
    agent.stop()
    with pytest.raises(BusyError):
        agent.start()
    assert "Parando" in agent.status()["phase"]
    release.set()
    agent._thread.join(5)
    agent.start()
    assert agent.running


def test_timer_stops_loop(agent):
    agent.start(duration_minutes=0.001)
    assert wait_for(lambda: not agent.running and not agent._thread.is_alive())


def test_manual_url_queue(agent, monkeypatch):
    done, release = [], threading.Event()

    def fetch(url, max_seconds=1800):
        release.wait(5)
        done.append(url)
        return {"ok": False, "reason": "sem legenda", "transient": False}

    monkeypatch.setattr(youtube, "fetch_transcript", fetch)
    with pytest.raises(ValueError):
        agent.submit_url("https://evil.example/x")
    assert agent.submit_url("https://youtu.be/LjVZpvGT7Mw")["queued"]
    assert not agent.submit_url("https://www.youtube.com/watch?v=LjVZpvGT7Mw")["queued"]
    release.set()
    assert wait_for(lambda: done and agent._url_worker is None)
    assert done == ["https://www.youtube.com/watch?v=LjVZpvGT7Mw"]


def test_create_skill_writes_file(agent, monkeypatch):
    kb = agent.paths.knowledge / "assunto-alfa.md"
    kb.write_text("# Assunto Alfa\n\nconhecimento real", encoding="utf-8")
    monkeypatch.setattr(synth, "generate_skill", lambda topic, slug, body, model: f"---\nname: {slug}\n---\nok\n")
    agent.create_skill("assunto-alfa")
    skill = agent.paths.skills / "assunto-alfa" / "SKILL.md"
    assert wait_for(skill.is_file)
    with pytest.raises(ValueError):
        agent.create_skill("nao-existe")


def test_video_that_always_fails_is_skipped_after_3_tries(agent, monkeypatch):
    monkeypatch.setattr(youtube, "search", lambda q, max_seconds=1800: [video("aaaaaaaaaaa")])
    calls = []

    def broken(url, max_seconds=1800):
        calls.append(url)
        raise RuntimeError("formato de legenda inesperado")

    monkeypatch.setattr(youtube, "fetch_transcript", broken)
    agent.start()
    assert wait_for(lambda: "aaaaaaaaaaa" in agent.state["topics"].get("assunto-alfa", {}).get("skipped_ids", []))
    agent.stop()
    assert len(calls) == 3


def test_next_query_waits_for_job_lock(agent, monkeypatch):
    called = threading.Event()
    monkeypatch.setattr(synth, "next_query", lambda *a, **k: called.set() or "q")
    with agent._job_lock:
        agent.start()
        assert not called.wait(0.3), "busca nova não pode chamar a LLM enquanto outra tarefa usa o Ollama"
    assert called.wait(5)
