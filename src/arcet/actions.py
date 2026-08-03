"""Turning a role definition into the concrete actions it grants.

Azure roles are written with wildcards: `*`, `Microsoft.KeyVault/*/read`. The
question arcet answers is what an identity can do in practice, so by default
those are expanded against the provider operations catalogue and the role's
NotActions are subtracted from the result.

The subtraction is the part worth being careful about. Getting it wrong in the
permissive direction reports access that does not exist; getting it wrong in
the restrictive direction hides access that does. Where it cannot be done
exactly, this module says so instead of guessing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from arcet.model import ActionKind, UnsupportedConstructKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from arcet.arm import ProviderOperation, RoleDefinition
    from arcet.diagnostics import Diagnostics

__all__ = ["ResolvedAction", "matches", "resolve_actions"]

#: One concrete action and the plane it belongs to.
ResolvedAction = tuple[str, ActionKind]


def _to_regex(pattern: str) -> re.Pattern[str]:
    """Compile an Azure action pattern.

    `*` spans everything, separators included: `Microsoft.KeyVault/*/read`
    matches `Microsoft.KeyVault/vaults/secrets/read`. Matching is
    case-insensitive, as ARM treats these.
    """
    escaped = "".join(".*" if char == "*" else re.escape(char) for char in pattern)
    return re.compile(f"^{escaped}$", re.IGNORECASE)


def matches(pattern: str, action: str) -> bool:
    """Whether an action pattern covers a concrete action."""
    return bool(_to_regex(pattern).match(action))


def _has_wildcard(pattern: str) -> bool:
    return "*" in pattern


def _expand_patterns(
    patterns: Iterable[str],
    catalogue: Sequence[ProviderOperation],
    *,
    data_plane: bool,
) -> tuple[set[str], list[str]]:
    """Expand patterns against the catalogue.

    Returns the concrete actions matched, and the wildcard patterns that
    matched nothing at all — those are reported, since a pattern matching
    nothing usually means the catalogue is older than the role.
    """
    names = [op.name for op in catalogue if op.is_data_action is data_plane]
    resolved: set[str] = set()
    barren: list[str] = []

    for pattern in patterns:
        if not _has_wildcard(pattern):
            # A literal action is taken at face value even when the catalogue
            # does not list it. The catalogue lags new providers, and dropping
            # a named action because a lookup table has not caught up would be
            # exactly the silent loss this tool exists to avoid.
            resolved.add(pattern)
            continue

        regex = _to_regex(pattern)
        matched = {name for name in names if regex.match(name)}
        if matched:
            resolved |= matched
        else:
            barren.append(pattern)

    return resolved, barren


def _subtract(granted: set[str], exclusions: Iterable[str]) -> set[str]:
    """Remove everything the NotActions cover.

    Exclusion patterns are matched against what was granted, so a wildcard
    NotAction removes every expanded action it covers rather than only an
    identical string.
    """
    remaining = set(granted)
    for pattern in exclusions:
        regex = _to_regex(pattern)
        remaining = {action for action in remaining if not regex.match(action)}
    return remaining


def resolve_actions(
    role: RoleDefinition,
    catalogue: Sequence[ProviderOperation] | None,
    *,
    expand: bool,
    diagnostics: Diagnostics,
    ref: str | None = None,
) -> tuple[ResolvedAction, ...]:
    """Resolve a role into the actions it grants, in canonical order.

    With `expand` false, or with no catalogue available, the role's patterns
    come back literally. That is a weaker answer, and where NotActions exist it
    is also an incomplete one, so it is reported rather than presented as
    equivalent.
    """
    if expand and catalogue is None:
        diagnostics.add(
            UnsupportedConstructKind.UNRECOGNISED,
            (
                f'wildcards in role "{role.name}" were left unexpanded because '
                f"the provider operations catalogue could not be read"
            ),
            ref or role.id,
        )

    if not expand or catalogue is None:
        return _literal(role, diagnostics, ref)

    control, barren_control = _expand_patterns(
        role.actions, catalogue, data_plane=False
    )
    data, barren_data = _expand_patterns(role.data_actions, catalogue, data_plane=True)

    control = _subtract(control, role.not_actions)
    data = _subtract(data, role.not_data_actions)

    for pattern in barren_control + barren_data:
        diagnostics.add(
            UnsupportedConstructKind.UNRECOGNISED,
            (
                f'pattern "{pattern}" in role "{role.name}" matched no known '
                f"operation; the catalogue may be older than the role"
            ),
            ref or role.id,
        )

    return _ordered(control, data)


def _literal(
    role: RoleDefinition, diagnostics: Diagnostics, ref: str | None
) -> tuple[ResolvedAction, ...]:
    """Return the role's patterns as written.

    NotActions cannot be applied to unexpanded wildcards without expanding
    them, so where they exist the reader is told that what is shown is broader
    than what is granted. Quietly printing the Actions alone would overstate
    the access.
    """
    if role.not_actions or role.not_data_actions:
        excluded = ", ".join((*role.not_actions, *role.not_data_actions))
        diagnostics.add(
            UnsupportedConstructKind.UNRECOGNISED,
            (
                f'role "{role.name}" excludes {excluded}, which was not '
                f"subtracted because wildcards were not expanded; the actions "
                f"shown are broader than what is granted"
            ),
            ref or role.id,
        )
    return _ordered(set(role.actions), set(role.data_actions))


def _ordered(control: set[str], data: set[str]) -> tuple[ResolvedAction, ...]:
    """Canonical order: control plane first, then data plane, each sorted."""
    return (
        *((action, ActionKind.CONTROL_PLANE) for action in sorted(control)),
        *((action, ActionKind.DATA_PLANE) for action in sorted(data)),
    )
