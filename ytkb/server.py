"""Painel HTTP local. Só atende o próprio painel: valida Host, Origin, Content-Type e tamanho do corpo."""
from __future__ import annotations

import json
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent import Agent, BusyError
from .paths import WEB_DIR
from .rules import slugify, write_rules

MAX_BODY = 1024 * 1024
JS = "text/javascript; charset=utf-8"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", JS),
    "/vendor/marked.umd.js": ("vendor/marked.umd.js", JS),
    "/vendor/purify.min.js": ("vendor/purify.min.js", JS),
}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixa outro processo ocupar a mesma porta em silêncio.
    allow_reuse_address = sys.platform != "win32"
    agent: Agent
    allowed_hosts: set[str]
    allowed_origins: set[str]


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = "ytkb"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 - assinatura da stdlib
        return

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _dispatch(self, fn) -> None:
        try:
            # Host fixo bloqueia DNS rebinding (site malicioso apontando seu domínio para 127.0.0.1).
            if (self.headers.get("Host") or "").lower() not in self.server.allowed_hosts:
                raise HttpError(403, "Host não permitido.")
            fn()
        except HttpError as e:
            self.close_connection = True
            self._json({"error": e.message}, e.status)
        except BusyError as e:
            self._json({"error": str(e)}, 409)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._json({"error": "Erro interno. Veja o terminal do agente."}, 500)

    def do_GET(self):  # noqa: N802
        self._dispatch(self._get)

    def do_POST(self):  # noqa: N802
        self._dispatch(self._post)

    def _read_json(self) -> dict:
        origin = self.headers.get("Origin")
        if origin is not None and origin.lower() not in self.server.allowed_origins:
            raise HttpError(403, "Origem não permitida.")
        # Exigir JSON força preflight CORS em navegadores; como não respondemos CORS, outros sites são barrados.
        if self.headers.get_content_type() != "application/json":
            raise HttpError(415, "Use Content-Type: application/json.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise HttpError(400, "Content-Length inválido.") from None
        if length > MAX_BODY:
            raise HttpError(413, "Corpo da requisição grande demais.")
        if length <= 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "JSON inválido.") from None
        if not isinstance(body, dict):
            raise HttpError(400, "O corpo deve ser um objeto JSON.")
        return body

    def _get(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in STATIC:
            name, ctype = STATIC[parsed.path]
            return self._send(200, (WEB_DIR / name).read_bytes(), ctype)
        agent = self.server.agent
        slug = slugify((urllib.parse.parse_qs(parsed.query).get("slug") or [""])[0])
        if parsed.path == "/api/status":
            return self._json(agent.status())
        if parsed.path == "/api/kb":
            path = agent.paths.kb_file(slug)
            if not path.is_file():
                raise HttpError(404, "Base não encontrada.")
            meta = agent.topic_meta(slug)
            return self._json({
                "slug": slug,
                "topic": meta.get("topic", slug),
                "content": path.read_text(encoding="utf-8"),
                "processed_videos": meta.get("processed_videos", []),
                "used_queries": meta.get("used_queries", []),
            })
        if parsed.path == "/api/skill":
            path = agent.paths.skill_file(slug)
            if not path.is_file():
                raise HttpError(404, "Skill ainda não foi gerada para este assunto.")
            return self._json({"slug": slug, "path": f"skills/{slug}/SKILL.md", "content": path.read_text(encoding="utf-8")})
        raise HttpError(404, "Não encontrado.")

    def _post(self) -> None:
        body = self._read_json()
        agent = self.server.agent
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/start":
            minutes = body.get("duration_minutes")
            if minutes is not None and (
                isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 0 <= minutes <= 1440
            ):
                raise ValueError("duration_minutes deve ser um número entre 0 e 1440, ou null.")
            return self._json(agent.start(duration_minutes=minutes or None))
        if path == "/api/stop":
            return self._json(agent.stop())
        if path == "/api/rules":
            rules = write_rules(
                agent.paths.rules,
                topic=body.get("topic", ""),
                max_minutes=body.get("max_minutes", 30),
                guidelines=body.get("guidelines") or "",
            )
            agent.ensure_kb_initialized(rules)
            agent.log(f"Regras atualizadas: assunto='{rules['topic']}' (máx {rules['max_minutes']} min)")
            return self._json(agent.status())
        if path == "/api/process-url":
            url = body.get("url")
            if not isinstance(url, str) or len(url) > 500:
                raise ValueError("URL inválida.")
            return self._json(agent.submit_url(url))
        if path == "/api/create-skill":
            slug = body.get("slug")
            if slug is not None and not isinstance(slug, str):
                raise ValueError("slug deve ser texto.")
            return self._json(agent.create_skill(slug or None))
        raise HttpError(404, "Não encontrado.")


def make_server(agent: Agent, port: int = 8765) -> Server:
    """Sempre em 127.0.0.1: o painel não tem login e nunca deve ficar exposto na rede."""
    httpd = Server(("127.0.0.1", port), Handler)
    real_port = httpd.server_address[1]
    httpd.agent = agent
    httpd.allowed_hosts = {f"127.0.0.1:{real_port}", f"localhost:{real_port}"}
    httpd.allowed_origins = {f"http://{h}" for h in httpd.allowed_hosts}
    return httpd
