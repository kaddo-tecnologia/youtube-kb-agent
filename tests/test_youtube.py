import pytest
from yt_dlp.utils import DownloadError

from ytkb import youtube

VTT = """WEBVTT
Kind: captions
Language: pt

00:00:00.000 --> 00:00:02.000 align:start position:0%
Olá<00:00:00.500><c> pessoal</c>

00:00:02.000 --> 00:00:02.010
Olá pessoal

00:00:02.010 --> 00:00:04.000
Olá pessoal
hoje vamos<c> configurar</c>

00:00:04.000 --> 00:00:06.000
hoje vamos configurar
o Ollama &amp; agentes
"""


def test_parse_vtt_dedupes_rollup_and_strips_tags():
    assert youtube.parse_vtt(VTT) == "Olá pessoal\nhoje vamos configurar\no Ollama & agentes"


def test_compact_transcript():
    raw = "[00:01] Olá pessoal\n[00:03] Olá pessoal\n[00:05] Hoje vamos configurar o Ollama."
    assert youtube.compact_transcript(raw) == "Olá pessoal Hoje vamos configurar o Ollama."


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.youtube.com/watch?v=LjVZpvGT7Mw&t=10s", "LjVZpvGT7Mw"),
        ("https://youtu.be/btMoPRHz8eM", "btMoPRHz8eM"),
        ("https://m.youtube.com/shorts/btMoPRHz8eM", "btMoPRHz8eM"),
        ("LjVZpvGT7Mw", "LjVZpvGT7Mw"),
        ("https://notyoutube.com/watch?v=LjVZpvGT7Mw", ""),
        ("https://www.youtube.com/watch?v=bad", ""),
        ("--exec calc", ""),
    ],
)
def test_extract_youtube_id(raw, expected):
    vid, url = youtube.extract_youtube_id(raw)
    assert vid == expected
    if expected:
        assert url == f"https://www.youtube.com/watch?v={expected}"


def test_pick_caption_prefers_manual_then_original_auto():
    manual = {"subtitles": {"live_chat": [{"ext": "json", "url": "x"}], "pt-BR": [{"ext": "vtt", "url": "m"}]}}
    assert youtube.pick_caption(manual) == ("pt-BR", "m")
    auto = {
        "subtitles": {},
        "automatic_captions": {
            "pt": [{"ext": "vtt", "url": "translated"}],
            "en-orig": [{"ext": "json3", "url": "j"}, {"ext": "vtt", "url": "orig"}],
        },
    }
    assert youtube.pick_caption(auto) == ("en-orig", "orig")
    assert youtube.pick_caption({"automatic_captions": {"pt": [{"ext": "vtt", "url": "p"}]}}) == ("pt", "p")
    assert youtube.pick_caption({}) is None


class FakeYDL:
    info: dict = {}
    raise_on_extract: Exception | None = None
    body = VTT.encode()

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if FakeYDL.raise_on_extract:
            raise FakeYDL.raise_on_extract
        return FakeYDL.info

    def urlopen(self, url):
        class R:
            def read(_self, n=-1):
                return FakeYDL.body

        return R()


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.info, FakeYDL.raise_on_extract = {}, None
    monkeypatch.setattr(youtube, "YoutubeDL", FakeYDL)
    return FakeYDL


def test_search_filters_duration_and_invalid_ids(fake_ydl):
    fake_ydl.info = {
        "entries": [
            {"id": "LjVZpvGT7Mw", "title": "Bom", "duration": 600, "channel": "C"},
            {"id": "aaaaaaaaaaa", "title": "Longo", "duration": 4000},
            {"id": "bbbbbbbbbbb", "title": "Short", "duration": 30},
            {"id": "x;rm -rf /", "title": "Ruim", "duration": 600},
            {"id": "ccccccccccc", "title": "Sem duração", "duration": None},
        ]
    }
    res = youtube.search("ollama", max_seconds=1800)
    assert [v["id"] for v in res] == ["LjVZpvGT7Mw"]
    assert res[0]["url"] == "https://www.youtube.com/watch?v=LjVZpvGT7Mw"


def test_fetch_transcript_ok(fake_ydl):
    fake_ydl.info = {
        "duration": 600,
        "title": "Vídeo",
        "channel": "Canal",
        "automatic_captions": {"pt-orig": [{"ext": "vtt", "url": "u"}]},
    }
    fake_ydl.body = (VTT + "\n00:00:06.000 --> 00:00:09.000\n" + "conteúdo relevante " * 10).encode()
    tr = youtube.fetch_transcript("https://www.youtube.com/watch?v=LjVZpvGT7Mw", max_seconds=1800)
    assert tr["ok"] and tr["title"] == "Vídeo" and tr["channel"] == "Canal" and tr["duration_sec"] == 600
    assert "Ollama & agentes" in tr["transcript"]


def test_fetch_transcript_too_long_is_permanent(fake_ydl):
    fake_ydl.info = {"duration": 5000}
    tr = youtube.fetch_transcript("https://www.youtube.com/watch?v=LjVZpvGT7Mw", max_seconds=1800)
    assert not tr["ok"] and not tr["transient"]


def test_fetch_transcript_without_captions_is_permanent(fake_ydl):
    fake_ydl.info = {"duration": 600}
    tr = youtube.fetch_transcript("https://www.youtube.com/watch?v=LjVZpvGT7Mw", max_seconds=1800)
    assert not tr["ok"] and not tr["transient"]


def test_fetch_transcript_rate_limit_is_transient(fake_ydl):
    fake_ydl.raise_on_extract = DownloadError("ERROR: HTTP Error 429: Too Many Requests")
    tr = youtube.fetch_transcript("https://www.youtube.com/watch?v=LjVZpvGT7Mw", max_seconds=1800)
    assert not tr["ok"] and tr["transient"]


def test_fetch_transcript_private_video_is_permanent(fake_ydl):
    fake_ydl.raise_on_extract = DownloadError("ERROR: Private video")
    tr = youtube.fetch_transcript("https://www.youtube.com/watch?v=LjVZpvGT7Mw", max_seconds=1800)
    assert not tr["ok"] and not tr["transient"]
