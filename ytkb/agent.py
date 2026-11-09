"""Loop autônomo, fila de links manuais, geração de skill e estado persistente (state.json)."""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import llm, synth, youtube
from .paths import Paths
from .rules import read_rules, slugify

SOURCES_HEADER = "\n\n---\n## Fontes Consultadas (Vídeos Processados)\n"
PLACEHOLDER = "_Base de conhecimento iniciada. Aguardando consolidação dos primeiros vídeos..._"
MAX_PENDING_URLS = 10
MAX_LOGS = 150
MANUAL_MAX_SECONDS = 7200
MAX_VIDEO_FAILURES = 3


class BusyError(RuntimeError):
    """Ação recusada porque o agente está ocupado (HTTP 409)."""


def _now(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


def format_duration(seconds: int | float) -> str:
    s = max(0, int(seconds))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def split_kb_content(md_text: str) -> tuple[str, str]:
    """Separa o corpo consolidado (gerido pela LLM) da lista de fontes (gerida pelo Python)."""
    if SOURCES_HEADER in md_text:
        body, sources = md_text.split(SOURCES_HEADER, 1)
        return body.strip(), sources.strip()
    return md_text.strip(), ""


def build_sources_section(videos: list[dict]) -> str:
    if not videos:
        return ""
    lines = [SOURCES_HEADER.strip(), ""]
    for idx, v in enumerate(videos, 1):
        title = str(v.get("title") or v.get("url") or "Vídeo").replace("[", "(").replace("]", ")")
        lines.append(
            f"{idx}. [{title}]({v.get('url', '')}) — `{format_duration(v.get('duration_sec', 0))}`"
            f" *(processado em {v.get('processed_at', '')})*"
        )
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


class Agent:
    def __init__(self, paths: Paths):
        self.paths = paths
        paths.ensure()
        self._lock = threading.RLock()  # protege estado em memória e state.json
        self._job_lock = threading.Lock()  # uma tarefa pesada (yt-dlp + LLM) por vez
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._url_worker: threading.Thread | None = None
        self._pending_urls: deque[tuple[str, str]] = deque()
        self._inflight_url = ""
        self._skill_busy = False
        self._failures: dict[str, int] = {}  # erros inesperados por vídeo nesta sessão
        self.running = False
        self.busy_action = ""
        self.phase = "Parado"
        self.active_model = llm.DEFAULT_MODEL
        self.started_at: float | None = None
        self.stop_at: float | None = None
        self.current_video: dict | None = None
        self.logs: list[str] = []
        self.between_videos_sec = 3.0
        self.idle_backoff_min = 30.0
        self.idle_backoff_max = 900.0
        self.state = self._load_state()

    # ---------- estado ----------

    def _load_state(self) -> dict:
        path = self.paths.state
        default = {"topics": {}, "last_slug": ""}
        if not path.is_file():
            return default
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not isinstance(state.get("topics", {}), dict):
                raise ValueError("formato inesperado")
        except (ValueError, OSError) as exc:
            backup = path.with_name(f"state.json.corrupt-{int(time.time())}")
            path.replace(backup)
            self.log(f"Erro: state.json corrompido ({exc}). Cópia salva em {backup.name}; iniciando estado vazio.")
            return default
        state.setdefault("topics", {})
        state.setdefault("last_slug", "")
        for tdata in state["topics"].values():
            seen, deduped = set(), []
            for v in tdata.get("processed_videos", []):
                if v.get("id") and v["id"] not in seen:
                    seen.add(v["id"])
                    deduped.append(v)
            tdata["processed_videos"] = deduped
        return state

    def _save_state(self) -> None:
        with self._lock:
            _write_atomic(self.paths.state, json.dumps(self.state, ensure_ascii=False, indent=2))

    def log(self, message: str) -> None:
        entry = f"[{_now('%H:%M:%S')}] {message}"
        print(entry, flush=True)
        with self._lock:
            self.logs.append(entry)
            del self.logs[:-MAX_LOGS]

    def get_topic_entry(self, slug: str, topic: str) -> dict:
        with self._lock:
            topics = self.state.setdefault("topics", {})
            if slug not in topics:
                topics[slug] = {
                    "topic": topic,
                    "slug": slug,
                    "file": f"{slug}.md",
                    "created_at": _now(),
                    "updated_at": _now(),
                    "processed_videos": [],
                    "used_queries": [],
                    "skipped_ids": [],
                }
                self._save_state()
            else:
                topics[slug]["topic"] = topic
                topics[slug].setdefault("skipped_ids", [])
                topics[slug].setdefault("used_queries", [])
                topics[slug].setdefault("processed_videos", [])
            return topics[slug]

    def topic_meta(self, slug: str) -> dict:
        with self._lock:
            return copy.deepcopy(self.state["topics"].get(slug, {}))

    def ensure_kb_initialized(self, rules: dict) -> Path:
        slug, topic = rules["slug"], rules["topic"]
        self.get_topic_entry(slug, topic)
        kb_path = self.paths.kb_file(slug)
        with self._lock:
            if self.state.get("last_slug") != slug:
                if self.state.get("last_slug"):
                    self.log(f"Assunto substituído! Nova base ativa: knowledge/{slug}.md ('{topic}')")
                self.state["last_slug"] = slug
                self._save_state()
        if not kb_path.is_file():
            _write_atomic(kb_path, f"# {topic}\n\n{PLACEHOLDER}\n")
        return kb_path

    def _record_processed_video(self, entry: dict, item: dict) -> None:
        with self._lock:
            if item.get("id") not in {v.get("id") for v in entry["processed_videos"]}:
                entry["processed_videos"].append(item)
            entry["updated_at"] = _now()
            self._save_state()

    def _mark_skipped(self, entry: dict, vid: str) -> None:
        with self._lock:
            if vid not in entry["skipped_ids"]:
                entry["skipped_ids"].append(vid)
                self._save_state()

    @staticmethod
    def _done_ids(entry: dict) -> set[str]:
        return {v["id"] for v in entry["processed_videos"]} | set(entry["skipped_ids"])

    # ---------- processamento de um vídeo (chamar com _job_lock) ----------

    def process_video(self, video: dict, rules: dict, max_seconds: int) -> str:
        """Retorna "processed", "skipped" (permanente) ou "retry" (falha transitória)."""
        slug = rules["slug"]
        kb_path = self.ensure_kb_initialized(rules)
        entry = self.get_topic_entry(slug, rules["topic"])
        self.current_video = video
        label = video.get("title") or video["url"]
        self.phase = f"Transcrevendo: {label}"
        self.log(f"Transcrevendo: {label} - {video['url']}")

        tr = youtube.fetch_transcript(video["url"], max_seconds=max_seconds)
        if not tr.get("ok"):
            self.log(f"Pulado ({tr.get('reason')}): {label}")
            if tr.get("transient"):
                return "retry"
            self._mark_skipped(entry, video["id"])
            return "skipped"

        info = {
            "id": video["id"],
            "url": video["url"],
            "title": tr.get("title") or video.get("title") or video["url"],
            "channel": tr.get("channel") or video.get("channel") or "",
            "duration_sec": tr.get("duration_sec") or video.get("duration_sec") or 0,
        }
        self.phase = f"Extraindo diferencial com {self.active_model}: {info['title'][:45]}..."
        self.log(f"Analisando o que há de novo em '{info['title']}' via {self.active_model}...")

        body, _ = split_kb_content(_read_text(kb_path))
        if PLACEHOLDER in body:
            body = ""
        outcome = synth.synthesize(
            rules["topic"], rules["guidelines"], body, info, tr["transcript"], model=self.active_model, log=self.log
        )
        if outcome["status"] == "irrelevant":
            self.log(f"Conteúdo julgado irrelevante para '{rules['topic']}': {info['title']}")
            self._mark_skipped(entry, video["id"])
            return "skipped"

        self._record_processed_video(entry, {**info, "processed_at": _now("%Y-%m-%d %H:%M")})
        new_body = body if outcome["status"] == "no_new_info" else outcome["body"]
        with self._lock:
            sources = build_sources_section(entry["processed_videos"])
            count = len(entry["processed_videos"])
        _write_atomic(kb_path, new_body.strip() + "\n\n" + sources)
        if outcome["status"] == "no_new_info":
            self.log(f"Vídeo já coberto pela base (sem conceitos inéditos): {info['title']}")
        else:
            self.log(f"Base 'knowledge/{slug}.md' complementada! Vídeos processados no assunto: {count}")
        return "processed"

    # ---------- links manuais ----------

    def submit_url(self, raw_url: str) -> dict:
        vid, url = youtube.extract_youtube_id(raw_url)
        if not vid:
            raise ValueError("Link do YouTube inválido. Envie uma URL como https://www.youtube.com/watch?v=...")
        with self._lock:
            if vid == self._inflight_url or any(v == vid for v, _ in self._pending_urls):
                return {"ok": True, "video_id": vid, "url": url, "queued": False}
            if len(self._pending_urls) >= MAX_PENDING_URLS:
                raise BusyError(f"Fila de links cheia ({MAX_PENDING_URLS}). Aguarde os atuais terminarem.")
            self._pending_urls.append((vid, url))
            if self._url_worker is None:
                self._url_worker = threading.Thread(target=self._drain_urls, daemon=True, name="ytkb-urls")
                self._url_worker.start()
        return {"ok": True, "video_id": vid, "url": url, "queued": True}

    def _drain_urls(self) -> None:
        while True:
            with self._lock:
                if not self._pending_urls:
                    self._url_worker = None
                    return
                vid, url = self._pending_urls.popleft()
                self._inflight_url = vid
            self._process_manual(vid, url)

    def _process_manual(self, vid: str, url: str) -> None:
        self.busy_action = f"Processando link individual ({vid})..."
        try:
            with self._job_lock:
                self.active_model = llm.ensure_model(self.log)
                rules = read_rules(self.paths.rules)
                if not rules["topic"]:
                    self.log("Defina um assunto em REGRAS.md antes de processar um link.")
                    return
                self.log(f"Iniciando leitura individual do link: {url}")
                video = {"id": vid, "url": url, "title": url, "channel": "", "duration_sec": 0}
                self.process_video(video, rules, max_seconds=max(MANUAL_MAX_SECONDS, rules["max_seconds"]))
        except Exception as exc:
            self.log(f"Erro ao processar link individual: {exc}")
        finally:
            with self._lock:
                self._inflight_url = ""
                self.current_video = None
                self.busy_action = ""
                if not self.running:
                    self.phase = "Parado"

    # ---------- skills ----------

    def create_skill(self, slug: str | None = None) -> dict:
        rules = read_rules(self.paths.rules)
        target = slugify(slug) if slug else rules["slug"]
        kb_path = self.paths.kb_file(target)
        if not kb_path.is_file():
            raise ValueError(f"Base 'knowledge/{target}.md' não encontrada.")
        body, _ = split_kb_content(_read_text(kb_path))
        if not body or PLACEHOLDER in body:
            raise ValueError("A base selecionada ainda não possui conhecimento consolidado para virar Skill.")
        with self._lock:
            if self._skill_busy:
                raise BusyError("Já existe uma Skill sendo gerada. Aguarde terminar.")
            self._skill_busy = True
        topic = self.topic_meta(target).get("topic") or target.replace("-", " ").title()

        def worker():
            self.busy_action = f"Gerando Skill '{target}'..."
            try:
                with self._job_lock:
                    self.active_model = llm.ensure_model(self.log)
                    self.log(f"Gerando Skill a partir da base '{topic}' ({target})...")
                    skill_md = synth.generate_skill(topic, target, body, self.active_model)
                    path = self.paths.skill_file(target)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _write_atomic(path, skill_md)
                    self.log(f"Skill criada em: skills/{target}/SKILL.md (revise antes de instalar em um agente)")
            except Exception as exc:
                self.log(f"Erro ao criar Skill '{target}': {exc}")
            finally:
                with self._lock:
                    self._skill_busy = False
                    self.busy_action = ""

        threading.Thread(target=worker, daemon=True, name="ytkb-skill").start()
        return {"ok": True, "slug": target}

    # ---------- loop autônomo ----------

    def start(self, duration_minutes: float | None = None) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise BusyError("O agente ainda está finalizando a tarefa atual. Tente de novo em instantes.")
                if duration_minutes is not None:
                    self.stop_at = time.time() + duration_minutes * 60 if duration_minutes > 0 else None
                return self.status()
            self._stop_event.clear()
            self.running = True
            self.started_at = time.time()
            self.stop_at = self.started_at + duration_minutes * 60 if duration_minutes and duration_minutes > 0 else None
            self.phase = "Iniciando agente..."
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ytkb-loop")
            self._thread.start()
        if duration_minutes and duration_minutes > 0:
            self.log(f"Agente ativado por {duration_minutes:g} min.")
        else:
            self.log("Agente ativado (contínuo até comando de parada).")
        return self.status()

    def stop(self, reason: str = "Parado pelo usuário no painel.") -> dict:
        self._stop_event.set()
        with self._lock:
            was_running = self.running
            self.running = False
            self.stop_at = None
            t = self._thread
            alive = t is not None and t.is_alive() and t is not threading.current_thread()
            self.phase = "Parando (aguardando a tarefa atual terminar)..." if alive else "Parado"
        if was_running:
            self.log(reason)
        return self.status()

    def _should_stop(self) -> bool:
        if self._stop_event.is_set():
            return True
        if self.stop_at and time.time() >= self.stop_at:
            self.stop("Período de execução programado concluído. Agente finalizado.")
            return True
        return False

    def _sleep_interruptible(self, seconds: float) -> None:
        end = time.time() + seconds
        while not self._should_stop():
            remaining = end - time.time()
            if remaining <= 0:
                return
            self._stop_event.wait(min(0.5, remaining))

    def _run_loop(self) -> None:
        backoff = self.idle_backoff_min
        try:
            self.phase = "Verificando conexão com Ollama..."
            self.active_model = llm.ensure_model(self.log)
            self.log(f"Conectado ao Ollama — modelo ativo: {self.active_model}")
            while not self._should_stop():
                try:
                    progressed = self._run_iteration()
                except Exception as exc:
                    self.log(f"Erro no ciclo autônomo (nova tentativa em {int(backoff)}s): {exc}")
                    progressed = False
                if progressed:
                    backoff = self.idle_backoff_min
                else:
                    # Sem vídeos novos ou com erro: espera crescente para não martelar o YouTube.
                    self._sleep_interruptible(backoff)
                    backoff = min(backoff * 2, self.idle_backoff_max)
        except Exception as exc:
            self.log(f"Erro ao iniciar o agente: {exc}")
        finally:
            with self._lock:
                self.running = False
                self.phase = "Parado"
                self.current_video = None

    def _run_iteration(self) -> bool:
        rules = read_rules(self.paths.rules)
        if not rules["topic"]:
            self.phase = "Aguardando assunto em REGRAS.md..."
            self.log("REGRAS.md está sem assunto definido. Defina um assunto para iniciar a busca.")
            return False
        slug = rules["slug"]
        self.ensure_kb_initialized(rules)
        entry = self.get_topic_entry(slug, rules["topic"])

        self.phase = f"Gerando busca para '{rules['topic']}'..."
        with self._lock:
            used = list(entry["used_queries"])
        with self._job_lock:  # uma chamada à LLM por vez: duas em paralelo podem estourar a VRAM
            query = synth.next_query(rules["topic"], rules["guidelines"], used, model=self.active_model)
        with self._lock:
            if query not in entry["used_queries"]:
                entry["used_queries"].append(query)
                self._save_state()
        if self._should_stop():
            return False

        self.phase = f"Buscando vídeos no YouTube: '{query}'"
        self.log(f"Buscando no YouTube: '{query}' (máx {rules['max_minutes']} min)")
        candidates = youtube.search(query, max_seconds=rules["max_seconds"])
        with self._lock:
            done = self._done_ids(entry)
        new = [v for v in candidates if v["id"] not in done]
        self.log(f"Encontrados {len(candidates)} vídeos (<= {rules['max_minutes']} min); {len(new)} inéditos.")

        progressed = False
        for video in new:
            if self._should_stop():
                break
            if read_rules(self.paths.rules)["slug"] != slug:
                self.log("Mudança de assunto detectada em REGRAS.md! Alternando base de conhecimento...")
                break
            with self._lock:
                if video["id"] in self._done_ids(entry):
                    continue
            try:
                with self._job_lock:
                    if self._stop_event.is_set():
                        break
                    result = self.process_video(video, rules, max_seconds=rules["max_seconds"])
                progressed = progressed or result != "retry"
            except Exception as exc:
                fails = self._failures[video["id"]] = self._failures.get(video["id"], 0) + 1
                self.log(f"Erro ao processar {video['url']} (tentativa {fails}/{MAX_VIDEO_FAILURES}): {exc}")
                if fails >= MAX_VIDEO_FAILURES:
                    self._mark_skipped(entry, video["id"])
            finally:
                self.current_video = None
            self._sleep_interruptible(self.between_videos_sec)
        return progressed

    # ---------- leitura para o painel (sem efeitos colaterais) ----------

    def list_knowledge_bases(self, active_slug: str, topics: dict) -> list[dict]:
        items = []
        for md in self.paths.knowledge.glob("*.md"):
            try:
                st = md.stat()
            except OSError:
                continue
            slug = md.stem
            meta = topics.get(slug, {})
            items.append({
                "slug": slug,
                "topic": meta.get("topic") or slug.replace("-", " ").title(),
                "file": md.name,
                "active": slug == active_slug,
                "videos_count": len(meta.get("processed_videos", [])),
                "queries_count": len(meta.get("used_queries", [])),
                "has_skill": (self.paths.skills / slug / "SKILL.md").is_file(),
                "updated_at": meta.get("updated_at") or datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_bytes": st.st_size,
                "_mtime": st.st_mtime,
            })
        items.sort(key=lambda i: i.pop("_mtime"), reverse=True)
        return items

    def list_skills(self, topics: dict) -> list[dict]:
        skills = []
        for f in self.paths.skills.glob("*/SKILL.md"):
            try:
                st = f.stat()
            except OSError:
                continue
            slug = f.parent.name
            skills.append({
                "slug": slug,
                "topic": topics.get(slug, {}).get("topic") or slug.replace("-", " ").title(),
                "path": f"skills/{slug}/SKILL.md",
                "updated_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_bytes": st.st_size,
            })
        return skills

    def status(self) -> dict:
        rules = read_rules(self.paths.rules)
        slug = rules["slug"]
        with self._lock:
            topics = copy.deepcopy(self.state["topics"])
            logs = list(self.logs[-80:])
            running, started_at, stop_at = self.running, self.started_at, self.stop_at
            pending = len(self._pending_urls)
        meta = topics.get(slug, {})
        return {
            "running": running,
            "busy_action": self.busy_action,
            "phase": self.busy_action or self.phase,
            "model": self.active_model,
            "elapsed_seconds": int(time.time() - started_at) if running and started_at else 0,
            "remaining_seconds": max(0, int(stop_at - time.time())) if running and stop_at else None,
            "current_video": self.current_video,
            "pending_urls": pending,
            "rules": rules,
            "data_dir": str(self.paths.root),
            "knowledge_bases": self.list_knowledge_bases(slug, topics),
            "skills": self.list_skills(topics),
            "active_kb_slug": slug,
            "active_kb_content": _read_text(self.paths.kb_file(slug)) if slug else "",
            "active_kb_videos": meta.get("processed_videos", []),
            "active_kb_queries": meta.get("used_queries", []),
            "logs": logs,
        }
