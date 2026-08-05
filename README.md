<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/arcet-logo-dark.svg">
  <img src="assets/brand/arcet-logo.svg" alt="arcet" width="300">
</picture>

### Effective Azure permissions, with the derivation chain that explains them.

**Read-only. No agent. No SaaS. Nothing leaves your machine.**

[![CI](https://github.com/mtlabs-eng/arcet/actions/workflows/ci.yml/badge.svg)](https://github.com/mtlabs-eng/arcet/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB)](https://www.python.org/)
[![Licence](https://img.shields.io/badge/licence-Apache--2.0-D9812F)](LICENSE)
[![Status](https://img.shields.io/badge/status-0.1.0a2%20alpha-8FA3B8)](#how-much-of-this-has-been-proven)
[![Writes to Azure](https://img.shields.io/badge/writes%20to%20Azure-never-2E7D32)](#read-only-by-construction)

</div>

---

The Azure portal will tell you that someone holds a role. It will not tell you
that they can write role assignments on a storage account **because they are in
a group, that is in another group, that holds Owner there**.

arcet answers the second question, and shows its working.

```console
$ arcet whocan alice@example.com --subscription 00000000-1111-2222-3333-444444444444 \
        --action 'Microsoft.Authorization/roleAssignments/write'

⚠  result may be incomplete — 1 construction detected and not interpreted
   • 1 deny assignment in scope was not evaluated; it may remove permissions listed here

alice@example.com  ·  subscription 00000000-1111-2222-3333-444444444444  ·  3 permissions

ACTIVE — 2 permissions ─────────────────────────────────────────────────────────

Microsoft.Authorization/roleAssignments/write
  └─ role "Owner"
     @ /subscriptions/00000000-1111-2222-3333-444444444444

Microsoft.Authorization/roleAssignments/write
  └─ group "Platform" → group "Ops" (nested)
     └─ role "Owner"
        @ /subscriptions/0000…/resourceGroups/demo/providers/Microsoft.Storage/storageAccounts/data

ELIGIBLE VIA PIM — 1 permission ────────────────────────────────────────────────
not held now; can be activated

Microsoft.Authorization/roleAssignments/write
  └─ role "User Access Administrator" (eligible, not active)
     @ /subscriptions/00000000-1111-2222-3333-444444444444
```

**The chain is the product.** A list of permissions without one is a list you
cannot check, argue with, or act on. Every other design decision here follows
from that.

---

## Contents

- [What this does not do](#what-this-does-not-do) — read this first
- [Install](#install)
- [Quick start](#quick-start)
- [Asking a narrow question](#asking-a-narrow-question)
- [Honest comparison](#honest-comparison)
- [Features](#features)
- [Reading the output](#reading-the-output)
- [Permissions needed to run it](#permissions-needed-to-run-it)
- [JSON output](#json-output)
- [Exit codes](#exit-codes)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Development](#development)
- [Licence](#licence)

---

## What this does not do

This section is first on purpose. A permissions tool that is wrong quietly is
worse than no tool at all, so here is exactly where the edges are.

### Detected, reported, **not** interpreted

Each of these produces a visible warning at runtime. None of them is ever
skipped in silence.

| Construction | What arcet does | What that costs you |
|---|---|---|
| **Deny assignments** | Reports that they exist | A permission listed may in fact be denied |
| **ABAC conditions** | Reports the assignment carries one | The grant may be narrower than shown |
| **Management group inheritance** | Reports the grant came from above | That hierarchy is not walked |

### Not in v0.1

- **Groups as the subject.** You ask about a user or a service principal.
- **A whole tenant.** One subscription per run.
- **Resource-level enumeration.** Scopes are reported as Azure states them; arcet does not expand a scope into the resources it covers.

### How much of this has been proven

The test suite is 317 tests and none of them touch the network — by design, so
that everything with judgement in it is covered without a tenant. The cost of
that design is that the network layer is only exercised when someone runs it
for real, and five genuine bugs have already survived a fully green suite.

Where it stands today:

| Path | Exercised against a real tenant |
|---|---|
| Identity lookup, group walk, nested paths | ✅ |
| Role assignments, including group-derived | ✅ |
| Built-in and custom role definitions | ✅ |
| Wildcard expansion and `NotActions` | ✅ |
| Deny assignment detection | ✅ |
| **PIM eligibility and activation** | ❌ **never** — the only tenant tested has no Entra ID P2 |
| **`insufficient_read_access` warnings** | ❌ **never** — the only identity tested could read everything |

The two unproven paths are covered by unit tests and fixtures, and the code is
written to the documented API shapes. That is not the same as knowing it works.
If you run arcet in a tenant with PIM, or with a genuinely restricted identity,
a report either way would be useful.

Coverage sits at **95%** across the modules where the judgement lives — the
model, the group walk, wildcard expansion, the resolver and the renderers.
`reader.py` is excluded from that figure on purpose: it is the thin layer that
only fetches, and covering it with mocks would test the mocks. Its correctness
comes from running arcet for real, which is what the table above reports.

### Read-only by construction

- **It never writes to Azure.** Read-only credentials are enough and Owner is
  never needed. This is not a promise in prose: a test walks the package's
  syntax tree and fails the build if a mutating SDK call, a non-`GET` request,
  or a new `azure-mgmt-*` import appears anywhere.
- **It keeps no state.** One identity, one run. No cache, no database, no
  telemetry, nothing written between runs.
- **No LLM at runtime.** Resolution is deterministic — the same input always
  gives the same output, in the same order.
- **Azure only.** There is no AWS or GCP roadmap.

---

## Install

```console
uvx arcet --help          # run without installing
pipx install arcet        # or install it
```

Requires Python 3.11 or newer. Linux, macOS and Windows: the wheel is pure
Python and CI runs the suite on all three.

> One caveat on Windows. The tests prove the logic runs; they render into a
> buffer, not into a console, so they say nothing about how the box drawing,
> arrows and `⚠` come out in a terminal that is not UTF-8. Windows Terminal is,
> and should be fine. If an older console mangles the output, that is a bug
> worth reporting — and `--format json` is unaffected either way.

> **Every release so far is an alpha.** The version carries an `a` suffix
> because parts of the tool have never run against a real tenant — see
> [how much of this has been proven](#how-much-of-this-has-been-proven).
>
> Note that the suffix **signals** that; it does not **stop** anything.
> `pip` and `uv` skip pre-releases only when a stable version exists to fall
> back to. There is none yet, so a plain `pip install arcet` installs the
> alpha without comment. Read the limits above rather than relying on your
> package manager to enforce them.

From source, for development or to build the wheel yourself:

```console
git clone https://github.com/mtlabs-eng/arcet && cd arcet
uv sync
uv run arcet --help
```

---

## Quick start

Sign in first. arcet uses whatever `DefaultAzureCredential` finds, so `az
login` on a laptop and `AZURE_*` environment variables in a pipeline both work
with no flags.

```console
az login
arcet whocan alice@example.com --subscription <subscription-id>
```

Interactive browser login is deliberately **excluded** from the credential
chain. A missing credential should fail loudly, not open a browser inside a CI
job and hang it.

---

## Asking a narrow question

This is the main way to use arcet, not an extra.

An identity holding `Owner` resolves to **tens of thousands** of concrete
actions. Listing them is not an answer anyone reads. The useful question is
almost always *can this person do X, and why*:

```console
# Can they grant themselves or others more access?
arcet whocan alice@example.com -s <sub> --action 'Microsoft.Authorization/*/write'

# Can they read the actual value of secrets, not just their names?
arcet whocan ci-deployer -s <sub> --action 'Microsoft.KeyVault/vaults/secrets/getSecret/action'

# Can they destroy storage?
arcet whocan alice@example.com -s <sub> --action 'Microsoft.Storage/*/delete'
```

Wildcards behave exactly as Azure's do: `*` spans everything, including path
separators, and matching is case-insensitive.

**Nothing matching is a real answer.** It means no — and the warnings still
tell you how much of the picture was understood before concluding it.

### Why `--expand` is the default

Azure roles are written with wildcards. Expanding them against the provider
operations catalogue is what makes `--action` exact, and it is the **only**
mode that subtracts a role's `NotActions` correctly.

That matters more than it sounds. `Contributor` is `*` minus
`Microsoft.Authorization/*/Write`, minus `elevateAccess`, minus a dozen more.
Without expansion there is nothing concrete to subtract from, so the
unexpanded view prints `*` — **more access than the identity actually has**.

`--no-expand` says so in a warning whenever it happens, and it is genuinely
useful for seeing the shape of the grants at a glance. But the default errs
towards being right.

---

## Honest comparison

arcet is not trying to replace a cloud security platform. It does one thing
and stops. This table is here so you can choose deliberately rather than
discover the gaps later.

| | **arcet** | Azure portal | `az role assignment list` | Commercial CSPM |
|---|---|---|---|---|
| **Effective actions** | Yes, wildcards expanded | No — roles only | No — assignments only | Usually |
| **Explains *why*** | Yes, full chain | No | Principal type only | Varies |
| **Nested group path** | Yes, the whole path | No | No | Some |
| **PIM eligible vs active** | Separate sections, never merged | Separate blades | Not shown | Varies |
| **`NotActions` subtracted** | Yes | n/a | No | Yes |
| **Control vs data plane** | Distinguished per action | Mixed | Mixed | Usually |
| **Deny assignments** | Reported, not evaluated | Listed separately | Separate command | Often evaluated |
| **ABAC conditions** | Reported, not evaluated | Shown | Shown raw | Often evaluated |
| **Management groups** | Reported, not walked | Full hierarchy | Full hierarchy | Full hierarchy |
| **Scope of a run** | One identity, one subscription | Whole tenant | Whole tenant | Whole estate |
| **Where it runs** | Your machine | Browser | Your machine | SaaS, often with an agent |
| **Writes to your tenant** | Never | Yes, if you click | Yes, with other verbs | Varies |
| **Cost** | Free, Apache-2.0 | Included | Included | Paid |
| **Machine-readable output** | JSON with a schema version | No | JSON | API |

If you need deny assignments and ABAC actually evaluated, whole-tenant
coverage, or continuous monitoring, a commercial platform is worth the money.
If you want to answer *"why can this person do that?"* on one identity, right
now, without uploading anything — that is what arcet is for.

---

## Features

**Derivation chains.** Every permission carries an ordered chain from the
subject to the grant. A permission with no chain is not merely discouraged: the
data model refuses to construct one.

**Nested group resolution with paths.** Graph will resolve nesting server-side
in one call, but it answers with a flat set — and a flat set cannot say *why*.
arcet walks membership level by level to keep the path, then cross-checks the
walk against the transitive set. Anything Graph can reach that the walk did not
becomes a warning, not quietly fewer permissions.

**PIM eligible and active never blur.** They come from different APIs, take
different paths through the resolver, and land in different sections. An
activated PIM assignment is *active*, and its chain says so. The model refuses
to mark something eligible without a step justifying it.

**Wildcard expansion with `NotActions`.** `Microsoft.KeyVault/*/read` becomes
the concrete actions it grants, minus what the role excludes. A control-plane
wildcard never pulls in a data action.

**Control plane vs data plane.** Reading a secret's properties and reading its
value are different grants. They are never collapsed into one line.

**Warnings that mean something.** A tenant without Entra ID P2 answers the PIM
APIs with a licence error — arcet treats that as *"no PIM here"*, not as a gap,
because without the licence no eligibility can exist. False warnings are how a
tool teaches people to skip the true ones.

**Deterministic output.** Canonical ordering is applied when the result is
constructed, not left to each renderer. Two runs over the same data render
identically, byte for byte.

**Table and JSON.** The table stops at 50 per section and states the count it
left out. JSON is never truncated, carries a schema version, and tells a
consumer in one field whether anything went uninterpreted.

**Fast where it counts.** `--help` and `--version` do not import the Azure SDK,
so they return instantly.

---

## Reading the output

### Three views, three questions

`--format table` is the default and answers **why**: one permission at a time,
with its chain, nothing abbreviated. It costs four or five lines each, which is
the right trade when you have narrowed with `--action` and the wrong one when
you have not.

`--format list` answers **what**: one line per action, grouped, with a count of
how many distinct chains lead to it.

```console
$ arcet whocan alice@example.com -s <sub> --format list

ACTIVE   Microsoft.Authorization/roleAssignments/write       2 paths
ELIGIBLE Microsoft.Authorization/roleAssignments/write       1 path
ACTIVE   Microsoft.KeyVault/vaults/secrets/getSecret/action  data plane  1 path
ACTIVE   Microsoft.Storage/storageAccounts/delete            1 path
```

Scan with `list`, then `--action` the one that surprised you and read the chain.

`--format grid` answers **which**: a column per field, in the shape
`az ... -o table` produces, for comparing rows against each other.

```console
$ arcet whocan alice@example.com -s <sub> --format grid \
        --action 'Microsoft.Storage/storageAccounts/delete'

Principal:    alice@example.com
Subscription: 00000000-1111-2222-3333-444444444444
Permissions:  3

+--------+------------------------------------------+--------+-------------+---------------------+
|STATUS  | PERMISSION                               | VIA    | ROLE        | SCOPE               |
|--------+------------------------------------------+--------+-------------+---------------------|
|ACTIVE  | Microsoft.Storage/storageAccounts/delete | Direct | Contributor | /subscriptions/0000 |
|        |                                          |        |             | 0000-1111-2222-3333 |
|        |                                          |        |             | -444444444444       |
|--------+------------------------------------------+--------+-------------+---------------------|
|ACTIVE  | Microsoft.Storage/storageAccounts/delete | Ops    | Owner       | /subscriptions/…/re |
|        |                                          |        |             | sourceGroups/demo/… |
+--------+------------------------------------------+--------+-------------+---------------------+
```

Cells **wrap, they do not truncate**. An Azure scope runs to about 120
characters and no terminal holds one beside an action name and a nested group
path, so something has to give: either the row gets tall, or the scope stops
being something you can paste. It gets tall. That makes `grid` the least
compact of the three, which is worth knowing before choosing it — `list` is the
dense one.

### Warnings

Warnings print **before everything else**, so piping through `head` still shows
them. A result carrying warnings is never presented as complete.

| Warning | Meaning |
|---|---|
| `deny_assignment` | Deny assignments exist here and were not evaluated |
| `abac_condition` | An assignment has a condition; the grant may be narrower |
| `management_group_inheritance` | A grant comes from a management group, not walked |
| `insufficient_read_access` | **Something could not be read — the list is short** |
| `unrecognised` | Anything else detected and not interpreted |

`insufficient_read_access` is the one to care about. Azure answers an
unauthorised list with *fewer rows* rather than an error, so wherever arcet can
tell it was blocked, it says so instead of reporting a smaller answer as if it
were the whole one.

The table cuts each section at 50 entries and names the count it left out along
with both ways to see more. Nothing is truncated quietly.

---

## Permissions needed to run it

Read-only throughout. The built-in **Reader** role plus two Graph permissions
is enough.

| Permission | Why | If missing |
|---|---|---|
| `Microsoft.Authorization/roleAssignments/read` | The assignments themselves | Warning, empty result |
| `Microsoft.Authorization/roleDefinitions/read` | What each role grants | Warning per role |
| `Microsoft.Authorization/denyAssignments/read` | To report that they exist | Warning instead of silence |
| Graph `User.Read.All` | Resolve the identity | Cannot start |
| Graph `GroupMember.Read.All` | Walk group membership | Warning, group grants missing |
| PIM eligibility read | Eligible roles | Warning — unless the tenant has no Entra ID P2, which is not a gap |

---

## JSON output

`--format json` is the contract for anything downstream. Never truncated,
versioned, and stable.

```console
arcet whocan alice@example.com -s <sub> --format json | jq '.permissions[0]'
```

```json
{
  "action": "Microsoft.KeyVault/vaults/secrets/read",
  "action_kind": "control_plane",
  "state": "active",
  "scope": "/subscriptions/…/resourceGroups/rg-prod",
  "derivation": [
    { "kind": "group_membership", "label": "group \"Platform\" → group \"SRE\" (nested)", "ref": "…" },
    { "kind": "role_assignment",  "label": "role \"Key Vault Secrets User\"",            "ref": "…" }
  ]
}
```

| Field | Values |
|---|---|
| `schema` | Integer, bumped only on a breaking shape change |
| `complete` | `false` when anything went uninterpreted |
| `state` | `active`, `pim_eligible` |
| `action_kind` | `control_plane`, `data_plane` |
| `derivation[].kind` | `group_membership`, `role_assignment`, `direct_assignment`, `pim_eligible` |

`scope_inheritance` exists in the schema but is not emitted in v0.1 — it is
reserved for management group inheritance, which is currently reported as a
warning rather than walked.

> **Size.** JSON is never truncated, which for a privileged identity means it
> is large — an `Owner` on a busy subscription produced roughly **39 MB** in
> testing. Redirect it to a file rather than through a pager, or narrow it with
> `--action` first.

Useful one-liners:

```console
# Everything reachable only through groups
… --format json | jq '[.permissions[] | select(any(.derivation[]; .kind=="group_membership"))]'

# Just the data-plane grants
… --format json | jq '[.permissions[] | select(.action_kind=="data_plane").action] | unique'

# Fail a pipeline if the answer was partial
… --format json | jq -e '.complete' > /dev/null
```

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Resolved. Warnings, if any, are printed but do not change this |
| `2` | arcet could not do its job — authentication failed, Azure unreachable |
| `3` | Identity not found, or bad arguments |

Warnings deliberately do **not** fail the run. Deny assignments exist in most
real subscriptions, so exiting non-zero whenever a result is partial would fire
on nearly every invocation and teach people to append `|| true` — which would
silence the warnings that matter. Use `jq -e '.complete'` when you want that
signal.

---

## Configuration

arcet has no config file and no environment variables of its own. It reads
these, which belong to the libraries underneath:

| Variable | Read by | Purpose |
|---|---|---|
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` | `azure-identity` | Service principal authentication |
| `AZURE_CLIENT_CERTIFICATE_PATH` | `azure-identity` | Certificate authentication |
| `NO_COLOR` | `rich` | Plain output |
| `COLUMNS` | `rich` | Force a width when not a terminal |

Redirected output is plain and stable by default — colour is only emitted to a
terminal.

---

## How it works

```
identity (UPN or object id)
   │
   ├─ Graph ──▶ resolve to an object id and kind
   ├─ Graph ──▶ walk memberOf level by level, keeping the path
   │            └─ cross-check against transitiveMemberOf ──▶ warn on any gap
   │
   ├─ ARM ────▶ role assignments via assignedTo(), which includes group-derived
   ├─ ARM ────▶ role definitions, built-in and custom
   ├─ ARM ────▶ PIM eligibilities and activations
   ├─ ARM ────▶ deny assignments (existence only)
   └─ ARM ────▶ provider operations catalogue, for wildcard expansion
                     │
                     ▼
        expand wildcards, subtract NotActions
                     │
                     ▼
        EffectivePermission × derivation chain
                     │
                     ▼
             table  or  JSON
```

The split that matters is **pure logic versus network**. Parsing, expansion,
`NotActions` subtraction, the group walk and chain construction are pure
functions driven by recorded fixtures. The layer that talks to Azure is thin
and dumb on purpose. That is why 317 tests can cover the judgement without a
single one touching the network — and why the bugs that did survive were all
found by running it against a real tenant, which is the honest limit of the
approach.

---

## Development

```console
uv sync --all-groups
uv run pytest          # 317 tests, none touch the network
uv run ruff check .
uv run ruff format .
```

| Module | Responsibility |
|---|---|
| `model.py` | Frozen types that validate on construction |
| `groups.py` | Membership walk, paths, cycle detection |
| `arm.py` | ARM payload parsers — pure |
| `actions.py` | Wildcard expansion and `NotActions` — pure |
| `resolve.py` | The resolver, behind a `PermissionSource` protocol |
| `reader.py` | The only module that touches the network |
| `render.py` | Table and JSON |

Tests never call Azure. `tests/fixtures/` holds recorded payloads in the wire
shape — which is exactly what the SDK's `serialize(keep_readonly=True)`
returns, so the parsers under test are the parsers that run in production.

`tests/test_readonly.py` is the guard on the read-only promise. Try flipping a
`GET` to a `DELETE` and watch two independent tests fail.

---

## Contributing

Bug reports and pull requests are welcome — [CONTRIBUTING.md](CONTRIBUTING.md)
covers the setup, the invariants a change cannot violate, and the shape of a
change that adds support for a new Azure construction.

Found a permission arcet failed to report, or a missing warning? That is a
security issue in a tool like this one. Please read
[SECURITY.md](SECURITY.md) and report it privately rather than in an issue.

- [Changelog](CHANGELOG.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

## Identity

<img src="assets/brand/arcet-mark.svg" alt="" width="112" align="right">

The name is from Latin *arcēre* — to keep out, to contain. Same root as *arx*,
citadel, and *arcanum*.

The mark says the same thing the tool does. A continuous route enters from
outside, passes between two boundaries, and ends at a single copper terminal.
A permission is not a fact standing on its own; it is the end of a path, and
showing the path is the whole job.

Copper appears once, on the terminal, and is never used for anything else.

Assets, palette, clear space and usage: [`assets/brand/`](assets/brand/).

## Licence

Apache-2.0. See [LICENSE](LICENSE).
