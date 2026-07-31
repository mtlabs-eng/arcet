# Rule pages

One page per rule, at `docs/rules/<category>/<name>.md`. These are what the
`helpUri` of each finding points to, in every output format.

A rule is not done until its page exists. Someone reading a SARIF alert in the
GitHub Security tab has the rule ID and nothing else; the page is the rest of
the explanation.

Each page covers:

- what the rule detects, and the threat model behind it
- a workflow that triggers it
- a workflow that does not, and why
- how to fix it
- when suppressing it is legitimate — with the reason that belongs after the
  `--` in the suppression comment

Pages arrive with their rules, from milestone 3 onwards.
