# YouTube Knowledge Agent

Agente local que assiste vídeos do YouTube sobre um assunto que você escolhe, consolida tudo em **uma base de conhecimento única em Markdown** (sem repetir o que já sabe) e transforma essa base em **Skills (`SKILL.md`)** para agentes de IA como Claude Code e Cursor.

Roda 100% na sua máquina: a LLM é local via [Ollama](https://ollama.com) e o YouTube é lido via [yt-dlp](https://github.com/yt-dlp/yt-dlp). Sem chave de API, sem custo.

```bash
npx @kaddo-tecnologia/youtube-kb-agent
```

---

## O que ele faz

- **Estuda sozinho em segundo plano:** busca vídeos do assunto, lê só a legenda (não baixa o vídeo) e gera novas buscas para explorar ângulos complementares.
- **Extração diferencial:** cada vídeo novo é comparado com a base. Se não traz nada novo, nada é reescrito (`NADA_NOVO`). Se traz, só o inédito é integrado na seção certa.
- **Uma base por assunto:** trocar o assunto cria `knowledge/<assunto>.md` e preserva as bases anteriores.
- **Link manual:** cole qualquer link do YouTube no painel para estudar aquele vídeo agora (fila com até 10 links).
- **Fábrica de Skills:** um clique converte a base em `skills/<assunto>/SKILL.md`.
- **Tempo de execução:** contínuo até você parar, ou com timer (15 min a 4 h, ou personalizado).

## Requisitos

| Item | Versão | Observação |
| --- | --- | --- |
| Node.js | 18.17+ | Só para o comando `npx` |
| Python | 3.10+ | O `npx` cria um ambiente isolado; não mexe no seu Python global |
| Ollama | atual | Com um modelo de chat: `ollama pull qwen3.5:9b` |
| ffmpeg | opcional | Não é necessário no modo padrão |

Referência medida: RTX 3060 12 GB rodando `qwen3.5:9b` com `num_ctx` 16384 usa cerca de 6 GB de VRAM. Cada vídeo leva de 1 a 2 minutos (legenda em ~2 s, o resto é a LLM).

## Instalação e uso

```bash
ollama pull qwen3.5:9b
npx @kaddo-tecnologia/youtube-kb-agent
```

Na primeira execução o comando cria um ambiente Python em `~/.youtube-kb-agent/venv` e instala o yt-dlp. Depois abre o painel em `http://127.0.0.1:8765`.

No painel:

1. Defina o **assunto**, a duração máxima dos vídeos e as diretrizes de estudo. Clique em **Salvar Regras**.
2. Escolha contínuo ou timer e clique em **Ativar Agente**.
3. Acompanhe a telemetria e a base sendo escrita em tempo real.
4. Quando a base estiver boa, clique em **Criar / Atualizar Skill**.

### Opções

```text
--data-dir <pasta>  Onde ficam os dados (padrão: ~/.youtube-kb-agent)
--port <n>          Porta do painel (padrão: 8765)
--no-open           Não abrir o navegador
--update            Reinstala dependências e atualiza o yt-dlp para a versão mais recente
doctor              Diagnóstico: Python, yt-dlp, Ollama e modelos
```

### Variáveis de ambiente

| Variável | Padrão | Uso |
| --- | --- | --- |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Endereço do Ollama. Aceita o formato do próprio Ollama. |
| `OLLAMA_MODEL` | `qwen3.5:9b` | Modelo preferido. Sem ele, usa outro `qwen*` ou o primeiro modelo de chat. |
| `OLLAMA_NUM_CTX` | `16384` | Janela de contexto. Os limites de texto enviados à LLM são calculados a partir dela. |
| `YTKB_DATA_DIR` | `~/.youtube-kb-agent` | Mesmo que `--data-dir`. |
| `PORT` | `8765` | Mesmo que `--port`. |

### Onde ficam seus dados

```text
~/.youtube-kb-agent/
  REGRAS.md                 # assunto, duração máxima e diretrizes (editável à mão)
  knowledge/<assunto>.md    # base consolidada + lista de fontes
  knowledge/state.json      # vídeos processados, pulados e buscas feitas
  skills/<assunto>/SKILL.md # skills geradas
  venv/                     # ambiente Python do agente
```

O pacote npm nunca guarda dados: atualizar ou limpar o cache do npx não apaga suas bases.

## Segurança

Leia antes de usar. O resumo do modelo de ameaça está em [SECURITY.md](./SECURITY.md).

- **O painel só escuta em `127.0.0.1`** e recusa requisições com `Host` ou `Origin` estranhos ou sem `Content-Type: application/json`. Isso bloqueia sites maliciosos abertos no seu navegador (CSRF e DNS rebinding). Não exponha a porta na rede: o painel não tem login.
- **Transcrições são conteúdo não confiável.** Um vídeo pode conter texto feito para manipular a LLM (prompt injection). Por isso:
  - todo Markdown exibido no painel passa por sanitização (DOMPurify) e uma Content Security Policy estrita;
  - os prompts marcam transcrições como dados, nunca instruções;
  - **toda Skill sai com um aviso de revisão** e uma lista de trechos suspeitos (comandos que baixam e executam scripts, URLs externas, tentativas de injection).
- **Revise cada `SKILL.md` antes de instalar em um agente.** Uma skill é um conjunto de instruções que o seu agente vai seguir. Ela nunca é instalada automaticamente.
- Se `OLLAMA_HOST` apontar para outra máquina, as transcrições e bases são enviadas para ela. O agente avisa no log quando isso acontece.

## Uso responsável

Este projeto lê legendas públicas para estudo pessoal. Respeite os [Termos de Serviço do YouTube](https://www.youtube.com/t/terms) e os direitos dos criadores: as bases geradas são derivadas do trabalho deles. Use para aprender, cite as fontes (a lista de vídeos fica no fim de cada base) e não republique o conteúdo como se fosse seu. O agente espera cada vez mais entre buscas sem resultado novo para não sobrecarregar o YouTube.

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `Python 3.10+ não encontrado` | Python ausente do PATH | Instale em python.org e marque "Add to PATH" |
| `Ollama indisponível` | Ollama desligado | `ollama serve` ou abra o app do Ollama |
| `Nenhum modelo de chat instalado` | Só há modelos de embedding | `ollama pull qwen3.5:9b` |
| Muitos vídeos `Pulado (Vídeo sem legendas)` | Criadores desativaram legendas | Normal: esses vídeos são pulados e o agente segue para os próximos |
| `HTTP Error 429` no log | YouTube limitando requisições | O agente espera e tenta de novo; reduza o ritmo ou rode `--update` |
| Busca parou de funcionar | Mudança no YouTube | `npx @kaddo-tecnologia/youtube-kb-agent --update` |
| `Porta 8765 em uso` | Outra instância aberta | Feche a outra ou use `--port 8780` |
| Base parou de ser reescrita e só ganha "Complementos" | Base maior que a janela de contexto | Normal; aumente `OLLAMA_NUM_CTX` se tiver VRAM ou divida o assunto |

## Desenvolvimento

```bash
git clone https://github.com/kaddo-tecnologia/youtube-kb-agent.git
cd youtube-kb-agent
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m ytkb --data-dir ./dev-data
.venv/Scripts/python -m pytest -q
npm test
```

Arquitetura, threads e orçamento de contexto: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md). Como contribuir: [CONTRIBUTING.md](./CONTRIBUTING.md).

## Créditos

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (busca e legendas), [Ollama](https://ollama.com) (LLM local)
- [marked](https://github.com/markedjs/marked) e [DOMPurify](https://github.com/cure53/DOMPurify), incluídos em `ytkb/web/vendor/` com suas licenças
- A primeira versão usava o pipeline [bradautomates/claude-video](https://github.com/bradautomates/claude-video), que inspirou o fluxo de transcrição

## Licença

[MIT](./LICENSE)
