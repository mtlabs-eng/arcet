"""Tests for the resolver, against a source backed by fixtures.

The point of putting Azure behind a protocol is exactly this file: every
judgement the tool makes is exercised here, and none of it needs a tenant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from arcet.arm import (
    DenyAssignmentRef,
    EligibleAssignment,
    ProviderOperation,
    RoleAssignment,
    RoleDefinition,
    parse_provider_operations,
    parse_role_definition,
)
from arcet.diagnostics import Diagnostics
from arcet.groups import GroupRef, Membership, walk_membership
from arcet.model import (
    DerivationKind,
    IdentityKind,
    IdentityRef,
    PermissionState,
    UnsupportedConstructKind,
)
from arcet.resolve import IdentityNotFound, resolve
from conftest import load_fixture

SUBSCRIPTION = "00000000-1111-2222-3333-444444444444"
SUB_SCOPE = f"/subscriptions/{SUBSCRIPTION}"
RG_SCOPE = f"{SUB_SCOPE}/resourceGroups/rg-prod"
MG_SCOPE = "/providers/Microsoft.Management/managementGroups/mg-root"

USER_ID = "99999999-8888-7777-6666-555555555555"
GROUP_ID = "aaaaaaaa-0000-0000-0000-000000000001"
NESTED_ID = "bbbbbbbb-0000-0000-0000-000000000002"

IDENTITY = IdentityRef(
    object_id=USER_ID, display_name="user@empresa.pt", kind=IdentityKind.USER
)

KEY_VAULT_ROLE = parse_role_definition(load_fixture("role_definition_builtin.json"))
CUSTOM_ROLE = parse_role_definition(load_fixture("role_definition_custom.json"))
ADMIN_ROLE = RoleDefinition(
    id="/roleDefinitions/uaa",
    name="User Access Administrator",
    is_custom=False,
    actions=("Microsoft.Authorization/roleAssignments/write",),
    not_actions=(),
    data_actions=(),
    not_data_actions=(),
)


def assignment(
    *,
    principal_id: str = USER_ID,
    role: RoleDefinition = KEY_VAULT_ROLE,
    scope: str = RG_SCOPE,
    condition: str | None = None,
    assignment_id: str = "/roleAssignments/a1",
) -> RoleAssignment:
    return RoleAssignment(
        id=assignment_id,
        principal_id=principal_id,
        principal_type="User" if principal_id == USER_ID else "Group",
        role_definition_id=role.id,
        scope=scope,
        condition=condition,
    )


def eligibility(
    *,
    principal_id: str = USER_ID,
    role: RoleDefinition = ADMIN_ROLE,
    scope: str = SUB_SCOPE,
    member_type: str = "Direct",
) -> EligibleAssignment:
    return EligibleAssignment(
        id="/roleEligibility/e1",
        principal_id=principal_id,
        principal_type="User",
        role_definition_id=role.id,
        scope=scope,
        member_type=member_type,
        status="Provisioned",
    )


def membership_of(*chains: tuple[GroupRef, ...]) -> Membership:
    edges: dict[str, tuple[GroupRef, ...]] = {}
    for chain in chains:
        previous = USER_ID
        for group in chain:
            edges[previous] = (*edges.get(previous, ()), group)
            previous = group.object_id
    return walk_membership(USER_ID, lambda oid: edges.get(oid, ()))


@dataclass
class FakeSource:
    """A PermissionSource that answers from memory."""

    identity: IdentityRef | None = IDENTITY
    membership: Membership = field(
        default_factory=lambda: walk_membership(USER_ID, lambda _: ())
    )
    transitive: frozenset[str] = frozenset()
    assignments: tuple[RoleAssignment, ...] = ()
    eligibilities: tuple[EligibleAssignment, ...] = ()
    activated: frozenset[str] = frozenset()
    denies: tuple[DenyAssignmentRef, ...] = ()
    roles: dict[str, RoleDefinition | None] = field(default_factory=dict)
    catalogue: tuple[ProviderOperation, ...] | None = None

    def find_identity(self, identifier: str) -> IdentityRef | None:
        del identifier
        return self.identity

    def group_membership(self, object_id: str) -> Membership:
        del object_id
        return self.membership

    def transitive_group_ids(self, object_id: str) -> frozenset[str]:
        del object_id
        return self.transitive

    def role_assignments_for(self, object_id: str) -> tuple[RoleAssignment, ...]:
        del object_id
        return self.assignments

    def eligible_assignments(self, object_id: str) -> tuple[EligibleAssignment, ...]:
        del object_id
        return self.eligibilities

    def activated_assignment_ids(self, object_id: str) -> frozenset[str]:
        del object_id
        return self.activated

    def deny_assignments(self) -> tuple[DenyAssignmentRef, ...]:
        return self.denies

    def role_definition(self, role_definition_id: str) -> RoleDefinition | None:
        return self.roles.get(role_definition_id)

    def provider_operations(self) -> tuple[ProviderOperation, ...] | None:
        return self.catalogue


@pytest.fixture
def source() -> FakeSource:
    catalogue = parse_provider_operations(load_fixture("provider_operations.json"))
    return FakeSource(
        catalogue=catalogue,
        roles={
            KEY_VAULT_ROLE.id: KEY_VAULT_ROLE,
            CUSTOM_ROLE.id: CUSTOM_ROLE,
            ADMIN_ROLE.id: ADMIN_ROLE,
        },
    )


def kinds(result) -> list[UnsupportedConstructKind]:
    return [warning.kind for warning in result.warnings]


class TestIdentity:
    def test_missing_identity_raises(self, source: FakeSource) -> None:
        source.identity = None
        with pytest.raises(IdentityNotFound):
            resolve("nobody@empresa.pt", SUBSCRIPTION, source)

    def test_the_identity_is_carried(self, source: FakeSource) -> None:
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.identity == IDENTITY
        assert result.subscription == SUBSCRIPTION


class TestDirectAssignments:
    def test_a_direct_assignment_yields_its_actions(self, source: FakeSource) -> None:
        source.assignments = (assignment(),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert [p.action for p in result.permissions] == [
            "Microsoft.KeyVault/vaults/secrets/getSecret/action",
            "Microsoft.KeyVault/vaults/secrets/readMetadata/action",
        ]
        assert all(p.state is PermissionState.ACTIVE for p in result.permissions)

    def test_the_chain_names_the_role(self, source: FakeSource) -> None:
        source.assignments = (assignment(),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        step = result.permissions[0].derivation[-1]
        assert step.kind is DerivationKind.DIRECT_ASSIGNMENT
        assert step.label == 'role "Key Vault Secrets User"'

    def test_the_scope_is_the_assignment_scope(self, source: FakeSource) -> None:
        source.assignments = (assignment(scope=RG_SCOPE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions[0].scope == RG_SCOPE

    def test_a_role_that_cannot_be_read_is_reported_not_dropped_quietly(
        self, source: FakeSource
    ) -> None:
        source.assignments = (assignment(),)
        source.roles = {}
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions == ()
        assert UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS in kinds(result)

    def test_a_role_is_fetched_once_per_definition(self, source: FakeSource) -> None:
        calls: list[str] = []
        original = source.role_definition

        def counting(role_id: str) -> RoleDefinition | None:
            calls.append(role_id)
            return original(role_id)

        source.role_definition = counting  # type: ignore[method-assign]
        source.assignments = (
            assignment(assignment_id="/a/1"),
            assignment(assignment_id="/a/2"),
        )
        resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert calls == [KEY_VAULT_ROLE.id]


class TestGroupDerivedAssignments:
    def test_a_group_assignment_carries_the_membership_step(
        self, source: FakeSource
    ) -> None:
        source.membership = membership_of((GroupRef(GROUP_ID, "Platform"),))
        source.assignments = (assignment(principal_id=GROUP_ID),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        first = result.permissions[0].derivation[0]
        assert first.kind is DerivationKind.GROUP_MEMBERSHIP
        assert first.label == 'group "Platform"'

    def test_nested_groups_show_the_whole_path(self, source: FakeSource) -> None:
        """The point of walking instead of asking for the flat set."""
        source.membership = membership_of(
            (GroupRef(GROUP_ID, "Platform"), GroupRef(NESTED_ID, "SRE"))
        )
        source.assignments = (assignment(principal_id=NESTED_ID),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions[0].derivation[0].label == (
            'group "Platform" → group "SRE" (nested)'
        )

    def test_the_role_step_follows_the_group_step(self, source: FakeSource) -> None:
        source.membership = membership_of((GroupRef(GROUP_ID, "Platform"),))
        source.assignments = (assignment(principal_id=GROUP_ID),)
        chain = (
            resolve("user@empresa.pt", SUBSCRIPTION, source).permissions[0].derivation
        )
        assert [step.kind for step in chain] == [
            DerivationKind.GROUP_MEMBERSHIP,
            DerivationKind.ROLE_ASSIGNMENT,
        ]

    def test_an_unidentifiable_principal_keeps_the_permission_and_warns(
        self, source: FakeSource
    ) -> None:
        """Dropping the permission would be worse than naming the gap."""
        source.assignments = (
            assignment(principal_id="cccccccc-0000-0000-0000-000000000009"),
        )
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions
        assert UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS in kinds(result)
        assert "unidentified principal" in result.permissions[0].derivation[0].label


class TestCrossCheck:
    def test_a_group_the_walk_missed_is_reported(self, source: FakeSource) -> None:
        source.membership = membership_of((GroupRef(GROUP_ID, "Platform"),))
        source.transitive = frozenset({GROUP_ID, "g-unreachable"})
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS in kinds(result)
        assert any("could not be walked" in w.message for w in result.warnings)

    def test_no_warning_when_the_walk_is_complete(self, source: FakeSource) -> None:
        source.membership = membership_of((GroupRef(GROUP_ID, "Platform"),))
        source.transitive = frozenset({GROUP_ID})
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.is_complete

    def test_depth_cap_notes_become_warnings(self, source: FakeSource) -> None:
        source.membership = Membership(
            paths=(), reached=frozenset(), notes=("stopped",)
        )
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert "stopped" in [w.message for w in result.warnings]


class TestPim:
    def test_an_eligibility_is_never_active(self, source: FakeSource) -> None:
        source.eligibilities = (eligibility(),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions
        assert all(p.state is PermissionState.PIM_ELIGIBLE for p in result.permissions)

    def test_the_eligibility_step_justifies_the_state(self, source: FakeSource) -> None:
        """The model refuses PIM_ELIGIBLE without it, so this is load-bearing."""
        source.eligibilities = (eligibility(),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert any(
            step.kind is DerivationKind.PIM_ELIGIBLE
            for step in result.permissions[0].derivation
        )

    def test_a_group_eligibility_carries_the_group(self, source: FakeSource) -> None:
        source.membership = membership_of((GroupRef(GROUP_ID, "Platform"),))
        source.eligibilities = (
            eligibility(principal_id=GROUP_ID, member_type="Group"),
        )
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert (
            result.permissions[0].derivation[0].kind is DerivationKind.GROUP_MEMBERSHIP
        )

    def test_active_and_eligible_coexist_without_merging(
        self, source: FakeSource
    ) -> None:
        source.assignments = (assignment(),)
        source.eligibilities = (eligibility(),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        states = {p.state for p in result.permissions}
        assert states == {PermissionState.ACTIVE, PermissionState.PIM_ELIGIBLE}

    def test_an_activated_assignment_is_active_and_says_so(
        self, source: FakeSource
    ) -> None:
        """Activated PIM is held now. The chain explains how, the state does not lie."""
        source.assignments = (assignment(assignment_id="/roleAssignments/a9"),)
        source.activated = frozenset({"/roleassignments/a9"})
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        permission = result.permissions[0]
        assert permission.state is PermissionState.ACTIVE
        assert any(
            "activated through PIM" in step.label for step in permission.derivation
        )

    def test_an_activated_assignment_is_not_counted_twice(
        self, source: FakeSource
    ) -> None:
        source.assignments = (assignment(assignment_id="/roleAssignments/a9"),)
        source.activated = frozenset({"/roleassignments/a9"})
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        actions = [p.action for p in result.permissions]
        assert len(actions) == len(set(actions))


class TestUnsupportedConstructs:
    def test_deny_assignments_are_reported(self, source: FakeSource) -> None:
        source.denies = (
            DenyAssignmentRef(id="/d/1", name="block", is_system_protected=True),
        )
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.DENY_ASSIGNMENT in kinds(result)
        assert not result.is_complete

    def test_no_deny_assignments_means_no_warning(self, source: FakeSource) -> None:
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.DENY_ASSIGNMENT not in kinds(result)

    def test_an_abac_condition_is_reported(self, source: FakeSource) -> None:
        source.assignments = (assignment(condition="@Resource[x] StringEquals 'y'"),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.ABAC_CONDITION in kinds(result)

    def test_a_conditioned_assignment_still_yields_its_permissions(
        self, source: FakeSource
    ) -> None:
        """The condition narrows the grant; it does not remove it."""
        source.assignments = (assignment(condition="@Resource[x] StringEquals 'y'"),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions

    def test_a_management_group_scope_is_reported(self, source: FakeSource) -> None:
        source.assignments = (assignment(scope=MG_SCOPE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.MANAGEMENT_GROUP_INHERITANCE in kinds(result)

    def test_a_subscription_scope_is_not_reported_as_a_management_group(
        self, source: FakeSource
    ) -> None:
        source.assignments = (assignment(scope=SUB_SCOPE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert UnsupportedConstructKind.MANAGEMENT_GROUP_INHERITANCE not in kinds(
            result
        )


class TestExpansion:
    def test_expansion_is_applied(self, source: FakeSource) -> None:
        source.assignments = (assignment(role=CUSTOM_ROLE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source, expand=True)
        assert "Microsoft.KeyVault/vaults/read" in [
            p.action for p in result.permissions
        ]

    def test_no_expand_keeps_the_pattern(self, source: FakeSource) -> None:
        source.assignments = (assignment(role=CUSTOM_ROLE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source, expand=False)
        assert "Microsoft.KeyVault/*/read" in [p.action for p in result.permissions]

    def test_no_expand_reports_unsubtractable_exclusions(
        self, source: FakeSource
    ) -> None:
        source.assignments = (assignment(role=CUSTOM_ROLE),)
        result = resolve("user@empresa.pt", SUBSCRIPTION, source, expand=False)
        assert any("broader than what is granted" in w.message for w in result.warnings)


class TestSharedDiagnostics:
    def test_warnings_from_the_source_reach_the_result(
        self, source: FakeSource
    ) -> None:
        """A read that failed inside the source must not be stranded there."""
        diagnostics = Diagnostics()
        diagnostics.unreadable("role assignments", SUB_SCOPE, "not authorised")
        result = resolve(
            "user@empresa.pt", SUBSCRIPTION, source, diagnostics=diagnostics
        )
        assert UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS in kinds(result)
        assert not result.is_complete


class TestEmptyAnswer:
    def test_an_identity_with_nothing_is_a_complete_answer(
        self, source: FakeSource
    ) -> None:
        result = resolve("user@empresa.pt", SUBSCRIPTION, source)
        assert result.permissions == ()
        assert result.is_complete
