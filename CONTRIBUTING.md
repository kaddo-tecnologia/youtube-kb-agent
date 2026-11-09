# Como contribuir

Obrigado pelo interesse. PRs pequenos e focados são revisados mais rápido.

## Ambiente

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m ytkb --data-dir ./dev-data --port 8780
```

Use sempre `--data-dir` em desenvolvimento para não misturar com as suas bases reais.

## Antes de abrir o PR

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m pytest -q
npm test
npm pack --dry-run   # confira que nenhum arquivo extra entrou no pacote
```

- Toda mudança de comportamento vem com teste. Testes não acessam rede: use os fakes de `tests/conftest.py` e `tests/test_youtube.py`.
- Testes que precisam de Ollama ou YouTube reais levam `@pytest.mark.integration` e não rodam no CI.
- Mudou comportamento, opção ou variável de ambiente? Atualize o `README.md` e, se for estrutural, o `docs/ARCHITECTURE.md`.
- Registre a mudança em `CHANGELOG.md` na seção "Não publicado".

## Regras do projeto

- **Sem dependências novas sem discussão em issue.** O objetivo é instalar com um comando e rodar em máquinas modestas.
- **Nada de rede no painel:** sem CDN, fontes externas ou analytics. Bibliotecas JS ficam em `ytkb/web/vendor/` com versão e licença.
- **Painel sem handlers inline** (`onclick=` etc.) e todo HTML vindo de Markdown passa por `DOMPurify.sanitize`. Os testes verificam isso.
- **Conteúdo de vídeo é dado, nunca instrução.** Novo prompt deve usar `_wrap()` e `UNTRUSTED_RULE` de `ytkb/synth.py`.
- **Caminhos derivados de entrada** passam por `slugify()` e `Paths.kb_file()` / `Paths.skill_file()`.
- Mudanças em `ytkb/server.py`, `ytkb/synth.py` (lint e prompts) ou `bin/cli.js` recebem revisão extra de segurança.

## Ideias bem-vindas

Veja as issues com `good first issue` e `help wanted`. Algumas direções: provedores compatíveis com a API da OpenAI (LM Studio, llama.cpp server), seleção de seções por embeddings para bases grandes, lista de canais permitidos/bloqueados, painel em inglês, export para Obsidian, playlists e canais como fonte.
