# arcet

Effective Azure permissions, with the derivation chain that explains them.

The Azure portal will tell you that someone has a role. It will not tell you
that they can write role assignments on a storage account because they are in
a group that is in another group that holds Owner there. arcet answers the
second question, and shows its working.

```console
$ arcet whocan user@example.com --subscription 00000000-1111-2222-3333-444444444444 \
      --action 'Microsoft.Authorization/roleAssignments/write'

Microsoft.Authorization/roleAssignments/write
  └─ role "Owner"
     @ /subscriptions/00000000-1111-2222-3333-444444444444

Microsoft.Authorization/roleAssignments/write
  └─ group "Platform" → group "Ops" (nested)
     └─ role "Owner"
        @ /subscriptions/00000000-.../resourceGroups/demo/providers/Microsoft.Storage/storageAccounts/data

ELIGIBLE VIA PIM — 1 permission
not held now; can be activated

Microsoft.Authorization/roleAssignments/write
  └─ role "User Access Administrator" (eligible, not active)
     @ /subscriptions/00000000-1111-2222-3333-444444444444
```

The chain is the point. A list of permissions without one is a list you cannot
check, argue with, or act on.

## What this does not do

Read this before trusting the output.

**Not in v0.1.** These are detected and reported as warnings, never silently
ignored, but they are not interpreted:

- **Deny assignments.** Their existence is reported. Their effect is not
  computed, so a permission listed here may in fact be denied.
- **ABAC conditions.** An assignment carrying a condition is reported. arcet
  does not evaluate the condition, so the grant may be narrower than shown.
- **Management group inheritance.** A grant arriving from a management group
  is reported, but that hierarchy is not walked.

**Out of scope entirely, for now:**

- **Groups as the subject.** You ask about a user or a service principal, not
  about a group.
- **A whole tenant.** One subscription per run.

**By design, and not negotiable:**

- **It never writes to Azure.** Read-only credentials are enough, and Owner is
  never needed. A build-time check fails the test suite if a mutating SDK call
  or a non-GET request appears anywhere in the package.
- **It keeps no state.** One identity, one run, nothing cached between them.
- **It does not use an LLM at runtime.** The resolution is deterministic: the
  same input gives the same output.
- **Azure only.** There is no AWS or GCP roadmap.

## Install

```console
uvx arcet --help          # run without installing
pipx install arcet        # or install it
```

Python 3.11 or newer.

## Use

Sign in first — arcet uses whatever `DefaultAzureCredential` finds, so
`az login` or the usual `AZURE_*` environment variables both work. Interactive
browser login is deliberately excluded, so a missing credential fails loudly
instead of opening a browser inside a pipeline.

```console
arcet whocan <upn-or-object-id> --subscription <subscription-id>
```

### Asking a narrow question

This is the main way to use it. An identity holding Owner resolves to tens of
thousands of actions, and the useful question is almost never "list them":

```console
arcet whocan alice@example.com -s <sub> --action 'Microsoft.Storage/*/delete'
arcet whocan alice@example.com -s <sub> --action 'Microsoft.KeyVault/vaults/secrets/getSecret/action'
```

Wildcards work the way Azure's do: `*` spans everything, matching is
case-insensitive. Nothing matching is a real answer — it means no, and the
warnings still tell you how much of the picture was understood.

### Options

| Flag | Meaning |
|---|---|
| `--subscription`, `-s` | Subscription to resolve within. Required. |
| `--action`, `-a` | Only show permissions matching this pattern. |
| `--format`, `-f` | `table` (default) or `json`. |
| `--expand` / `--no-expand` | Expand wildcard actions into concrete ones. On by default. |
| `--version`, `--help` | |

### `--expand`, and why it is the default

Azure roles are written with wildcards. Expanding them against the provider
operations catalogue is what makes `--action` exact, and it is also the only
mode that subtracts a role's `NotActions` correctly.

That matters more than it sounds. `Contributor` is `*` minus
`Microsoft.Authorization/*/Write`, `elevateAccess` and a dozen others. Without
expansion there is nothing concrete to subtract from, so the unexpanded view
shows `*` — more access than the identity actually has. `--no-expand` says so
in a warning when it happens, and it is useful for seeing the shape of the
grants, but the default errs towards being right.

### JSON

`--format json` is the contract for anything downstream. It is never
truncated, it carries a `schema` version, and `complete` tells a consumer in
one field whether anything went uninterpreted.

```console
arcet whocan alice@example.com -s <sub> --format json | jq '.permissions[0]'
```

```json
{
  "action": "Microsoft.KeyVault/vaults/secrets/read",
  "action_kind": "control_plane",
  "state": "active",
  "scope": "/subscriptions/.../resourceGroups/rg-prod",
  "derivation": [
    { "kind": "group_membership", "label": "group \"Platform\" → group \"SRE\" (nested)", "ref": "..." },
    { "kind": "role_assignment", "label": "role \"Key Vault Secrets User\"", "ref": "..." }
  ]
}
```

`action_kind` separates control plane from data plane, because reading a
secret's properties and reading its value are different grants.

`state` is `active` or `pim_eligible`, and they never blur: "has access" and
"can have access in five minutes" are different facts, and the table puts them
in different sections for the same reason.

## Reading the output

The table cuts each section at 50 entries and tells you the count it left out.
Nothing is ever truncated quietly, and JSON is never truncated at all.

Warnings appear first, before anything else, so that piping through `head`
still shows them. A result carrying warnings is never presented as complete.

| Warning | What it means |
|---|---|
| `deny_assignment` | Deny assignments exist here and were not evaluated. |
| `abac_condition` | An assignment has a condition; the grant may be narrower. |
| `management_group_inheritance` | A grant comes from a management group, not walked. |
| `insufficient_read_access` | Something could not be read. **The list is short of something.** |
| `unrecognised` | Anything else detected and not interpreted. |

`insufficient_read_access` is the one to care about. Azure answers an
unauthorised list with fewer rows rather than an error, so wherever arcet can
tell that it was blocked, it says so instead of reporting a smaller answer.

## Permissions needed to run it

Read-only throughout:

- `Microsoft.Authorization/roleAssignments/read`
- `Microsoft.Authorization/roleDefinitions/read`
- `Microsoft.Authorization/denyAssignments/read` — without it you get a warning
  rather than silence
- Microsoft Graph `User.Read.All` and `GroupMember.Read.All`, to resolve the
  identity and walk group membership
- PIM eligibility reads, if the tenant has Entra ID P2. Tenants without it
  answer with a licence error, which arcet treats as "no PIM here" rather than
  as a gap, because without the licence no eligibility can exist.

The built-in `Reader` role plus the two Graph permissions is enough.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Resolved. Warnings, if any, are printed but do not change this. |
| `2` | arcet could not do its job: authentication failed, Azure unreachable. |
| `3` | The identity was not found, or the arguments were wrong. |

Warnings deliberately do not fail the run. Deny assignments exist in most real
subscriptions, so exiting non-zero whenever a result is partial would fire on
nearly every invocation and teach people to append `|| true`, which would
silence the warnings that matter.

## Development

```console
uv sync --all-groups
uv run pytest
uv run ruff check .
```

The tests never call Azure. Everything with judgement in it — parsing, wildcard
expansion, `NotActions` subtraction, group walking, chain building — is pure
and driven by recorded fixtures; the layer that talks to the network is thin
and dumb on purpose.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
