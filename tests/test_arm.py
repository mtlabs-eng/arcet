"""Tests for the ARM payload parsers.

Fed by recorded fixtures. Nothing here reaches the network.
"""

from __future__ import annotations

from arcet.arm import (
    is_subscription_scope,
    parse_provider_operations,
    parse_role_assignment,
    parse_role_definition,
    scope_chain,
)
from conftest import load_fixture

SUBSCRIPTION = "/subscriptions/00000000-1111-2222-3333-444444444444"


class TestRoleDefinition:
    def test_builtin(self) -> None:
        role = parse_role_definition(load_fixture("role_definition_builtin.json"))
        assert role.name == "Key Vault Secrets User"
        assert role.is_custom is False
        assert role.actions == ()
        assert "Microsoft.KeyVault/vaults/secrets/getSecret/action" in role.data_actions

    def test_custom_is_flagged(self) -> None:
        role = parse_role_definition(load_fixture("role_definition_custom.json"))
        assert role.is_custom is True

    def test_all_permission_blocks_are_merged(self) -> None:
        """A role's grant is the union of its blocks.

        Reading only the first would under-report every role that uses more
        than one, and several built-ins do.
        """
        role = parse_role_definition(load_fixture("role_definition_custom.json"))
        assert role.actions == (
            "Microsoft.KeyVault/*/read",
            "Microsoft.Resources/subscriptions/resourceGroups/read",
        )
        assert role.not_actions == ("Microsoft.KeyVault/vaults/keys/read",)
        assert role.data_actions == (
            "Microsoft.KeyVault/vaults/secrets/getSecret/action",
        )

    def test_missing_properties_do_not_crash(self) -> None:
        """One odd role must not cost us the other forty."""
        role = parse_role_definition({"id": "/x"})
        assert role.id == "/x"
        assert role.actions == ()
        assert role.is_custom is False

    def test_non_string_entries_are_dropped(self) -> None:
        role = parse_role_definition(
            {"properties": {"permissions": [{"actions": ["a/read", 7, None]}]}}
        )
        assert role.actions == ("a/read",)

    def test_a_non_list_permissions_block_is_survived(self) -> None:
        role = parse_role_definition({"properties": {"permissions": "nonsense"}})
        assert role.actions == ()


class TestRoleAssignment:
    def test_direct_user_assignment(self) -> None:
        payload = load_fixture("role_assignments.json")[0]
        assignment = parse_role_assignment(payload)
        assert assignment.principal_type == "User"
        assert assignment.principal_id == "99999999-8888-7777-6666-555555555555"
        assert assignment.scope.endswith("/rg-prod")
        assert assignment.condition is None

    def test_group_assignment_keeps_its_principal_type(self) -> None:
        """Group expansion is milestone 4; the type has to survive until then."""
        assignment = parse_role_assignment(load_fixture("role_assignments.json")[1])
        assert assignment.principal_type == "Group"

    def test_abac_condition_is_carried(self) -> None:
        """arcet does not evaluate conditions, so it must not lose them either."""
        assignment = parse_role_assignment(load_fixture("role_assignments.json")[2])
        assert assignment.condition is not None
        assert "StringEquals" in assignment.condition

    def test_empty_condition_reads_as_absent(self) -> None:
        assignment = parse_role_assignment({"properties": {"condition": ""}})
        assert assignment.condition is None

    def test_missing_fields_do_not_crash(self) -> None:
        assignment = parse_role_assignment({})
        assert assignment.principal_id == ""
        assert assignment.condition is None


class TestProviderOperations:
    def test_nested_operations_are_collected(self, catalogue: tuple) -> None:
        """Operations hang off providers and off each resource type.

        Missing the nested ones would make every expanded role look far
        smaller than it is.
        """
        names = {op.name for op in catalogue}
        assert "Microsoft.KeyVault/register/action" in names
        assert "Microsoft.KeyVault/vaults/read" in names

    def test_data_actions_are_marked(self, catalogue: tuple) -> None:
        by_name = {op.name: op for op in catalogue}
        assert by_name[
            "Microsoft.KeyVault/vaults/secrets/getSecret/action"
        ].is_data_action
        assert not by_name["Microsoft.KeyVault/vaults/secrets/read"].is_data_action

    def test_duplicates_collapse(self) -> None:
        payload = [
            {"operations": [{"name": "a/read", "isDataAction": False}]},
            {"operations": [{"name": "a/read", "isDataAction": False}]},
        ]
        assert len(parse_provider_operations(payload)) == 1

    def test_malformed_entries_are_skipped(self) -> None:
        payload = [{"operations": ["nonsense", {"noName": True}, None]}]
        assert parse_provider_operations(payload) == ()


class TestScopes:
    def test_subscription_scope_is_its_own_chain(self) -> None:
        assert scope_chain(SUBSCRIPTION) == (SUBSCRIPTION,)

    def test_resource_group_inherits_the_subscription(self) -> None:
        assert scope_chain(f"{SUBSCRIPTION}/resourceGroups/rg-prod") == (
            SUBSCRIPTION,
            f"{SUBSCRIPTION}/resourceGroups/rg-prod",
        )

    def test_chain_is_broadest_first(self) -> None:
        chain = scope_chain(f"{SUBSCRIPTION}/resourceGroups/rg/providers/X/vaults/v")
        assert chain[0] == SUBSCRIPTION
        assert chain == tuple(sorted(chain, key=len))

    def test_is_subscription_scope(self) -> None:
        assert is_subscription_scope(SUBSCRIPTION)
        assert not is_subscription_scope(f"{SUBSCRIPTION}/resourceGroups/rg")
