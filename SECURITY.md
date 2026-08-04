# Security policy

## Reporting a vulnerability

**Do not open a public issue.**

Use [private vulnerability reporting](https://github.com/mtlabs-eng/arcet/security/advisories/new),
which is enabled on this repository. It creates a private thread visible only
to you and the maintainers.

If you would rather not use GitHub, say so in a public issue *without any
detail* — just "I would like to report a security issue privately" — and a
contact will be arranged.

## What counts as a vulnerability here

arcet is a tool people use to decide who has access to what. That makes some
correctness bugs security bugs, and they are the ones we care about most:

- **Under-reporting.** A permission an identity genuinely holds that arcet does
  not list. Someone may conclude an account is safe when it is not. This is the
  most serious class of bug in this project.
- **A missing warning.** A construction that arcet cannot interpret — a deny
  assignment, an ABAC condition, a failed read — that does not produce a
  warning. A silently incomplete answer presented as a complete one is the
  failure the whole design exists to prevent.
- **Over-reporting** that could plausibly lead someone to revoke access that
  was never granted.
- **Any write to Azure.** arcet is read-only by construction. A code path that
  issues a non-`GET` request or calls a mutating SDK method is a vulnerability
  even if it never fires in practice.
- **Credential or token leakage** into output, logs, or error messages.
- **Injection** into an OData filter, a Graph URL, or an ARM request through an
  identity string, subscription id, or action pattern.

## What is not a vulnerability

- **Deny assignments and ABAC conditions not being evaluated.** These are
  documented limitations, reported as warnings on every run. See
  [What this does not do](README.md#what-this-does-not-do).
- **Management group inheritance not being walked.** Same — documented and
  warned.
- **A vulnerability in a dependency.** Report it upstream. If it affects arcet
  specifically, tell us and we will pin or patch.
- **Results being incomplete when your own credentials cannot read something.**
  arcet reports that as `insufficient_read_access`. If it does *not* report it,
  that is a vulnerability — see above.

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` | Yes — current pre-release line |
| Anything earlier | No |

arcet is pre-1.0 and maintained by one person. Only the latest release gets
fixes.

## What to expect

This is a personal project, not a funded one. Honest expectations rather than a
service level agreement:

- Acknowledgement within **7 days**.
- An assessment of whether it is a real issue within **30 days**.
- Fixes for confirmed issues released as soon as they are ready, with an
  advisory published once users have had a chance to update.

Credit in the advisory and the changelog if you want it, and none if you do
not. Please give us a reasonable window before disclosing publicly.

## Running arcet safely

- arcet needs **read-only** credentials. It never needs Owner, and never needs
  write access to anything. If a set of instructions somewhere tells you
  otherwise, that is wrong.
- It makes no outbound connections other than to Azure Resource Manager and
  Microsoft Graph.
- It writes nothing to disk and keeps no state between runs.
- `--format json` output contains object ids, group names and scope paths from
  your tenant. Treat it as sensitive before pasting it into an issue.
