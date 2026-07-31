# Taxonomia de regras

Formato do ID: `categoria/nome-em-kebab-case`

Os IDs são **contrato público**. Ver `CLAUDE.md`, secção "Decisões fechadas".

## Severidades

Mapeamento entre a severidade interna, o `level` do SARIF e o
`security-severity` que o GitHub usa para mostrar o escalão no code scanning.

| Interna | SARIF `level` | `security-severity` |
|---------|---------------|---------------------|
| critical | `error` | `9.0` |
| high | `error` | `7.0` |
| medium | `warning` | `5.0` |
| low | `note` | `3.0` |

Limiar por omissão para exit code `1`: `medium`.

---

## `agent/` — agentes de AI em CI

**A categoria diferenciadora.** É onde se investe primeiro e melhor.

O modelo de ameaça: um agente de AI num workflow é um interpretador de
instruções vindas de dados. Se esses dados forem controlados por terceiros
(corpo de um issue, comentário, título de PR, diff de um fork) e o agente tiver
acesso a shell, a credenciais ou a cache, o atacante tem execução no vosso CI
sem precisar de commit.

| ID | Severidade | Apanha |
|----|-----------|--------|
| `agent/shell-on-untrusted-trigger` | critical | Agente com execução de shell num workflow accionado por evento não confiável. **A regra de referência — o padrão Clinejection.** |
| `agent/write-token-exposure` | critical | Agente com acesso a token de escrita (`GITHUB_TOKEN` com `write`, `NPM_TOKEN`, chaves de registry) |
| `agent/cache-write-access` | high | Agente capaz de escrever em cache partilhada — vector de envenenamento entre execuções |
| `agent/untrusted-prompt-injection` | high | Contexto controlável por terceiros interpolado no prompt do agente |
| `agent/unpinned-agent-action` | high | A própria action do agente sem pin de SHA |
| `agent/mcp-server-untrusted` | medium | Servidor MCP configurado com origem não fixada ou não verificada |
| `agent/autonomous-commit` | medium | Agente com permissão de commit ou push sem revisão humana |
| `agent/no-network-egress-control` | low | Agente sem restrição de egress declarada |

Sinais para detectar "isto é um agente": actions conhecidas de agentes de
código, invocações de CLIs de agentes dentro de `run:`, configuração de
servidores MCP, variáveis de ambiente com chaves de API de LLM.

Manter a heurística de detecção **num sítio só** (`internal/rule/agent/detect.go`),
não espalhada por cada regra. Vai mudar muitas vezes.

---

## `supply/` — proveniência e cadeia de fornecimento

| ID | Severidade | Apanha |
|----|-----------|--------|
| `supply/unpinned-action` | high | Action referenciada por tag ou branch em vez de SHA |
| `supply/mutable-ref` | high | Referência a `@main`, `@master` ou branch |
| `supply/short-sha` | medium | SHA truncado em vez dos 40 caracteres |
| `supply/missing-tag-comment` | low | Pin de SHA sem o tag em comentário — correcto mas impossível de auditar |
| `supply/untrusted-publisher` | medium | Action de publicador não verificado |

---

## `perms/` — permissões

| ID | Severidade | Apanha |
|----|-----------|--------|
| `perms/write-all` | high | `permissions: write-all` |
| `perms/missing-block` | medium | Sem bloco `permissions:` — herda o default do repo, que pode ser permissivo |
| `perms/excessive-scope` | medium | Scope de escrita concedido mas não usado pelo job |
| `perms/id-token-write` | medium | `id-token: write` sem uso aparente de OIDC |

---

## `trigger/` — eventos perigosos

| ID | Severidade | Apanha |
|----|-----------|--------|
| `trigger/pull-request-target-checkout` | critical | `pull_request_target` com checkout de código do fork. O clássico. |
| `trigger/workflow-run-artifact` | high | `workflow_run` a consumir artefactos de execução não confiável |
| `trigger/issue-comment-unfiltered` | high | `issue_comment` sem verificação de associação do autor |
| `trigger/fork-pr-secrets` | critical | Secrets alcançáveis a partir de PR de fork |

---

## `secret/` — exposição de credenciais

| ID | Severidade | Apanha |
|----|-----------|--------|
| `secret/echo-in-run` | high | Secret ecoado, impresso ou escrito para ficheiro |
| `secret/global-env` | medium | Secret em `env:` global em vez do job ou step que precisa |
| `secret/passed-to-untrusted-action` | high | Secret passado a action de terceiros sem pin |

---

## `exec/` — injecção

| ID | Severidade | Apanha |
|----|-----------|--------|
| `exec/script-injection` | critical | Contexto controlável (`github.event.issue.title` e afins) interpolado em `run:` |
| `exec/unsafe-interpolation` | high | `${{ }}` em posição perigosa dentro de shell |

Manter a lista de contextos controláveis por terceiros num sítio só, partilhada
entre `exec/` e `agent/untrusted-prompt-injection` — é o mesmo conjunto.
