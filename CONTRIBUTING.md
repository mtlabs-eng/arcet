# Contributing

Thanks for looking. arcet is small on purpose, so the fastest way to get a
change merged is to know what it will and will not accept.

## Setup

```console
git clone https://github.com/mtlabs-eng/arcet && cd arcet
uv sync --all-groups
uv run pytest        # should be green before you change anything
```

Python 3.11 or newer. Nothing else is required — no Azure account, no
credentials, no network. If a test needs any of those, it is the wrong test.

```console
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
```

CI runs the same three on 3.11, 3.12 and 3.13, and then builds the wheel and
runs the console script out of it.

## The invariants

These are not style preferences. A pull request that violates one will be
declined regardless of how good the rest of it is. They are stated in full in
[`CLAUDE.md`](CLAUDE.md); the short version:

- **Never write to Azure.** No `POST`, `PUT`, `PATCH`, `DELETE`, no mutating
  SDK method, no `begin_*` long-running operation. `tests/test_readonly.py`
  walks the package's syntax tree and fails the build if one appears. Do not
  add an exception to it.
- **Never fail silently.** Anything arcet meets and cannot interpret must
  produce an `UnsupportedConstruct` that reaches the output. `except: pass` has
  no place in the resolution path, and neither does dropping a field you do not
  recognise.
- **Tests never call Azure.** Recorded fixtures, always.
- **No scoring, no recommendations.** arcet reports facts. It does not rank by
  risk, suggest remediations, or say what is "wrong".
- **Deterministic.** The same input gives the same output, in the same order.
  No LLM at runtime, no wall-clock, no randomness.
- **Stateless.** No cache, no database, no files written between runs.

## How the code is arranged

The split that matters is **pure logic versus network**:

| Module | What it does | Testable without Azure |
|---|---|---|
| `model.py` | Frozen types that validate on construction | Yes |
| `groups.py` | Membership walk, paths, cycles | Yes |
| `arm.py` | ARM payload parsers | Yes |
| `actions.py` | Wildcard expansion, `NotActions` | Yes |
| `resolve.py` | The resolver, behind a `PermissionSource` protocol | Yes |
| `render.py` | Table and JSON | Yes |
| `diagnostics.py` | Collects what was not interpreted | Yes |
| `reader.py` | **The only module that touches the network** | Not directly |

Put judgement in the pure modules. Keep `reader.py` dumb: fetch, hand the
payload to a parser, record a warning if the fetch failed.

## Adding support for a new construction

This is the most common kind of change, and it has a fixed shape:

1. **Parse it** in `arm.py`, from a fixture in `tests/fixtures/` written in the
   wire shape — which is what the SDK's `serialize(keep_readonly=True)`
   returns, so the parser under test is the parser that runs for real.
2. **Interpret it** in `resolve.py` or `actions.py`, as a pure function.
3. **If you cannot fully interpret it, warn.** Add the case to
   `UnsupportedConstructKind` if none fits, and be specific in the message
   about what the reader is missing.
4. **Test both directions.** A positive case, a negative case, and — where
   applicable — a test that proves the warning appears in the rendered output.

A change that makes arcet report *more* permissions needs a test showing where
they came from. A change that makes it report *fewer* needs a test showing why
the removed ones were wrong.

## Pull requests

- One concern per pull request.
- Green CI before review, not after.
- Explain **why** in the description, not what — the diff already says what.
- New behaviour comes with tests. Behaviour changes come with the tests that
  used to assert the old behaviour, updated.
- If you found the bug by running arcet against a real tenant, say so and
  describe the shape of the tenant. Several real bugs have survived a full
  green suite; that context is worth more than it looks.

Commit messages: a short imperative subject, then a body explaining the
reasoning. No trailers.

## Things that will be declined

- Multi-cloud. arcet is Azure only, and there is no roadmap otherwise.
- Risk scores, severity ratings, or remediation advice.
- Anything that writes, even behind a flag.
- Caching between runs.
- An LLM anywhere in the resolution path.
- A dependency that is not clearly worth its weight. In a tool whose argument
  is trust, every transitive package is surface. `msgraph-sdk` was rejected for
  adding 28 packages to serve two endpoints.

If you are unsure whether an idea fits, open an issue before writing the code.
It is a cheaper conversation than a declined pull request.

## Reporting security issues

Not here — see [`SECURITY.md`](SECURITY.md).
