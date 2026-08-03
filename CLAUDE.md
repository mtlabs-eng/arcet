# arcet

CLI open source em Python que responde a uma pergunta sobre Azure:

> o que é que esta identidade consegue fazer, na prática, e porquê?

O output não é uma lista de atribuições. É a lista de permissões **efectivas**,
cada uma acompanhada da **cadeia de derivação** que a justifica.

```
$ arcet whocan user@empresa.pt --subscription <id>

Microsoft.KeyVault/vaults/secrets/read        ✓ activo
  └─ grupo "Platform" → grupo "SRE" (aninhado)
     └─ papel "Key Vault Secrets User" @ /subscriptions/xxx/rg-prod

Microsoft.Authorization/roleAssignments/write ⚠ elegível (PIM)
  └─ papel "User Access Administrator" @ /subscriptions/xxx
```

**A cadeia é o produto.** Se o output não explicar *porquê*, a ferramenta não
vale nada — o portal do Azure já mostra permissões sem explicação, e é esse o
problema que existimos para resolver.

## O que isto NÃO é

Invariantes do produto, não preferências. Não se re-litigam. Se uma tarefa
parecer exigir violar uma delas, **para e pergunta** em vez de contornar.

- **Não é um linter.** Não emite findings, não tem regras, não tem
  severidades, não tem IDs de regra, não produz SARIF.
- **Não faz scoring nem recomendações.** Reporta factos verificáveis. Não
  ordena por risco, não sugere remediações, não diz o que está "mal".
- **Não escreve nada no Azure.** Credenciais só de leitura, nunca Owner.
  Qualquer código que chame uma API de escrita é um bug, não uma feature.
- **Não guarda estado entre execuções.** Uma identidade, um run, sem estado.
  Sem cache em disco, sem base de dados, sem ficheiros de sessão.
- **Não é multi-cloud.** Azure apenas. Sem roadmap público de AWS ou GCP.
- **Não usa AI nem LLM em runtime.** A resolução é determinística e
  repetível: o mesmo input dá sempre o mesmo output.

## Precisão é a propriedade central

Uma ferramenta de permissões efectivas que erra em silêncio é pior do que não
existir. Quem a corre vai tomar decisões de acesso com base no que ela diz.

**Regra absoluta:** quando encontrares uma construção que o arcet não sabe
resolver — deny assignments, condições ABAC, herança de management groups, ou
qualquer outra — **nunca a ignores em silêncio**. Emite um aviso explícito no
output a dizer que foi detectada e não é interpretada, e que o resultado pode
estar incompleto.

Silêncio aqui é o pior erro possível. Um resultado incompleto que se anuncia
como incompleto é utilizável; um resultado incompleto que se apresenta como
completo é uma armadilha.

Isto tem consequências práticas no código:

- O caminho de resolução nunca faz `except: pass`, nunca descarta um campo que
  não reconhece, e nunca assume que uma lista vazia significa "não há".
- Toda a construção não suportada vira um `UnsupportedConstruct` em
  `ResolutionResult.warnings`, e os renderers **têm** de a mostrar.
- Um `ResolutionResult` com avisos nunca é apresentado como se não os tivesse.

## Modelo de dados

A peça central. Está desenhado; não o redesenhes sem ser pedido.

```python
class IdentityKind(StrEnum):     USER, SERVICE_PRINCIPAL
class PermissionState(StrEnum):  ACTIVE, PIM_ELIGIBLE
class ActionKind(StrEnum):       CONTROL_PLANE, DATA_PLANE
class DerivationKind(StrEnum):   GROUP_MEMBERSHIP, ROLE_ASSIGNMENT, PIM_ELIGIBLE,
                                 SCOPE_INHERITANCE, DIRECT_ASSIGNMENT
class UnsupportedConstructKind(StrEnum):
                                 DENY_ASSIGNMENT, ABAC_CONDITION,
                                 MANAGEMENT_GROUP_INHERITANCE,
                                 INSUFFICIENT_READ_ACCESS, UNRECOGNISED

DerivationStep:        kind, label (legível), ref (id canónico do Azure)
EffectivePermission:   action, action_kind, state, scope, derivation
IdentityRef:           object_id, display_name, kind
UnsupportedConstruct:  kind, message, ref
ResolutionResult:      identity, subscription, permissions, warnings
```

Decisões já tomadas sobre o modelo:

- **Estruturas imutáveis.** `frozen=True, slots=True`, e sequências como
  `tuple`, não `list`. Resultados hashable tornam a deduplicação trivial e
  nenhum renderer pode mutar o que recebeu.
- **`UnsupportedConstruct`, não `Warning`.** `Warning` é um builtin do Python
  e herdar o nome dá colisões reais em `except`. O campo continua a chamar-se
  `warnings`.
- **`action_kind` distingue control plane de data plane.** Ler as propriedades
  de um segredo (`Microsoft.KeyVault/vaults/secrets/read`) e ler o *valor* do
  segredo (`dataActions`) são papéis diferentes. Colapsar os dois na mesma
  linha é exactamente o erro silencioso que dissemos não cometer.
- **A mesma acção por dois caminhos dá duas entradas.** Reportamos factos, não
  resumos. A tabela agrupa por acção e mostra as duas cadeias. Fundi-las
  obrigaria a eleger uma cadeia "melhor", e isso já é scoring.
- **`derivation` é ordenada, do sujeito até à origem.** É a ordem por que se
  lê em voz alta: "o utilizador está no grupo X, que está no grupo Y, que tem
  o papel Z neste âmbito".
- **Uma permissão sem cadeia é irrepresentável.** `derivation` vazia levanta
  `ValueError` na construção. A cadeia é o produto; um `EffectivePermission`
  que não a tenha é uma afirmação sem prova, e não deve chegar a existir na
  memória, quanto mais ao output.
- **`PIM_ELIGIBLE` exige um passo `PIM_ELIGIBLE` na cadeia.** Também validado
  na construção. Marcar algo como elegível sem o justificar é o erro que mais
  cara custa a quem lê.
- **Ordenação canónica na construção.** O `ResolutionResult` ordena e
  desduplica as permissões ao ser criado. O determinismo é invariante do
  produto, e assim não depende de cada renderer se lembrar de ordenar. A
  desduplicação é só de duplicados exactos — cadeias diferentes para a mesma
  acção continuam a ser entradas distintas.

### PIM elegível e activo

**Têm de ser visualmente distintos no output, em todos os formatos.** É a
diferença entre "tem acesso" e "pode ter daqui a cinco minutos", e é onde a
maioria das ferramentas engana quem as lê.

### notActions

Subtraem durante a resolução: a acção simplesmente não aparece na lista. É
construção que sabemos interpretar, logo não gera aviso. Deny assignments são
outra coisa — esses geram aviso, porque não os sabemos resolver no v0.1.

### Limitações do observador

O arcet corre com credenciais só de leitura. Se essas credenciais não puderem
ler as atribuições de papel de um âmbito, ou a pertença a grupos no Graph, o
Azure não devolve erro — devolve **menos linhas**.

Resolver isso para "esta identidade tem menos permissões" seria um resultado
incompleto a apresentar-se como completo, exactamente o que a regra de precisão
proíbe. Não é uma construção não suportada; é uma limitação de quem observa.

Toda a leitura que falhe por permissões, e todo o âmbito que não seja possível
enumerar, gera um `UnsupportedConstruct` de tipo `INSUFFICIENT_READ_ACCESS`.
Entra em M3, com a camada de autenticação.

### Wildcards

Os papéis definem permissões com wildcards (`*`, `Microsoft.KeyVault/*/read`).
Por omissão o arcet **expande-os** para acções concretas, consultando o
catálogo `Microsoft.Authorization/providerOperations` (leitura apenas). É o que
responde de facto a "o que consegue fazer na prática".

`--no-expand` mostra o padrão literal. Existe porque a expansão depende de um
catálogo que a Microsoft actualiza: o mesmo tenant, noutro dia, pode dar mais
linhas. Isso não viola o determinismo — o catálogo é input, e o output continua
a ser função do input — mas quem precisar de comparar dois runs à distância de
semanas vai querer a forma literal.

## Âmbito do v0.1

Um comando: `whocan`. Uma identidade (utilizador ou service principal). Uma
subscrição de cada vez. Output em tabela e em JSON.

**Fora do v0.1, e a dizer explicitamente no README:**

- grupos como sujeito (só identidades individuais)
- tenant inteiro (uma subscrição de cada vez)
- deny assignments
- condições ABAC
- herança de management groups

Os quatro últimos, quando detectados, geram aviso. Não são ignorados.

## Stack

- Python, gerido com `uv`
- CLI com Typer (Click por baixo, com Rich para a árvore de derivação)
- SDK oficial do Azure: `azure-identity`, `azure-mgmt-authorization`,
  `msgraph-sdk` ou equivalente
- `pytest`, com fixtures de dados gravados
- `ruff` para lint e formatação
- Instalável por `uvx arcet` e `pipx install arcet`

## Convenções

- **Os testes nunca chamam o Azure.** Sempre fixtures gravadas. Um teste que
  precise de rede é um teste que não corre no CI de ninguém.
- Toda a construção nova que o resolver não saiba tratar traz o seu
  `UnsupportedConstruct` e um teste que prova que o aviso aparece no output.
- Comentários e nomes em inglês (o projecto é público e internacional); este
  ficheiro e as conversas em português.
- Erros com contexto suficiente para agir: que identidade, que âmbito, que
  chamada.

## Milestones

Um de cada vez. **Para no fim de cada um e espera revisão.**

| | |
|---|---|
| M0 | Estrutura, `pyproject` com uv, ruff, pytest, CI mínimo. Zero lógica de negócio. |
| M1 | Modelo de dados, com testes. Sem Azure ainda. |
| M2 | Renderers de tabela e JSON, alimentados por fixtures em memória. |
| M3 | Camada de leitura do Azure: auth, atribuições, papéis personalizados. |
| M4 | Grupos aninhados e PIM. Detecção e aviso das construções não suportadas. |
| M5 | README com os limites em cima, empacotamento, comando ponta a ponta. |

M2 vem antes de qualquer código de Azure de propósito: a cadeia de derivação
tem de ficar legível antes de existir rede. Se não ficar bonita com fixtures,
o resto não interessa.
