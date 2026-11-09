# Política de Segurança

## Como reportar uma vulnerabilidade

Não abra issue pública. Use **Security > Report a vulnerability** neste repositório (GitHub Private Vulnerability Reporting). Inclua passos para reproduzir, impacto e versão (`npx @kaddo-tecnologia/youtube-kb-agent --version`).

Resposta inicial em até 7 dias. Correções de segurança saem como versão patch, com crédito a quem reportou, se desejar.

## Versões suportadas

Apenas a versão mais recente publicada no npm recebe correções.

## Escopo

Interessam especialmente:

- Qualquer forma de uma página web ler ou alterar o painel local (CSRF, DNS rebinding, XSS).
- Conteúdo de vídeo que faça o agente executar comandos, gravar fora da pasta de dados ou gerar uma Skill maliciosa sem aviso.
- Problemas no launcher `npx` (execução de código não esperado, caminhos, dependências).

O modelo de ameaça completo está em [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md#modelo-de-ameaça).

## O que não é vulnerabilidade

- Expor a porta do painel na rede de propósito (o painel não tem autenticação e só escuta em `127.0.0.1`).
- Um processo local já rodando com o seu usuário.
- Qualidade ou veracidade do conteúdo resumido pela LLM.
