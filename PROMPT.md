# Prompt de arranque para o Claude Code

Copiar tudo abaixo da linha e colar na primeira sessão, com o `CLAUDE.md`,
o `docs/rules.md` e o `scripts/pin.sh` já no repo.

Não colar isto de uma vez esperando que saia tudo pronto. Está dividido em
marcos por uma razão: cada um termina numa coisa executável e testável, e é
onde se revê antes de seguir.

---

Estamos a arrancar o **arcet**, uma CLI em Go para auditoria estática de
workflows de CI/CD. Lê primeiro o `CLAUDE.md` e o `docs/rules.md` na raiz —
contêm as invariantes do produto e as decisões já fechadas. Não as reabras.

Três coisas antes de escreveres código:

1. Se alguma tarefa parecer exigir violar uma invariante do `CLAUDE.md`
   (executar workflows, fazer rede, escrever nos ficheiros analisados), **para
   e pergunta**. Não contornes.
2. Nunca escrevas um SHA de commit que não tenhas resolvido. Se precisares de
   um pin, usa `./scripts/pin.sh owner/repo tag`. Placeholder visível é
   sempre melhor do que um hash inventado.
3. Trabalhamos por marcos. Termina um, para, e espera revisão antes do
   seguinte.

## Marco 0 — esqueleto

Objectivo: `arcet --version` corre.

- `go mod init` com o module path `arcet.dev/arcet` (temos o domínio; isto
  sobrevive a mudanças de repo ou de org)
- Estrutura de pastas conforme o `CLAUDE.md`
- `cmd/arcet/main.go` com parsing de flags: `--format`, `--output`,
  `--fail-on`, `--config`, `--version`, `--help`
- O contrato de exit codes implementado e centralizado num sítio: 0 limpo,
  1 findings acima do limiar, 2 erro da ferramenta, 3 erro de configuração
- `.gitignore`, `LICENSE` (Apache-2.0), `go.mod`

Não implementes regras nenhumas neste marco.

## Marco 1 — parsing com posição

Objectivo: dado um ficheiro de workflow, produzir uma árvore navegável onde
qualquer nó sabe a sua linha e coluna.

- `internal/workflow/` usando `yaml.Node` do `gopkg.in/yaml.v3`
- **Não** faças unmarshal para structs. A posição é o produto — ver o
  `CLAUDE.md`, "Restrição técnica central"
- Helpers para navegar o que interessa: jobs, steps, `uses:`, `run:`, `on:`,
  `permissions:`, `env:`
- YAML inválido → erro com ficheiro e linha, exit 2, nunca panic
- `testdata/` com workflows reais, incluindo casos feios: âncoras, matrizes,
  strings multilinha, `on:` nas três formas (string, lista, mapa)

## Marco 2 — findings e relatórios

Objectivo: emitir um finding inventado nos três formatos.

- `internal/finding/`: tipo `Finding` com ID, severidade, mensagem, ficheiro,
  linha, coluna, excerto de evidência, `helpUri`
- `internal/report/`: `text`, `json`, `sarif`
- O SARIF tem de ser 2.1.0 válido e conter `properties.security-severity`
  conforme a tabela em `docs/rules.md` — sem isso o GitHub não mostra o escalão
- Valida o SARIF contra o schema num teste. Não confies em inspecção visual.

## Marco 3 — primeiras regras

Objectivo: valor real no caso mais comum.

- `internal/rule/`: interface `Rule` e registo
- Implementa por esta ordem: `supply/unpinned-action`, `supply/mutable-ref`,
  `perms/write-all`, `perms/missing-block`
- Cada regra traz caso positivo **e** negativo em `testdata/`
- Cada regra traz a sua página em `docs/rules/<categoria>/<nome>.md`, que é
  para onde o `helpUri` aponta

## Marco 4 — a categoria `agent/`

**É este o produto.** Os marcos anteriores são infra-estrutura para chegar
aqui; o zizmor e o poutine já fazem o resto.

- `internal/rule/agent/detect.go`: heurística única e partilhada para
  identificar um agente de AI num workflow (actions conhecidas, CLIs de
  agentes invocadas em `run:`, configuração de MCP, variáveis de ambiente com
  chaves de LLM). Isto vai mudar muitas vezes — mantém-no num sítio só.
- Conjunto partilhado de contextos controláveis por terceiros, usado tanto por
  `exec/script-injection` como por `agent/untrusted-prompt-injection`
- Implementa `agent/shell-on-untrusted-trigger` primeiro. É a regra de
  referência, a que apanha o padrão Clinejection: agente com shell, accionado
  por evento não confiável, com acesso a credenciais ou cache.
- `testdata/` com uma reconstrução do padrão Clinejection como caso positivo,
  e com agentes legítimos e bem contidos como casos negativos. **Os falsos
  positivos aqui custam-nos a credibilidade toda** — se marcarmos como crítico
  cada agente bem configurado, ninguém nos usa.

## Marco 5 — dogfooding e distribuição

- Preenche os SHAs em `.github/workflows/ci.yml` com o `scripts/pin.sh` e
  confirma que o job `pins` passa
- Confirma que a auto-auditoria passa a limpo
- GoReleaser: binários para linux/darwin/windows em amd64 e arm64, checksums,
  e PR automático para `mtlabs/homebrew-tap` a cada tag
- **Não** submetas ao homebrew-core. Tem critérios de notoriedade que um
  projecto acabado de lançar não cumpre; migra-se quando houver tracção.
- README com o diferenciador acima da dobra: quem chega vai comparar-nos ao
  zizmor e ao poutine nos primeiros trinta segundos, e a resposta a "porquê
  mais um?" é a categoria `agent/`. A atribuição ao Opsyron fica discreta e no
  fim.

---

Começa pelo Marco 0. Quando terminares, para e diz o que fizeste.
