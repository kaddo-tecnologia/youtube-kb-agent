# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento [SemVer](https://semver.org/lang/pt-BR/).

## Não publicado

## 0.1.0

Primeira versão pública.

### Adicionado
- Instalação com `npx`, venv isolado em `~/.youtube-kb-agent` e comando `doctor`.
- Busca e legendas via yt-dlp como biblioteca (vídeos sem legenda são pulados).
- Fila de links manuais (até 10, sem duplicatas).
- Lint de skills com aviso de revisão obrigatório.

### Segurança
- Painel valida Host, Origin, Content-Type e tamanho do corpo (CSRF, DNS rebinding).
- Markdown sanitizado com DOMPurify, CSP estrita, bibliotecas JS vendorizadas.
- Delimitação de conteúdo não confiável nos prompts.

### Corrigido
- Fusão de bases maiores que o contexto apagava o final da base.
- Gravação concorrente e não atômica de `state.json`; arquivo corrompido zerava o histórico.
- Erro em um vídeo derrubava o loop autônomo inteiro.
- Parar e iniciar rápido criava dois loops simultâneos.
- Busca sem resultados novos repetia a cada 5 s sem espera crescente.
- Bases grandes: comparação agora vê o início e o fim da base, evitando complementos repetidos.
- Vídeo com erro inesperado é pulado após 3 tentativas.
- Geração de busca respeita a trava de uma chamada à LLM por vez.
- Painel só redesenha a base quando o conteúdo muda (seleção de texto não some mais).
- Launcher recria o venv quando ele está quebrado ou foi criado pela metade.
