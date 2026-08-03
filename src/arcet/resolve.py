"""Turning what Azure says into effective permissions, with their chains.

The resolver never talks to Azure itself. It asks a `PermissionSource`, which
in production is backed by the readers and in tests by recorded fixtures. That
is what lets the part with the judgement in it be tested exhaustively without
a tenant.

Two rules shape almost every decision here:

* Nothing is dropped quietly. An assignment whose principal cannot be
  identified, a role that cannot be read, a construct that cannot be evaluated
  — each produces a warning, and where possible still produces a permission
  with an honest chain.
* Eligible never blurs into active. They come from different sources and take
  different paths through this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from arcet.actions import matches, resolve_actions
from arcet.arm import is_management_group_scope
from arcet.diagnostics import Diagnostics
from arcet.groups import Membership, unreached
from arcet.model import (
    DerivationKind,
    DerivationStep,
    EffectivePermission,
    IdentityRef,
    PermissionState,
    ResolutionResult,
    UnsupportedConstructKind,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from arcet.arm import (
        DenyAssignmentRef,
        EligibleAssignment,
        ProviderOperation,
        RoleAssignment,
        RoleDefinition,
    )

__all__ = ["IdentityNotFound", "PermissionSource", "filter_by_action", "resolve"]


def filter_by_action(result: ResolutionResult, pattern: str) -> ResolutionResult:
    """Keep only the permissions an action pattern covers.

    This is what makes the tool usable against a privileged identity: Owner
    expands to tens of thousands of actions, and the question worth asking is
    almost never "list them" but "can this person do X, and why".

    Warnings are carried over untouched. A filter narrows what is shown; it
    does not narrow what could not be understood, and a filtered answer that
    dropped the caveats would be more confident than the unfiltered one.
    """
    matcher = matches
    return ResolutionResult(
        identity=result.identity,
        subscription=result.subscription,
        permissions=tuple(
            permission
            for permission in result.permissions
            if matcher(pattern, permission.action)
        ),
        warnings=result.warnings,
    )


class IdentityNotFound(LookupError):
    """The subject could not be found in the directory."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"no user or service principal matches {identifier!r}")
        self.identifier = identifier


class PermissionSource(Protocol):
    """Everything the resolver needs to ask of Azure.

    A protocol rather than a base class so the fixture-backed implementation in
    the tests is a peer of the real one, not a subclass pretending to be it.
    """

    def find_identity(self, identifier: str) -> IdentityRef | None: ...

    def group_membership(self, object_id: str) -> Membership: ...

    def transitive_group_ids(self, object_id: str) -> frozenset[str]: ...

    def role_assignments_for(self, object_id: str) -> Sequence[RoleAssignment]: ...

    def eligible_assignments(self, object_id: str) -> Sequence[EligibleAssignment]: ...

    def activated_assignment_ids(self, object_id: str) -> frozenset[str]: ...

    def deny_assignments(self) -> Sequence[DenyAssignmentRef]: ...

    def role_definition(self, role_definition_id: str) -> RoleDefinition | None: ...

    def provider_operations(self) -> Sequence[ProviderOperation] | None: ...


def resolve(
    identifier: str,
    subscription_id: str,
    source: PermissionSource,
    *,
    expand: bool = True,
    diagnostics: Diagnostics | None = None,
) -> ResolutionResult:
    """Resolve one identity in one subscription.

    The caller may pass the same Diagnostics the source writes to. It should:
    a read that failed inside the source is exactly the kind of thing the
    result has to carry, and a second collector would strand those warnings
    where nobody sees them.
    """
    diagnostics = diagnostics if diagnostics is not None else Diagnostics()

    identity = source.find_identity(identifier)
    if identity is None:
        raise IdentityNotFound(identifier)

    membership = _membership(identity, source, diagnostics)
    catalogue = source.provider_operations() if expand else None
    roles = _RoleCache(source, diagnostics)

    permissions: list[EffectivePermission] = []
    permissions.extend(
        _from_assignments(
            source.role_assignments_for(identity.object_id),
            identity,
            membership,
            roles,
            catalogue,
            diagnostics,
            expand=expand,
            activated=source.activated_assignment_ids(identity.object_id),
        )
    )
    permissions.extend(
        _from_eligibilities(
            source.eligible_assignments(identity.object_id),
            identity,
            membership,
            roles,
            catalogue,
            diagnostics,
            expand=expand,
        )
    )

    _report_deny_assignments(source.deny_assignments(), diagnostics)

    return ResolutionResult(
        identity=identity,
        subscription=subscription_id,
        permissions=tuple(permissions),
        warnings=diagnostics.snapshot(),
    )


def _membership(
    identity: IdentityRef, source: PermissionSource, diagnostics: Diagnostics
) -> Membership:
    """Walk the groups, then check the walk against what Graph can reach."""
    membership = source.group_membership(identity.object_id)
    for note in membership.notes:
        diagnostics.add(UnsupportedConstructKind.UNRECOGNISED, note, identity.object_id)

    missing = unreached(membership, source.transitive_group_ids(identity.object_id))
    if missing:
        # Graph reaching a group the walk did not means a branch was not read.
        # Reporting fewer permissions without saying so is the failure this
        # whole cross-check exists to prevent.
        count = len(missing)
        noun = "group" if count == 1 else "groups"
        diagnostics.add(
            UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
            (
                f"{count} {noun} reachable through nesting could not be walked, "
                f"so permissions granted through {'it' if count == 1 else 'them'} "
                f"are missing"
            ),
            identity.object_id,
        )
    return membership


class _RoleCache:
    """Role definitions, fetched once each.

    A subject with forty assignments usually holds a handful of distinct roles,
    and a role that failed to read is remembered as failed rather than retried
    once per assignment.
    """

    def __init__(self, source: PermissionSource, diagnostics: Diagnostics) -> None:
        self._source = source
        self._diagnostics = diagnostics
        self._cache: dict[str, RoleDefinition | None] = {}

    def get(self, role_definition_id: str) -> RoleDefinition | None:
        if role_definition_id not in self._cache:
            definition = self._source.role_definition(role_definition_id)
            if definition is None:
                self._diagnostics.add(
                    UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
                    (
                        "a role definition could not be read, so the permissions "
                        "it grants are missing"
                    ),
                    role_definition_id,
                )
            self._cache[role_definition_id] = definition
        return self._cache[role_definition_id]


def _principal_step(
    principal_id: str,
    identity: IdentityRef,
    membership: Membership,
    diagnostics: Diagnostics,
) -> DerivationStep | None:
    """How the grant reaches the subject: directly, or through which groups.

    None means the grant is the subject's own. An unresolvable principal is
    reported and still described, because dropping the permission would be
    worse than naming the gap.
    """
    if principal_id.casefold() == identity.object_id.casefold():
        return None

    path = membership.path_for(principal_id)
    if path is not None:
        return DerivationStep(
            kind=DerivationKind.GROUP_MEMBERSHIP,
            label=path.label(),
            ref=path.target.object_id,
        )

    diagnostics.add(
        UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
        (
            "an assignment reaches this identity through a principal that could "
            "not be identified, so the chain below it is incomplete"
        ),
        principal_id,
    )
    return DerivationStep(
        kind=DerivationKind.GROUP_MEMBERSHIP,
        label=f"through unidentified principal {principal_id}",
        ref=principal_id,
    )


def _flag_scope(scope: str, ref: str, diagnostics: Diagnostics) -> None:
    if is_management_group_scope(scope):
        diagnostics.add(
            UnsupportedConstructKind.MANAGEMENT_GROUP_INHERITANCE,
            (
                "a grant comes from a management group; arcet does not resolve "
                "that hierarchy, so what it grants may be wider than shown"
            ),
            ref,
        )


def _permissions_for(
    role: RoleDefinition,
    scope: str,
    state: PermissionState,
    steps: Sequence[DerivationStep],
    catalogue: Sequence[ProviderOperation] | None,
    diagnostics: Diagnostics,
    *,
    expand: bool,
) -> list[EffectivePermission]:
    resolved = resolve_actions(
        role, catalogue, expand=expand, diagnostics=diagnostics, ref=role.id
    )
    return [
        EffectivePermission(
            action=action,
            action_kind=action_kind,
            state=state,
            scope=scope,
            derivation=tuple(steps),
        )
        for action, action_kind in resolved
    ]


def _from_assignments(
    assignments: Iterable[RoleAssignment],
    identity: IdentityRef,
    membership: Membership,
    roles: _RoleCache,
    catalogue: Sequence[ProviderOperation] | None,
    diagnostics: Diagnostics,
    *,
    expand: bool,
    activated: frozenset[str],
) -> list[EffectivePermission]:
    permissions: list[EffectivePermission] = []
    for assignment in assignments:
        if assignment.condition:
            diagnostics.add(
                UnsupportedConstructKind.ABAC_CONDITION,
                (
                    "an assignment carries a condition that arcet does not "
                    "evaluate, so it may grant less than shown"
                ),
                assignment.id,
            )
        _flag_scope(assignment.scope, assignment.id, diagnostics)

        role = roles.get(assignment.role_definition_id)
        if role is None:
            continue

        steps: list[DerivationStep] = []
        group_step = _principal_step(
            assignment.principal_id, identity, membership, diagnostics
        )
        if group_step is not None:
            steps.append(group_step)

        if assignment.id.casefold() in activated:
            # Active because someone activated it, not because it was standing.
            # The model allows a PIM step on an active permission for exactly
            # this: it is held now, and the chain says how it came to be.
            steps.append(
                DerivationStep(
                    kind=DerivationKind.PIM_ELIGIBLE,
                    label=f'role "{role.name}" activated through PIM',
                    ref=assignment.id,
                )
            )

        steps.append(
            DerivationStep(
                kind=(
                    DerivationKind.DIRECT_ASSIGNMENT
                    if group_step is None
                    else DerivationKind.ROLE_ASSIGNMENT
                ),
                label=f'role "{role.name}"',
                ref=assignment.id or assignment.role_definition_id,
            )
        )

        permissions.extend(
            _permissions_for(
                role,
                assignment.scope,
                PermissionState.ACTIVE,
                steps,
                catalogue,
                diagnostics,
                expand=expand,
            )
        )
    return permissions


def _from_eligibilities(
    eligibilities: Iterable[EligibleAssignment],
    identity: IdentityRef,
    membership: Membership,
    roles: _RoleCache,
    catalogue: Sequence[ProviderOperation] | None,
    diagnostics: Diagnostics,
    *,
    expand: bool,
) -> list[EffectivePermission]:
    permissions: list[EffectivePermission] = []
    for eligibility in eligibilities:
        _flag_scope(eligibility.scope, eligibility.id, diagnostics)

        role = roles.get(eligibility.role_definition_id)
        if role is None:
            continue

        steps: list[DerivationStep] = []
        if eligibility.member_type.casefold() == "group":
            group_step = _principal_step(
                eligibility.principal_id, identity, membership, diagnostics
            )
            if group_step is not None:
                steps.append(group_step)

        # The eligibility step is what makes the permission representable as
        # PIM_ELIGIBLE at all: the model refuses that state without it.
        steps.append(
            DerivationStep(
                kind=DerivationKind.PIM_ELIGIBLE,
                label=f'role "{role.name}" (eligible, not active)',
                ref=eligibility.id or eligibility.role_definition_id,
            )
        )

        permissions.extend(
            _permissions_for(
                role,
                eligibility.scope,
                PermissionState.PIM_ELIGIBLE,
                steps,
                catalogue,
                diagnostics,
                expand=expand,
            )
        )
    return permissions


def _report_deny_assignments(
    deny_assignments: Sequence[DenyAssignmentRef], diagnostics: Diagnostics
) -> None:
    """Say that deny assignments exist, since v0.1 cannot evaluate them.

    A deny assignment can take away something listed above it. Not saying so
    would leave every permission in the output slightly less true than it
    looks.
    """
    if not deny_assignments:
        return
    count = len(deny_assignments)
    if count == 1:
        subject, verb, pronoun = "deny assignment", "was", "it"
    else:
        subject, verb, pronoun = "deny assignments", "were", "they"
    diagnostics.add(
        UnsupportedConstructKind.DENY_ASSIGNMENT,
        (
            f"{count} {subject} in scope {verb} not evaluated; {pronoun} may "
            f"remove permissions listed here"
        ),
    )
