"""The data model for a resolution result.

Everything here is frozen and validates itself on construction. That is
deliberate: the states this tool must never reach — a permission with no chain
explaining it, a PIM-eligible permission with nothing marking it as eligible,
two runs over the same data producing different orderings — are made
unrepresentable rather than merely discouraged.

Nothing in this module talks to Azure, and nothing in it renders output.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "ActionKind",
    "DerivationKind",
    "DerivationStep",
    "EffectivePermission",
    "IdentityKind",
    "IdentityRef",
    "PermissionState",
    "ResolutionResult",
    "UnsupportedConstruct",
    "UnsupportedConstructKind",
    "canonical_permissions",
]


class IdentityKind(StrEnum):
    """What kind of principal the subject is. v0.1 resolves these two only."""

    USER = "user"
    SERVICE_PRINCIPAL = "service_principal"


class PermissionState(StrEnum):
    """Whether the identity holds the permission now, or could activate it.

    The difference between these two is the difference between "has access"
    and "can have access in five minutes", and every renderer must show it.
    """

    ACTIVE = "active"
    PIM_ELIGIBLE = "pim_eligible"


class ActionKind(StrEnum):
    """Which Azure plane an action belongs to.

    Reading a secret's properties is a control plane action; reading its value
    is a data plane one. They come from different role definitions and grant
    genuinely different power, so they never collapse into one line.
    """

    CONTROL_PLANE = "control_plane"
    DATA_PLANE = "data_plane"


class DerivationKind(StrEnum):
    """One link in the chain that explains why a permission is held."""

    GROUP_MEMBERSHIP = "group_membership"
    ROLE_ASSIGNMENT = "role_assignment"
    PIM_ELIGIBLE = "pim_eligible"
    SCOPE_INHERITANCE = "scope_inheritance"
    DIRECT_ASSIGNMENT = "direct_assignment"


class UnsupportedConstructKind(StrEnum):
    """Something detected but not interpreted, which may make the result wrong.

    UNRECOGNISED is the catch-all, and it exists so that meeting something new
    is reported rather than dropped for want of an enum member.
    """

    DENY_ASSIGNMENT = "deny_assignment"
    ABAC_CONDITION = "abac_condition"
    MANAGEMENT_GROUP_INHERITANCE = "management_group_inheritance"
    INSUFFICIENT_READ_ACCESS = "insufficient_read_access"
    UNRECOGNISED = "unrecognised"


def _require_text(value: str, owner: str, field_name: str) -> None:
    """Reject blank text.

    Every string in this model ends up either in the output or in a lookup. A
    blank one is a bug upstream, and it should surface where it was created
    rather than as an empty cell in someone's table.
    """
    if not value.strip():
        raise ValueError(f"{owner}.{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class DerivationStep:
    """One step of the explanation, from the subject towards the origin."""

    kind: DerivationKind
    #: Human-readable, e.g. 'group "Platform" -> group "SRE" (nested)'.
    label: str
    #: Canonical Azure id or path for the object this step went through.
    ref: str

    def __post_init__(self) -> None:
        _require_text(self.label, "DerivationStep", "label")
        _require_text(self.ref, "DerivationStep", "ref")


@dataclass(frozen=True, slots=True)
class IdentityRef:
    """The subject a resolution was run for."""

    object_id: str
    display_name: str
    kind: IdentityKind

    def __post_init__(self) -> None:
        _require_text(self.object_id, "IdentityRef", "object_id")
        _require_text(self.display_name, "IdentityRef", "display_name")


@dataclass(frozen=True, slots=True)
class EffectivePermission:
    """One thing an identity can do, and the chain that says why."""

    action: str
    action_kind: ActionKind
    state: PermissionState
    scope: str
    #: Ordered from the subject to the origin of the grant. Never empty.
    derivation: tuple[DerivationStep, ...]

    def __post_init__(self) -> None:
        _require_text(self.action, "EffectivePermission", "action")
        _require_text(self.scope, "EffectivePermission", "scope")

        # Accept any sequence and store a tuple, so callers cannot hand in a
        # list and keep mutating it after the fact.
        object.__setattr__(self, "derivation", tuple(self.derivation))

        if not self.derivation:
            raise ValueError(
                f"EffectivePermission.derivation must not be empty "
                f"({self.action} @ {self.scope}): a permission without a chain "
                f"is a claim without evidence"
            )

        # A permission may be active *because* a PIM assignment was activated,
        # so an active permission is allowed to carry a PIM step. The reverse
        # is not: calling something eligible with nothing in the chain marking
        # it eligible is the mislabelling that costs the reader most.
        if self.state is PermissionState.PIM_ELIGIBLE and not any(
            step.kind is DerivationKind.PIM_ELIGIBLE for step in self.derivation
        ):
            raise ValueError(
                f"EffectivePermission is PIM_ELIGIBLE but no step in its "
                f"derivation says so ({self.action} @ {self.scope})"
            )


@dataclass(frozen=True, slots=True)
class UnsupportedConstruct:
    """Something detected and not interpreted.

    Named for what it is rather than `Warning`, which is a builtin: inheriting
    that name causes real collisions in `except` clauses.
    """

    kind: UnsupportedConstructKind
    #: What was found and what it means for the result, in plain language.
    message: str
    #: Canonical Azure id of the object involved, when there is one.
    ref: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.message, "UnsupportedConstruct", "message")
        if self.ref is not None:
            _require_text(self.ref, "UnsupportedConstruct", "ref")


# Explicit orderings rather than relying on the enum values sorting the way we
# happen to want. Renaming a member should not silently reorder the output.
_ACTION_KIND_ORDER = {ActionKind.CONTROL_PLANE: 0, ActionKind.DATA_PLANE: 1}
_STATE_ORDER = {PermissionState.ACTIVE: 0, PermissionState.PIM_ELIGIBLE: 1}


def _permission_sort_key(permission: EffectivePermission) -> tuple[str, int, int, str]:
    return (
        permission.action,
        _ACTION_KIND_ORDER[permission.action_kind],
        _STATE_ORDER[permission.state],
        permission.scope,
    )


def canonical_permissions(
    permissions: Iterable[EffectivePermission],
) -> tuple[EffectivePermission, ...]:
    """Put permissions into the one order this tool ever emits.

    Grouped by action, control plane before data plane, active before eligible,
    then by scope. Exact duplicates collapse; two entries for the same action
    reached by different chains do not, because those are two separate facts
    and choosing between them would be a judgement we do not make.
    """
    unique = dict.fromkeys(permissions)
    return tuple(sorted(unique, key=_permission_sort_key))


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Everything one run of `whocan` found, and everything it could not."""

    identity: IdentityRef
    subscription: str
    permissions: tuple[EffectivePermission, ...] = ()
    warnings: tuple[UnsupportedConstruct, ...] = field(default=())

    def __post_init__(self) -> None:
        _require_text(self.subscription, "ResolutionResult", "subscription")
        # Canonical order is applied here rather than left to the renderers.
        # Determinism is a product invariant, so it should not depend on each
        # output format remembering to sort.
        object.__setattr__(self, "permissions", canonical_permissions(self.permissions))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def is_complete(self) -> bool:
        """Whether everything encountered was understood.

        False means the permission list may be missing entries or carrying
        wrong ones. Renderers must not present an incomplete result as if it
        were complete.
        """
        return not self.warnings
