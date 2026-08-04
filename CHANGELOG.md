# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning

arcet is pre-1.0, so the minor number carries breaking changes. There are two
contracts, and they move independently:

- **The command line.** Flags, arguments and exit codes. A removed or
  redefined flag is breaking.
- **The JSON output.** It carries its own `schema` integer, bumped only when
  the shape changes in a way that breaks a consumer. A new optional field does
  not bump it; a renamed or removed one does. Anything that changes it is
  called out here.

The table output is *not* a contract. It is for reading, and it will change.
Parse the JSON.

`a` suffixes mean alpha: released, but with parts that have not been proven
against a real tenant. `pip` and `uv` will not install an alpha unless asked,
which is the intended friction. See
[How much of this has been proven](README.md#how-much-of-this-has-been-proven).

## [Unreleased]

### Added

- **`--format list`** — one line per action, grouped, with a count of the
  chains that lead to it. The chain view spends four or five lines per
  permission, which is unreadable at fifty of them; this answers *what* so the
  default can go on answering *why*.

  A column-per-field grid was prototyped first and rejected on evidence: an
  action name, an Azure scope and a nested group path come to roughly 230
  characters, so every column is elided even at 200 columns wide. A truncated
  scope cannot be pasted or acted on, and nothing here is allowed to be cut
  silently. The list view drops the chain instead of shrinking it.

- **`--format grid`** — a column per field, in the shape `az ... -o table`
  produces, for comparing rows against each other. Cells wrap rather than
  truncate, so a row with a long scope becomes four lines tall and nothing is
  lost. It is the least compact of the three views; `list` is the dense one.

### Fixed

- The header line no longer folds mid-phrase on a narrow terminal.

## [0.1.0a1] — 2026-08-04

First release. `arcet whocan` resolves effective Azure permissions for one
identity in one subscription, and shows the derivation chain behind each one.

### Added

- `arcet whocan <identity> --subscription <id>` — the only command.
- **Derivation chains.** Every permission carries an ordered chain from the
  subject to the grant. The data model refuses to construct a permission
  without one.
- **Nested group resolution with paths.** Membership is walked level by level
  rather than fetched flat, so the chain can say *why* an identity is in a
  group. The walk is cross-checked against Graph's transitive set, and any gap
  becomes a warning.
- **PIM eligibility**, kept strictly separate from active permissions and
  rendered in its own section. Activated PIM assignments are labelled in the
  chain but counted once.
- **Wildcard expansion** against the provider operations catalogue, with
  `NotActions` and `NotDataActions` subtracted. `--no-expand` keeps the literal
  patterns and warns that exclusions could not be applied.
- **Control plane and data plane** distinguished per action.
- **Warnings** for deny assignments, ABAC conditions, management group
  inheritance, unreadable scopes and anything else detected but not
  interpreted. A result carrying warnings is never presented as complete.
- **`--action <pattern>`** to answer a narrow question against an identity that
  holds a lot. Wildcards match the way Azure's do.
- **Table and JSON output.** The table stops at 50 per section and states what
  it left out; JSON is never truncated and carries `schema` and `complete`.
- **Read-only enforced by the build.** A test walks the package's syntax tree
  and fails if a mutating SDK call, a non-`GET` request, or a new
  `azure-mgmt-*` import appears.

### Known limitations

Documented in [the README](README.md#what-this-does-not-do) and warned about at
runtime:

- Deny assignments and ABAC conditions are reported but not evaluated.
- Management group inheritance is reported but not walked.
- Groups cannot be the subject; one subscription per run.
- The PIM and `insufficient_read_access` code paths have not yet been exercised
  against a real tenant — see the README.

### Project history

`arcet` previously named a Go static linter for GitHub Actions workflows. That
project was abandoned on 2026-08-03 and the repository reused; only
`scripts/pin.sh`, the licence and the git history carried over. The linter is
still reachable in the history at `482723d`.

[Unreleased]: https://github.com/mtlabs-eng/arcet/compare/v0.1.0a1...HEAD
[0.1.0a1]: https://github.com/mtlabs-eng/arcet/releases/tag/v0.1.0a1
