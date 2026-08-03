"""Shared in-memory fixtures.

Nothing here touches Azure, and nothing reads from disk. Milestone 3 records
real payloads into tests/fixtures/; until then results are built by hand,
which is also the point of building the renderers before the client.
"""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from arcet.model import (
    ActionKind,
    DerivationKind,
    DerivationStep,
    EffectivePermission,
    IdentityKind,
    IdentityRef,
    PermissionState,
    ResolutionResult,
    UnsupportedConstruct,
    UnsupportedConstructKind,
)

SUBSCRIPTION = "00000000-1111-2222-3333-444444444444"
RG_SCOPE = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-prod"
SUB_SCOPE = f"/subscriptions/{SUBSCRIPTION}"

USER = IdentityRef(
    object_id="99999999-8888-7777-6666-555555555555",
    display_name="user@empresa.pt",
    kind=IdentityKind.USER,
)

DIRECT_STEP = DerivationStep(
    kind=DerivationKind.DIRECT_ASSIGNMENT,
    label='role "Reader" assigned directly',
    ref=SUB_SCOPE,
)
GROUP_STEP = DerivationStep(
    kind=DerivationKind.GROUP_MEMBERSHIP,
    label='group "Platform" → group "SRE" (nested)',
    ref="/groups/aaaaaaaa-0000-0000-0000-000000000001",
)
ROLE_STEP = DerivationStep(
    kind=DerivationKind.ROLE_ASSIGNMENT,
    label='role "Key Vault Secrets User"',
    ref=RG_SCOPE,
)
PIM_STEP = DerivationStep(
    kind=DerivationKind.PIM_ELIGIBLE,
    label='role "User Access Administrator" (eligible)',
    ref=SUB_SCOPE,
)


def make_permission(
    action: str = "Microsoft.KeyVault/vaults/secrets/read",
    *,
    action_kind: ActionKind = ActionKind.CONTROL_PLANE,
    state: PermissionState = PermissionState.ACTIVE,
    scope: str = RG_SCOPE,
    derivation: tuple[DerivationStep, ...] = (GROUP_STEP, ROLE_STEP),
) -> EffectivePermission:
    return EffectivePermission(
        action=action,
        action_kind=action_kind,
        state=state,
        scope=scope,
        derivation=derivation,
    )


ACTIVE_PERMISSION = make_permission()
DATA_PLANE_PERMISSION = make_permission(
    action="Microsoft.KeyVault/vaults/secrets/getSecret/action",
    action_kind=ActionKind.DATA_PLANE,
)
ELIGIBLE_PERMISSION = make_permission(
    action="Microsoft.Authorization/roleAssignments/write",
    state=PermissionState.PIM_ELIGIBLE,
    scope=SUB_SCOPE,
    derivation=(PIM_STEP,),
)

DENY_WARNING = UnsupportedConstruct(
    kind=UnsupportedConstructKind.DENY_ASSIGNMENT,
    message="1 deny assignment found and not evaluated",
    ref=SUB_SCOPE,
)
READ_ACCESS_WARNING = UnsupportedConstruct(
    kind=UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
    message="could not list role assignments; some permissions may be missing",
    ref=RG_SCOPE,
)


@pytest.fixture
def mixed_result() -> ResolutionResult:
    """One active permission, one data plane one, and one PIM-eligible."""
    return ResolutionResult(
        identity=USER,
        subscription=SUBSCRIPTION,
        permissions=(ACTIVE_PERMISSION, DATA_PLANE_PERMISSION, ELIGIBLE_PERMISSION),
    )


@pytest.fixture
def active_only_result() -> ResolutionResult:
    return ResolutionResult(
        identity=USER, subscription=SUBSCRIPTION, permissions=(ACTIVE_PERMISSION,)
    )


@pytest.fixture
def eligible_only_result() -> ResolutionResult:
    """Nothing held now, one thing an activation away. The dangerous shape."""
    return ResolutionResult(
        identity=USER, subscription=SUBSCRIPTION, permissions=(ELIGIBLE_PERMISSION,)
    )


@pytest.fixture
def empty_result() -> ResolutionResult:
    return ResolutionResult(identity=USER, subscription=SUBSCRIPTION)


@pytest.fixture
def incomplete_result() -> ResolutionResult:
    return ResolutionResult(
        identity=USER,
        subscription=SUBSCRIPTION,
        permissions=(ACTIVE_PERMISSION,),
        warnings=(DENY_WARNING, READ_ACCESS_WARNING),
    )


@pytest.fixture
def console() -> Console:
    """A console that behaves like a redirected stream: fixed width, no colour."""
    return Console(
        file=StringIO(),
        width=100,
        force_terminal=False,
        no_color=True,
        highlight=False,
    )


def output_of(console: Console) -> str:
    """Read back everything printed to a test console."""
    assert isinstance(console.file, StringIO)
    return console.file.getvalue()
