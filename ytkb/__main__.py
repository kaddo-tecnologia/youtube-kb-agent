"""Ponto de entrada: python -m ytkb [--data-dir DIR] [--port N] [--no-open]."""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .agent import Agent
from .paths import Paths, default_data_dir
from .rules import ensure_rules_file
from .server import make_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="youtube-kb-agent", description="Agente local que estuda vídeos do YouTube.")
    ap.add_argument("--data-dir", type=Path, default=None, help="Pasta dos dados (padrão: ~/.youtube-kb-agent)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    ap.add_argument("--no-open", action="store_true", help="Não abrir o navegador")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    paths = Paths((args.data_dir or default_data_dir()).expanduser().resolve())
    paths.ensure()
    ensure_rules_file(paths.rules)
    agent = Agent(paths)
    try:
        httpd = make_server(agent, args.port)
    except OSError as exc:
        print(f"Não foi possível abrir a porta {args.port} ({exc}). Use --port <outra>.", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    print(f"Dados em: {paths.root}\nPainel:   {url}   (Ctrl+C para sair)", flush=True)
    if not args.no_open:
        webbrowser.open(url)  # servidor já está escutando: sem corrida com o navegador
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Encerrando...", flush=True)
    finally:
        agent.stop("Servidor encerrado.")
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
