import http.client
import json
import re
import threading
from pathlib import Path

import pytest

from ytkb import server

WEB = Path(__file__).resolve().parent.parent / "ytkb" / "web"


@pytest.fixture
def srv(agent):
    httpd = server.make_server(agent, port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def req(srv, method, path, body=None, headers=None, host=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{port}"}
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r, data


def test_index_has_security_headers(srv):
    r, data = req(srv, "GET", "/")
    assert r.status == 200
    csp = r.getheader("Content-Security-Policy")
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.getheader("X-Content-Type-Options") == "nosniff"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "127.0.0.1.nip.io"])
def test_rejects_foreign_host_dns_rebinding(srv, host):
    r, _ = req(srv, "GET", "/api/status", host=host)
    assert r.status == 403


def test_localhost_host_allowed(srv):
    r, data = req(srv, "GET", "/api/status", host=f"localhost:{srv.server_address[1]}")
    assert r.status == 200
    assert "rules" in json.loads(data)


def test_rejects_cross_origin_post(srv):
    r, _ = req(srv, "POST", "/api/stop", {}, headers={"Origin": "http://evil.example"})
    assert r.status == 403


def test_same_origin_post_ok(srv):
    r, _ = req(srv, "POST", "/api/stop", {}, headers={"Origin": f"http://127.0.0.1:{srv.server_address[1]}"})
    assert r.status == 200


def test_rejects_simple_request_content_type(srv):
    r, _ = req(srv, "POST", "/api/stop", b"{}", headers={"Content-Type": "text/plain"})
    assert r.status == 415


def test_rejects_large_body(srv):
    # Declara 2 MB e envia pouco: o servidor tem que recusar antes de ler o corpo.
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.putrequest("POST", "/api/rules", skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{srv.server_address[1]}")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Content-Length", str(2 * 1024 * 1024))
    conn.endheaders(b"{}")
    assert conn.getresponse().status == 413
    conn.close()


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/rules", b"{nao json"),
        ("/api/rules", {"topic": "ok", "max_minutes": "abc"}),
        ("/api/rules", {"topic": "", "max_minutes": 30}),
        ("/api/rules", {"topic": ["lista"], "max_minutes": 30}),
        ("/api/start", {"duration_minutes": "abc"}),
        ("/api/start", {"duration_minutes": -5}),
        ("/api/process-url", {"url": "https://evil.example"}),
        ("/api/create-skill", {"slug": 123}),
    ],
)
def test_bad_input_returns_400(srv, path, body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    r, data = req(srv, "POST", path, raw, headers={"Content-Type": "application/json"})
    assert r.status == 400
    assert "error" in json.loads(data)


def test_rules_update(srv, agent):
    r, data = req(srv, "POST", "/api/rules", {"topic": "Novo Tema", "max_minutes": 15, "guidelines": "- g"})
    assert r.status == 200
    assert json.loads(data)["rules"]["slug"] == "novo-tema"
    assert "Novo Tema" in agent.paths.rules.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["/api/kb?slug=../../etc/passwd", "/vendor/../server.py", "/agent.py", "/api/skill?slug=x"])
def test_no_traversal_or_unknown_files(srv, path):
    r, _ = req(srv, "GET", path)
    assert r.status == 404


def test_static_assets_served(srv):
    for path in ("/app.js", "/vendor/marked.umd.js", "/vendor/purify.min.js"):
        r, _ = req(srv, "GET", path)
        assert r.status == 200 and "javascript" in r.getheader("Content-Type")


def test_web_has_no_inline_handlers_or_cdn():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html), "handler inline quebra a CSP"
    assert "<script>" not in html, "script inline quebra a CSP"
    assert "onclick" not in js
    assert not re.search(r"(src|href)=\"https?://", html), "nada de CDN/fonte externa"
    assert "DOMPurify.sanitize" in js
