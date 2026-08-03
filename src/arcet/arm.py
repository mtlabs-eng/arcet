"""Reading role assignments and role definitions from ARM.

The parsing here is pure: it turns payloads into typed records and nothing
else. Everything that touches the network lives in `AzureReader`, which is
deliberately thin, so that the logic worth being sure about is the logic the
tests can reach without a tenant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DenyAssignmentRef",
    "EligibleAssignment",
    "ProviderOperation",
    "RoleAssignment",
    "RoleDefinition",
    "is_management_group_scope",
    "is_subscription_scope",
    "parse_activated_assignment_ids",
    "parse_deny_assignment",
    "parse_eligible_assignment",
    "parse_provider_operations",
    "parse_role_assignment",
    "parse_role_definition",
    "scope_chain",
]


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """A built-in or custom role, as ARM describes it."""

    id: str
    name: str
    is_custom: bool
    actions: tuple[str, ...]
    not_actions: tuple[str, ...]
    data_actions: tuple[str, ...]
    not_data_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    """One grant of a role to a principal at a scope."""

    id: str
    principal_id: str
    principal_type: str
    role_definition_id: str
    scope: str
    #: An ABAC condition, when the assignment carries one. arcet does not
    #: evaluate these in v0.1; its presence must reach the reader as a warning.
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class EligibleAssignment:
    """A role a principal may activate, but does not currently hold.

    Kept apart from RoleAssignment on purpose. The whole point of the tool is
    that "can activate this in five minutes" and "has this now" never blur, and
    a single type carrying a flag is how they eventually would.
    """

    id: str
    principal_id: str
    principal_type: str
    role_definition_id: str
    scope: str
    #: "Direct" when the eligibility is the principal's own, "Group" when it
    #: reaches them through a group.
    member_type: str
    status: str


@dataclass(frozen=True, slots=True)
class DenyAssignmentRef:
    """A deny assignment, recorded but not evaluated in v0.1."""

    id: str
    name: str
    is_system_protected: bool


@dataclass(frozen=True, slots=True)
class ProviderOperation:
    """One concrete action from the provider operations catalogue."""

    name: str
    is_data_action: bool


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _strings(value: Any) -> tuple[str, ...]:
    """Read a list of strings, ignoring anything that is not one.

    ARM has never returned a non-string here, but coercing beats crashing on a
    payload shape we have not seen: a tool that dies on one odd role tells the
    reader nothing about the other forty.
    """
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def parse_role_definition(payload: dict[str, Any]) -> RoleDefinition:
    """Turn an ARM role definition payload into a RoleDefinition.

    A role carries a *list* of permission blocks, and its effective grant is
    the union of them. Reading only the first would quietly under-report every
    role that uses more than one, which several built-ins do.
    """
    properties = payload.get("properties") or {}
    blocks = properties.get("permissions")
    blocks = blocks if isinstance(blocks, list) else []

    actions: list[str] = []
    not_actions: list[str] = []
    data_actions: list[str] = []
    not_data_actions: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        actions.extend(_strings(block.get("actions")))
        not_actions.extend(_strings(block.get("notActions")))
        data_actions.extend(_strings(block.get("dataActions")))
        not_data_actions.extend(_strings(block.get("notDataActions")))

    return RoleDefinition(
        id=_text(payload.get("id")),
        name=_text(properties.get("roleName")),
        # ARM spells this "CustomRole" or "BuiltInRole"; anything else is
        # treated as built-in, since custom is the claim that needs evidence.
        is_custom=_text(properties.get("type")) == "CustomRole",
        actions=tuple(actions),
        not_actions=tuple(not_actions),
        data_actions=tuple(data_actions),
        not_data_actions=tuple(not_data_actions),
    )


def parse_role_assignment(payload: dict[str, Any]) -> RoleAssignment:
    """Turn an ARM role assignment payload into a RoleAssignment."""
    properties = payload.get("properties") or {}
    condition = properties.get("condition")
    return RoleAssignment(
        id=_text(payload.get("id")),
        principal_id=_text(properties.get("principalId")),
        principal_type=_text(properties.get("principalType")),
        role_definition_id=_text(properties.get("roleDefinitionId")),
        scope=_text(properties.get("scope")),
        condition=condition if isinstance(condition, str) and condition else None,
    )


def parse_eligible_assignment(payload: dict[str, Any]) -> EligibleAssignment:
    """Turn a role eligibility schedule instance into an EligibleAssignment."""
    properties = payload.get("properties") or {}
    return EligibleAssignment(
        id=_text(payload.get("id")),
        principal_id=_text(properties.get("principalId")),
        principal_type=_text(properties.get("principalType")),
        role_definition_id=_text(properties.get("roleDefinitionId")),
        scope=_text(properties.get("scope")),
        member_type=_text(properties.get("memberType")),
        status=_text(properties.get("status")),
    )


def parse_deny_assignment(payload: dict[str, Any]) -> DenyAssignmentRef:
    """Turn a deny assignment payload into the little of it we report."""
    properties = payload.get("properties") or {}
    return DenyAssignmentRef(
        id=_text(payload.get("id")),
        name=_text(properties.get("denyAssignmentName")) or _text(payload.get("name")),
        is_system_protected=bool(properties.get("isSystemProtected")),
    )


def parse_activated_assignment_ids(payloads: list[dict[str, Any]]) -> frozenset[str]:
    """Role assignment ids that exist because someone activated a PIM role.

    These already appear in the ordinary assignment list, so they are not a
    second source of permissions — they only let the chain say that an active
    permission got there through an activation rather than a standing grant.
    """
    activated: set[str] = set()
    for payload in payloads:
        properties = payload.get("properties") or {}
        if _text(properties.get("assignmentType")) != "Activated":
            continue
        origin = _text(properties.get("originRoleAssignmentId"))
        if origin:
            activated.add(origin.casefold())
    return frozenset(activated)


def is_management_group_scope(scope: str) -> bool:
    """Whether a scope sits in the management group hierarchy.

    arcet does not walk that inheritance in v0.1, so a permission arriving from
    there is reported with a warning rather than silently attributed to the
    subscription.
    """
    return scope.casefold().startswith(
        "/providers/microsoft.management/managementgroups/"
    )


def parse_provider_operations(
    payloads: list[dict[str, Any]],
) -> tuple[ProviderOperation, ...]:
    """Flatten the provider operations catalogue.

    Operations hang off a provider both directly and under each resource type,
    and a wildcard has to be matched against all of them. Missing the nested
    ones would make an expanded role look far smaller than it is.
    """
    operations: list[ProviderOperation] = []
    seen: set[str] = set()

    def collect(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            if not name or name in seen:
                continue
            seen.add(name)
            operations.append(
                ProviderOperation(
                    name=name, is_data_action=bool(item.get("isDataAction"))
                )
            )

    for payload in payloads:
        collect(payload.get("operations"))
        for resource_type in payload.get("resourceTypes") or []:
            if isinstance(resource_type, dict):
                collect(resource_type.get("operations"))

    return tuple(operations)


_SUBSCRIPTION_SCOPE = re.compile(r"^/subscriptions/[^/]+$", re.IGNORECASE)


def scope_chain(scope: str) -> tuple[str, ...]:
    """Every scope an assignment at `scope` is inherited by, broadest first.

    '/subscriptions/s/resourceGroups/rg' yields the subscription and then the
    resource group. Management groups are not walked: arcet does not resolve
    that inheritance in v0.1, and the caller warns rather than guessing.
    """
    parts = [part for part in scope.split("/") if part]
    chain: list[str] = []
    for index in range(0, len(parts), 2):
        chain.append("/" + "/".join(parts[: index + 2]))
    return tuple(chain)


def is_subscription_scope(scope: str) -> bool:
    """Whether a scope is exactly a subscription, with nothing below it."""
    return bool(_SUBSCRIPTION_SCOPE.match(scope))
