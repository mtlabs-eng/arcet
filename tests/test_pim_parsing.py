"""Tests for the PIM and deny assignment parsers.

These cover the code paths that have never run against a real tenant — the
only one available has no Entra ID P2. Fixtures cannot prove the API returns
what the documentation says it does, but they can prove that when it does, the
parsers read it correctly. That is the half of the risk it is possible to
close from here.
"""

from __future__ import annotations

import pytest

from arcet.arm import (
    is_management_group_scope,
    parse_activated_assignment_ids,
    parse_deny_assignment,
    parse_eligible_assignment,
)
from conftest import load_fixture

SUBSCRIPTION = "/subscriptions/00000000-1111-2222-3333-444444444444"


@pytest.fixture
def pim() -> dict:
    return load_fixture("pim.json")


class TestEligibility:
    def test_a_direct_eligibility(self, pim: dict) -> None:
        e = parse_eligible_assignment(pim["eligibilityInstances"][0])
        assert e.principal_id == "99999999-8888-7777-6666-555555555555"
        assert e.principal_type == "User"
        assert e.member_type == "Direct"
        assert e.status == "Provisioned"
        assert e.scope == SUBSCRIPTION
        assert e.role_definition_id.endswith("18d7d88d-d35e-4fb5-a5c3-7773c20a72d9")

    def test_an_eligibility_reaching_through_a_group(self, pim: dict) -> None:
        """memberType is what tells the resolver to look for a group path."""
        e = parse_eligible_assignment(pim["eligibilityInstances"][1])
        assert e.member_type == "Group"
        assert e.principal_id == "aaaaaaaa-0000-0000-0000-000000000001"

    def test_missing_fields_do_not_crash(self) -> None:
        e = parse_eligible_assignment({})
        assert e.principal_id == ""
        assert e.member_type == ""

    def test_a_null_properties_block(self) -> None:
        assert parse_eligible_assignment({"properties": None}).scope == ""


class TestActivatedAssignments:
    def test_only_activated_entries_are_collected(self, pim: dict) -> None:
        """An Assigned entry is a standing grant, not an activation.

        Both come back from the same API. Treating them alike would label
        every permanent assignment as though someone had activated it.
        """
        ids = parse_activated_assignment_ids(pim["assignmentInstances"])
        assert len(ids) == 1
        assert "11111111-aaaa-bbbb-cccc-111111111111" in next(iter(ids))

    def test_the_origin_assignment_id_is_what_is_matched(self, pim: dict) -> None:
        ids = parse_activated_assignment_ids(pim["assignmentInstances"])
        origin = pim["assignmentInstances"][0]["properties"]["originRoleAssignmentId"]
        assert origin.casefold() in ids

    def test_matching_is_case_insensitive(self, pim: dict) -> None:
        """ARM is inconsistent about the case of resource ids it echoes back."""
        ids = parse_activated_assignment_ids(pim["assignmentInstances"])
        assert all(i == i.casefold() for i in ids)

    def test_an_activation_without_an_origin_is_skipped(self) -> None:
        """Nothing to match against, so recording it would be a false label."""
        payload = [{"properties": {"assignmentType": "Activated"}}]
        assert parse_activated_assignment_ids(payload) == frozenset()

    def test_empty_input(self) -> None:
        assert parse_activated_assignment_ids([]) == frozenset()

    def test_malformed_entries_do_not_crash(self) -> None:
        assert parse_activated_assignment_ids([{}, {"properties": None}]) == frozenset()


class TestDenyAssignments:
    def test_a_system_protected_deny_assignment(self, pim: dict) -> None:
        d = parse_deny_assignment(pim["denyAssignments"][0])
        assert d.name == "Deny writes to managed resources"
        assert d.is_system_protected is True
        assert d.id.endswith("88888888-aaaa-bbbb-cccc-888888888888")

    def test_the_name_falls_back_to_the_resource_name(self) -> None:
        """denyAssignmentName is optional; the resource name always exists."""
        d = parse_deny_assignment({"name": "fallback", "properties": {}})
        assert d.name == "fallback"

    def test_absent_system_protection_reads_as_false(self) -> None:
        assert parse_deny_assignment({"properties": {}}).is_system_protected is False

    def test_missing_fields_do_not_crash(self) -> None:
        d = parse_deny_assignment({})
        assert d.id == ""
        assert d.name == ""


class TestManagementGroupScope:
    @pytest.mark.parametrize(
        ("scope", "expected"),
        [
            ("/providers/Microsoft.Management/managementGroups/mg-root", True),
            # ARM does not promise a stable case for this segment.
            ("/providers/microsoft.management/managementgroups/mg-root", True),
            ("/PROVIDERS/MICROSOFT.MANAGEMENT/MANAGEMENTGROUPS/mg", True),
            (SUBSCRIPTION, False),
            (f"{SUBSCRIPTION}/resourceGroups/rg-prod", False),
            ("", False),
            # A resource that merely mentions the provider is not the hierarchy.
            (f"{SUBSCRIPTION}/providers/Microsoft.Management/somethingElse", False),
        ],
    )
    def test_detection(self, scope: str, expected: bool) -> None:
        assert is_management_group_scope(scope) is expected
