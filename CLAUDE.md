# arcet

CLI de auditoria estática de workflows de CI/CD, a começar pelo GitHub Actions.
Go, binário estático, sem dependências de runtime.

Do latim *arcēre* — manter fora, conter. Raiz de *arx* (cidadela) e *arcanum*.

## O que isto é

Lê `.github/workflows/*.yml`, aplica regras, emite findings com evidência
(ficheiro, linha, coluna, excerto). Um repo, uma execução, sem estado.

## O que isto NÃO é, em nenhuma circunstância

Estas são invariantes do produto, não preferências. Se uma tarefa parecer
exigir violar uma delas, **para e pergunta** em vez de contornar.

- **Não executa nada.** Nem os workflows, nem os scripts que eles contêm, nem
  as actions. Análise puramente estática sobre a árvore YAML.
- **Não faz rede por omissão.** Sem telemetria, sem "check for updates", sem
  resolver actions remotamente, sem enviar findings para lado nenhum. Se
  alguma funcionalidade futura precisar de rede, é opt-in explícito por flag e
  documentada como tal.
- **Não escreve nos ficheiros analisados** a não ser que exista um `--fix`
  explícito (que não faz parte da v0.1).
- **Não requer autenticação** para funcionar no caso base.

Isto é o argumento de confiança da ferramenta. É a razão pela qual alguém a
corre num repo privado. Não se negoceia por conveniência.

## Decisões fechadas

Foram debatidas e estão decididas. Não as reabras sem ser pedido.

### IDs de regras — semânticos, com prefixo de categoria

Formato: `categoria/nome-em-kebab-case`

```
supply/unpinned-action
perms/write-all
trigger/pull-request-target-checkout
agent/shell-on-untrusted-trigger
```

Estes IDs vão parar a comentários de supressão e a configurações de CI de
terceiros. **São contrato público a partir da v0.1.** Renomear uma regra parte
pipelines alheios: se for mesmo preciso, mantém-se o ID antigo como alias
depreciado, nunca se remove sem major bump.

Categorias em `docs/rules.md`.

### Exit codes

| Código | Significado |
|--------|-------------|
| `0` | Análise concluída, nada acima do limiar |
| `1` | Análise concluída, findings acima do limiar |
| `2` | Erro da ferramenta (YAML inválido, ficheiro ilegível, panic recuperado) |
| `3` | Erro de configuração ou de argumentos |

**Nunca confundir `1` com `2`.** "Encontrei problemas" e "rebentei" são coisas
diferentes; quem nos puser no CI depende dessa distinção.

### SARIF desde a v0.1

`--format sarif` produz SARIF 2.1.0. Não é feature de v1, é fundacional — o
GitHub ingere SARIF nativamente, o que põe os nossos findings no separador
Security sem integração nenhuma. Acrescentar isto depois obrigaria a refazer a
camada de findings.

Detalhes que importam para o code scanning do GitHub:
- `ruleId` = o ID semântico
- `level` = `error` | `warning` | `note`
- `properties.security-severity` = string numérica "0.0"–"10.0"; é o que faz o
  GitHub mostrar Critical/High/Medium/Low
- `helpUri` a apontar para a documentação da regra

Formatos de saída: `text` (omissão, legível por humanos), `json`, `sarif`.

### Supressão inline

```yaml
# arcet: ignore agent/shell-on-untrusted-trigger -- agente corre em fork isolado
```

A razão a seguir a `--` é **obrigatória**. Uma supressão sem justificação é
rejeitada com erro de configuração. Supressões sem razão apodrecem.

### Configuração

`.arcet.yml` na raiz do repo. Tudo opcional; a ferramenta funciona sem
configuração nenhuma.

## Arquitectura

```
cmd/arcet/           entrypoint, parsing de flags, exit codes
internal/workflow/   parsing do YAML preservando posição
internal/rule/       interface Rule + registo
internal/rule/supply/
internal/rule/perms/
internal/rule/trigger/
internal/rule/secret/
internal/rule/exec/
internal/rule/agent/   — o diferenciador
internal/finding/    tipo Finding, severidade, evidência
internal/report/     text, json, sarif
docs/rules/          uma página por regra, serve de helpUri
```

### Restrição técnica central: evidência posicional

Todo o finding tem de apontar para ficheiro, linha e coluna. Isso obriga a usar
`yaml.Node` do `gopkg.in/yaml.v3`, que preserva `Line` e `Column`, e **não**
unmarshalling directo para structs, que descarta a posição.

Se em algum momento for tentador fazer unmarshal para struct "só para esta
regra": não. A evidência é metade do produto. Um linter de segurança que diz
"tens um problema algures neste ficheiro" não é usado por ninguém.

### Dependências

Mínimas e justificadas. Cada nova dependência é superfície de ataque numa
ferramenta de supply chain, e a ironia não passaria despercebida a ninguém.
Neste momento: `gopkg.in/yaml.v3` e a biblioteca padrão. Para acrescentar
outra, pergunta primeiro.

## Dogfooding — regra dura

Os nossos próprios workflows têm de passar na nossa própria auditoria, e há um
job de CI que falha se não passarem.

Isto significa, em `.github/workflows/`:
- todas as actions com pin de SHA completo de 40 caracteres, com o tag em
  comentário ao lado
- bloco `permissions:` explícito e mínimo em cada job
- zero `pull_request_target`
- zero interpolação directa de contexto do GitHub dentro de blocos `run:`

Uma ferramenta que audita workflows e cujos workflows não passam na auditoria
está morta à nascença. O primeiro issue que abrirem contra nós vai ser esse.

Para resolver SHAs: `scripts/pin.sh actions/checkout v4.2.2`

## Convenções de código

- Erros embrulhados com contexto: `fmt.Errorf("parse %s: %w", path, err)`
- Sem `panic` em caminho de biblioteca; `cmd/` recupera e converte em exit 2
- Tabelas de teste com ficheiros YAML reais em `testdata/`
- Toda a regra nova traz: implementação, testes com caso positivo **e**
  negativo, e a página em `docs/rules/`
- Comentários em inglês (o projecto é público e internacional); esta conversa
  e o CLAUDE.md em português

## Posicionamento

"O linter de CI para a era dos agentes."

As regras clássicas (`supply/`, `perms/`, `trigger/`, `secret/`, `exec/`) são
mesa posta — o zizmor, o poutine e o octoscan já as fazem. **O diferenciador é
a categoria `agent/`**, que não existe em mais lado nenhum: agentes de AI a
correr em CI, accionados por eventos não confiáveis, com acesso a shell e a
credenciais.

O caso de referência é o padrão "Clinejection" (Fev 2026): um agente com
acesso a shell, accionado por issues, que levou a envenenamento de cache e a
roubo de tokens npm. A regra `agent/shell-on-untrusted-trigger` existe para
apanhar exactamente essa forma.

Quando houver dúvida sobre onde investir esforço, investe-se na categoria
`agent/`.

## Atribuição

O README faz atribuição ao Opsyron Security da MTLabs, **discreta e no fim**.
O arcet é um projecto próprio e independente, não uma demo. Um README de open
source com ar de funil de vendas queima a adopção que estamos a construir.
Não puxes o Opsyron para cima nem o menciones em `--help`, em mensagens de
erro, ou em qualquer sítio no caminho do utilizador.
