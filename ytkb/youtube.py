"""Busca e transcrição no YouTube via yt-dlp (biblioteca, sem subprocess)."""
from __future__ import annotations

import html
import re
import urllib.parse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
MIN_SECONDS = 60
LANG_PREFS = ("pt", "en")
MAX_CAPTION_BYTES = 5 * 1024 * 1024
TRANSIENT_HINTS = ("429", "timed out", "timeout", "temporarily", "connection", "http error 5", "network", "reset by peer")
BASE_OPTS = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 30}
_TAG_RE = re.compile(r"<[^>]+>")


def canonical_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


def extract_youtube_id(url_or_id: str) -> tuple[str, str]:
    """Retorna (video_id, url_canônica) ou ("", "") se não for um vídeo do YouTube."""
    raw = (url_or_id or "").strip()
    if VIDEO_ID_RE.fullmatch(raw):
        return raw, canonical_url(raw)
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower()
    vid = ""
    if host in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        vid = (urllib.parse.parse_qs(parsed.query).get("v") or [""])[0].strip()
        if not vid:
            m = re.search(r"/(?:shorts|embed|live|v)/([^/?#]+)", parsed.path)
            vid = m.group(1) if m else ""
    if VIDEO_ID_RE.fullmatch(vid):
        return vid, canonical_url(vid)
    return "", ""


def parse_vtt(text: str) -> str:
    """WebVTT -> linhas de texto. Remove tempos/tags e as repetições das legendas automáticas (roll-up)."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or "-->" in s or s.isdigit() or s.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
            continue
        s = html.unescape(_TAG_RE.sub("", s)).strip()
        if s and s not in out[-3:]:
            out.append(s)
    return "\n".join(out)


def compact_transcript(transcript: str) -> str:
    """Remove timestamps [mm:ss] e une linhas em prosa, sem repetir linhas consecutivas."""
    cleaned: list[str] = []
    for line in transcript.splitlines():
        txt = re.sub(r"^\[(?:\d{1,2}:)?\d{2}:\d{2}\]\s*", "", line).strip()
        if txt and not (cleaned and cleaned[-1].lower() == txt.lower()):
            cleaned.append(txt)
    return " ".join(cleaned)


def _vtt_url(formats) -> str:
    for f in formats or []:
        if f.get("ext") == "vtt" and f.get("url"):
            return f["url"]
    return ""


def _matches(lang: str, pref: str) -> bool:
    lang = lang.lower()
    return lang == pref or lang.startswith(pref + "-")


def pick_caption(info: dict, prefs: tuple[str, ...] = LANG_PREFS) -> tuple[str, str] | None:
    """Ordem: legenda manual (idiomas preferidos, depois qualquer) > automática no idioma original > automática traduzida."""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    order = [(k, manual[k]) for p in prefs for k in manual if _matches(k, p)]
    order += list(manual.items())
    order += [(k, v) for k, v in auto.items() if k.endswith("-orig")]
    order += [(k, auto[k]) for p in prefs for k in auto if _matches(k, p)]
    for lang, formats in order:
        url = _vtt_url(formats)
        if url:
            return lang, url
    return None


def _fail(reason: str, transient: bool) -> dict:
    return {"ok": False, "reason": reason, "transient": transient}


def search(query: str, max_seconds: int = 1800, limit: int = 15) -> list[dict]:
    """Busca vídeos e filtra por MIN_SECONDS <= duração <= max_seconds."""
    with YoutubeDL({**BASE_OPTS, "extract_flat": "in_playlist", "skip_download": True}) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False) or {}
    out, seen = [], set()
    for e in info.get("entries") or []:
        vid, dur = str(e.get("id") or ""), e.get("duration")
        if not VIDEO_ID_RE.fullmatch(vid) or vid in seen or not isinstance(dur, (int, float)):
            continue
        if not MIN_SECONDS <= dur <= max_seconds:
            continue
        seen.add(vid)
        out.append({
            "id": vid,
            "url": canonical_url(vid),
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration_sec": int(dur),
        })
    return out


def fetch_transcript(url: str, max_seconds: int = 1800) -> dict:
    """Baixa só a legenda (nunca o vídeo). `transient=True` indica falha que vale tentar de novo depois."""
    text = ""
    try:
        with YoutubeDL({**BASE_OPTS, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False) or {}
            duration = int(info.get("duration") or 0)
            if info.get("is_live"):
                return _fail("Transmissão ao vivo não é suportada", False)
            if max_seconds and duration > max_seconds:
                return _fail(f"Duração real ({duration}s) excede limite ({max_seconds}s)", False)
            picked = pick_caption(info)
            if picked:
                text = parse_vtt(ydl.urlopen(picked[1]).read(MAX_CAPTION_BYTES).decode("utf-8", "replace"))
    except DownloadError as exc:
        msg = str(exc).replace("ERROR: ", "")[:200]
        return _fail(msg, any(h in msg.lower() for h in TRANSIENT_HINTS))
    if not text:
        return _fail("Vídeo sem legendas", False)
    if len(text) < 80:
        return _fail("Transcrição muito curta ou sem fala relevante", False)
    return {
        "ok": True,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration_sec": duration,
        "transcript": text,
    }

