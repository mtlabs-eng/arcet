## What and why

<!-- The diff says what changed. Say why it needed to. -->

## How it was verified

<!--
Beyond CI. If you ran it against a real tenant, say what shape that tenant
had — several real bugs in this project survived a fully green suite, and that
context is worth more than it looks.
-->

## Invariants

<!-- See CONTRIBUTING.md. Tick, or explain in "What and why" why one does not apply. -->

- [ ] No write to Azure — no non-`GET` request, no mutating SDK method
- [ ] Nothing new is ignored silently; anything uninterpreted produces a warning that reaches the output
- [ ] No test calls Azure; new cases are driven by fixtures
- [ ] No scoring, ranking or remediation advice
- [ ] Output stays deterministic — same input, same order
- [ ] Nothing is cached or written between runs

## Tests

- [ ] New behaviour has tests, positive and negative
- [ ] Behaviour that changed has its old assertions updated rather than deleted
- [ ] `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` pass locally

## Anything else

<!-- Follow-ups, things deliberately left out, decisions you would like a second opinion on. -->
