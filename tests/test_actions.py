"""Tests for wildcard expansion and NotActions subtraction.

This is where being wrong is most expensive. Too permissive reports access
that does not exist; too restrictive hides access that does. Both directions
are checked, and so is the case where the answer cannot be exact.
"""

from __future__ import annotations

import pytest

from arcet.actions import matches, resolve_actions
from arcet.arm import ProviderOperation, RoleDefinition, parse_role_definition
from arcet.diagnostics import Diagnostics
from arcet.model import ActionKind, UnsupportedConstructKind
from conftest import load_fixture


def role(
    *,
    actions: tuple[str, ...] = (),
    not_actions: tuple[str, ...] = (),
    data_actions: tuple[str, ...] = (),
    not_data_actions: tuple[str, ...] = (),
    name: str = "Test Role",
) -> RoleDefinition:
    return RoleDefinition(
        id="/roleDefinitions/test",
        name=name,
        is_custom=True,
        actions=actions,
        not_actions=not_actions,
        data_actions=data_actions,
        not_data_actions=not_data_actions,
    )


def control_actions(resolved: tuple) -> list[str]:
    return [a for a, kind in resolved if kind is ActionKind.CONTROL_PLANE]


def data_actions(resolved: tuple) -> list[str]:
    return [a for a, kind in resolved if kind is ActionKind.DATA_PLANE]


class TestMatching:
    @pytest.mark.parametrize(
        ("pattern", "action", "expected"),
        [
            ("*", "Microsoft.KeyVault/vaults/read", True),
            ("Microsoft.KeyVault/*", "Microsoft.KeyVault/vaults/read", True),
            # A star spans separators, which is how Azure reads it.
            (
                "Microsoft.KeyVault/*/read",
                "Microsoft.KeyVault/vaults/secrets/read",
                True,
            ),
            ("Microsoft.KeyVault/*/read", "Microsoft.KeyVault/vaults/read", True),
            ("Microsoft.KeyVault/*/read", "Microsoft.Storage/vaults/read", False),
            ("Microsoft.KeyVault/vaults/read", "Microsoft.KeyVault/vaults/read", True),
            (
                "Microsoft.KeyVault/vaults/read",
                "Microsoft.KeyVault/vaults/write",
                False,
            ),
            # ARM treats these case-insensitively.
            ("microsoft.keyvault/*", "Microsoft.KeyVault/vaults/read", True),
            # A dot is a literal, not a regex wildcard.
            ("MicrosoftXKeyVault/vaults/read", "Microsoft.KeyVault/vaults/read", False),
        ],
    )
    def test_matches(self, pattern: str, action: str, expected: bool) -> None:
        assert matches(pattern, action) is expected


class TestExpansion:
    def test_a_wildcard_expands_to_concrete_actions(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*/read",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == [
            "Microsoft.KeyVault/vaults/keys/read",
            "Microsoft.KeyVault/vaults/read",
            "Microsoft.KeyVault/vaults/secrets/read",
        ]

    def test_control_and_data_planes_do_not_mix(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        """A control plane wildcard must never pull in a data action.

        Reading a secret's properties and reading its value are different
        grants, and conflating them is the mistake that matters most here.
        """
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert data_actions(resolved) == []
        assert (
            "Microsoft.KeyVault/vaults/secrets/getSecret/action"
            not in control_actions(resolved)
        )

    def test_data_wildcards_expand_against_data_operations(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(data_actions=("Microsoft.KeyVault/vaults/secrets/*",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert data_actions(resolved) == [
            "Microsoft.KeyVault/vaults/secrets/getSecret/action",
            "Microsoft.KeyVault/vaults/secrets/readMetadata/action",
            "Microsoft.KeyVault/vaults/secrets/setSecret/action",
        ]

    def test_star_expands_to_the_whole_control_plane(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(actions=("*",)), catalogue, expand=True, diagnostics=diagnostics
        )
        expected = sorted(op.name for op in catalogue if not op.is_data_action)
        assert control_actions(resolved) == expected

    def test_a_literal_action_survives_an_incomplete_catalogue(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        """The catalogue lags new providers.

        Dropping a named action because a lookup table has not caught up would
        be exactly the silent loss this tool exists to avoid.
        """
        resolved = resolve_actions(
            role(actions=("Microsoft.BrandNew/things/read",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == ["Microsoft.BrandNew/things/read"]
        assert not diagnostics

    def test_a_wildcard_matching_nothing_is_reported(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolve_actions(
            role(actions=("Microsoft.Unknown/*/read",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert diagnostics
        assert "matched no known operation" in diagnostics.snapshot()[0].message

    def test_results_are_sorted_and_deduplicated(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(
                actions=("Microsoft.KeyVault/*/read", "Microsoft.KeyVault/vaults/read")
            ),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        actions = control_actions(resolved)
        assert actions == sorted(actions)
        assert len(actions) == len(set(actions))


class TestSubtraction:
    def test_not_actions_remove_a_concrete_action(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(
                actions=("Microsoft.KeyVault/*/read",),
                not_actions=("Microsoft.KeyVault/vaults/keys/read",),
            ),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert "Microsoft.KeyVault/vaults/keys/read" not in control_actions(resolved)
        assert "Microsoft.KeyVault/vaults/read" in control_actions(resolved)

    def test_a_wildcard_not_action_removes_everything_it_covers(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(actions=("*",), not_actions=("Microsoft.KeyVault/*",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert not any(
            a.startswith("Microsoft.KeyVault") for a in control_actions(resolved)
        )
        assert (
            "Microsoft.Resources/subscriptions/resourceGroups/read"
            in control_actions(resolved)
        )

    def test_not_data_actions_only_touch_the_data_plane(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(
                actions=("Microsoft.KeyVault/*/read",),
                data_actions=("Microsoft.KeyVault/vaults/secrets/*",),
                not_data_actions=(
                    "Microsoft.KeyVault/vaults/secrets/setSecret/action",
                ),
            ),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert "Microsoft.KeyVault/vaults/secrets/setSecret/action" not in data_actions(
            resolved
        )
        assert "Microsoft.KeyVault/vaults/secrets/read" in control_actions(resolved)

    def test_subtracting_everything_leaves_nothing(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*",), not_actions=("*",)),
            catalogue,
            expand=True,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == []


class TestLiteralMode:
    def test_no_expand_returns_the_patterns_as_written(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*/read",)),
            catalogue,
            expand=False,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == ["Microsoft.KeyVault/*/read"]

    def test_unsubtractable_exclusions_are_reported(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        """Printing Actions alone without their NotActions overstates access.

        Without expansion there is nothing concrete to subtract from, so the
        reader is told that what is shown is broader than what is granted.
        """
        resolve_actions(
            role(
                actions=("Microsoft.KeyVault/*",),
                not_actions=("Microsoft.KeyVault/vaults/delete",),
            ),
            catalogue,
            expand=False,
            diagnostics=diagnostics,
        )
        assert diagnostics
        message = diagnostics.snapshot()[0].message
        assert "broader than what is granted" in message
        assert "Microsoft.KeyVault/vaults/delete" in message

    def test_literal_mode_without_exclusions_is_quiet(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        resolve_actions(
            role(actions=("Microsoft.KeyVault/vaults/read",)),
            catalogue,
            expand=False,
            diagnostics=diagnostics,
        )
        assert not diagnostics


class TestMissingCatalogue:
    def test_expansion_without_a_catalogue_warns_and_falls_back(
        self, diagnostics: Diagnostics
    ) -> None:
        """Fewer rows without explanation is the failure mode to avoid."""
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*/read",)),
            None,
            expand=True,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == ["Microsoft.KeyVault/*/read"]
        kinds = [w.kind for w in diagnostics.snapshot()]
        assert UnsupportedConstructKind.UNRECOGNISED in kinds
        assert "could not be read" in diagnostics.snapshot()[0].message


class TestRealRoles:
    def test_builtin_key_vault_secrets_user(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        parsed = parse_role_definition(load_fixture("role_definition_builtin.json"))
        resolved = resolve_actions(
            parsed, catalogue, expand=True, diagnostics=diagnostics
        )
        assert control_actions(resolved) == []
        assert data_actions(resolved) == [
            "Microsoft.KeyVault/vaults/secrets/getSecret/action",
            "Microsoft.KeyVault/vaults/secrets/readMetadata/action",
        ]
        assert not diagnostics

    def test_custom_role_with_two_blocks_and_an_exclusion(
        self, catalogue: tuple, diagnostics: Diagnostics
    ) -> None:
        parsed = parse_role_definition(load_fixture("role_definition_custom.json"))
        resolved = resolve_actions(
            parsed, catalogue, expand=True, diagnostics=diagnostics
        )
        assert control_actions(resolved) == [
            "Microsoft.KeyVault/vaults/read",
            "Microsoft.KeyVault/vaults/secrets/read",
            "Microsoft.Resources/subscriptions/resourceGroups/read",
        ]
        assert data_actions(resolved) == [
            "Microsoft.KeyVault/vaults/secrets/getSecret/action"
        ]
        assert not diagnostics


class TestEmptyCatalogue:
    def test_no_operations_at_all(self, diagnostics: Diagnostics) -> None:
        empty: tuple[ProviderOperation, ...] = ()
        resolved = resolve_actions(
            role(actions=("Microsoft.KeyVault/*",)),
            empty,
            expand=True,
            diagnostics=diagnostics,
        )
        assert control_actions(resolved) == []
        assert diagnostics
