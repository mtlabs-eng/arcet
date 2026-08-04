"""Tests for the list view.

It exists because the chain view spends four or five lines per permission,
which is unreadable when there are fifty of them. A grid with a column per
field was the obvious alternative and does not survive real data — an action,
a scope and a nested group path come to roughly 230 characters, so every
column ends up elided even at 200 columns wide. This view drops the chain
rather than shrinking it, and nothing it does show is ever truncated.
"""

from __future__ import annotations

from io import StringIO

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
from arcet.render import DEFAULT_LIST_LIMIT, OutputFormat, render, render_list

IDENTITY = IdentityRef(
    object_id="99999999-8888-7777-6666-555555555555",
    display_name="alice@example.com",
    kind=IdentityKind.USER,
)
SUB = "/subscriptions/00000000-1111-2222-3333-444444444444"
LONG_SCOPE = (
    f"{SUB}/resourceGroups/rg-platform-prod/providers/Microsoft.Storage"
    f"/storageAccounts/stplatformprod001"
)
DIRECT = DerivationStep(
    kind=DerivationKind.DIRECT_ASSIGNMENT, label='role "Owner"', ref="/a/1"
)
VIA_GROUP = DerivationStep(
    kind=DerivationKind.GROUP_MEMBERSHIP,
    label='group "All Staff" → group "Engineering" → group "Ops" (nested)',
    ref="/g/1",
)
ROLE = DerivationStep(
    kind=DerivationKind.ROLE_ASSIGNMENT, label='role "Owner"', ref="/a/2"
)
PIM = DerivationStep(
    kind=DerivationKind.PIM_ELIGIBLE, label='role "UAA" (eligible)', ref="/a/3"
)


def permission(
    action: str = "Microsoft.Authorization/roleAssignments/write",
    *,
    kind: ActionKind = ActionKind.CONTROL_PLANE,
    state: PermissionState = PermissionState.ACTIVE,
    scope: str = SUB,
    derivation: tuple[DerivationStep, ...] = (DIRECT,),
) -> EffectivePermission:
    return EffectivePermission(
        action=action,
        action_kind=kind,
        state=state,
        scope=scope,
        derivation=derivation,
    )


def result_of(
    *permissions: EffectivePermission, warnings: tuple = ()
) -> ResolutionResult:
    return ResolutionResult(
        identity=IDENTITY,
        subscription="00000000-1111-2222-3333-444444444444",
        permissions=permissions,
        warnings=warnings,
    )


def render_to(result: ResolutionResult, width: int = 80, **kwargs: object) -> str:
    console = Console(file=StringIO(), width=width, force_terminal=False, no_color=True)
    render_list(result, console, **kwargs)  # type: ignore[arg-type]
    assert isinstance(console.file, StringIO)
    return console.file.getvalue()


class TestNothingIsTruncated:
    def test_a_long_action_survives_whole(self) -> None:
        """The point of dropping the chain is that what remains fits."""
        action = "Microsoft.KeyVault/vaults/secrets/getSecret/action"
        assert action in render_to(result_of(permission(action)))

    def test_no_ellipsis_anywhere(self) -> None:
        text = render_to(
            result_of(
                permission(scope=LONG_SCOPE, derivation=(VIA_GROUP, ROLE)),
                permission("Microsoft.Storage/storageAccounts/delete"),
            )
        )
        assert "…" not in text
        assert "..." not in text

    def test_it_fits_a_narrow_terminal(self) -> None:
        text = render_to(result_of(permission()), width=80)
        body = [line for line in text.splitlines() if "roleAssignments/write" in line]
        assert body and all(len(line) <= 80 for line in body)


class TestGrouping:
    def test_one_line_per_action_however_many_chains(self) -> None:
        """The chains are exactly what this view is not showing."""
        text = render_to(
            result_of(
                permission(derivation=(DIRECT,)),
                permission(scope=LONG_SCOPE, derivation=(VIA_GROUP, ROLE)),
            )
        )
        assert text.count("Microsoft.Authorization/roleAssignments/write") == 1

    def test_the_count_says_how_many_chains(self) -> None:
        text = render_to(
            result_of(
                permission(derivation=(DIRECT,)),
                permission(scope=LONG_SCOPE, derivation=(VIA_GROUP, ROLE)),
            )
        )
        assert "2 paths" in text

    def test_singular_for_one(self) -> None:
        assert "1 path" in render_to(result_of(permission()))

    def test_active_and_eligible_are_separate_lines(self) -> None:
        """Grouping must never merge "has it" with "could have it"."""
        text = render_to(
            result_of(
                permission(),
                permission(state=PermissionState.PIM_ELIGIBLE, derivation=(PIM,)),
            )
        )
        assert "ACTIVE" in text
        assert "ELIGIBLE" in text
        assert text.count("roleAssignments/write") == 2

    def test_control_and_data_plane_are_separate_lines(self) -> None:
        text = render_to(
            result_of(
                permission("same/action"),
                permission("same/action", kind=ActionKind.DATA_PLANE),
            )
        )
        assert text.count("same/action") == 2
        assert "data plane" in text

    def test_control_plane_carries_no_tag(self) -> None:
        assert "data plane" not in render_to(result_of(permission()))

    def test_an_action_past_the_column_cap_keeps_a_separator(self) -> None:
        """Regression: it ran straight into its count — "…/write2 paths"."""
        long_action = (
            "Microsoft.Authorization/roleEligibilityScheduleRequests"
            "/whenApprovalRequired/write"
        )
        text = render_to(result_of(permission(long_action)), width=200)
        assert f"{long_action}  1 path" in text

    def test_one_long_action_does_not_stretch_the_others(self) -> None:
        """Aligning to the widest would push every other count off the screen."""
        long_action = "A" * 90
        text = render_to(
            result_of(permission(long_action), permission("B/read")), width=200
        )
        # Canonical order sorts by action, so the long one comes first; the
        # line under test is the short one.
        short = next(line for line in text.splitlines() if "B/read" in line)
        assert len(short) < 90


class TestLimit:
    def test_a_short_result_is_not_cut(self) -> None:
        assert "not shown" not in render_to(result_of(permission()))

    def test_a_long_result_is_cut_and_says_so(self) -> None:
        many = [permission(f"Provider/action{i:04d}/read") for i in range(60)]
        text = render_to(result_of(*many), limit=10)
        assert "showing 10 of 60 actions" in text
        assert "50 not shown" in text
        assert "--action" in text

    def test_zero_means_no_limit(self) -> None:
        many = [permission(f"Provider/action{i:04d}/read") for i in range(60)]
        text = render_to(result_of(*many), limit=0)
        assert "not shown" not in text

    def test_the_default_is_larger_than_the_chain_view(self) -> None:
        """One line per action instead of five, so it can afford to show more."""
        assert DEFAULT_LIST_LIMIT > 50


class TestWarningsAndEmpty:
    def test_warnings_come_first(self) -> None:
        text = render_to(
            result_of(
                permission(),
                warnings=(
                    UnsupportedConstruct(
                        kind=UnsupportedConstructKind.DENY_ASSIGNMENT,
                        message="1 deny assignment",
                    ),
                ),
            )
        )
        assert text.index("may be incomplete") < text.index("ACTIVE")

    def test_no_permissions(self) -> None:
        assert "No permissions found" in render_to(result_of())

    def test_no_match_names_the_filter(self) -> None:
        text = render_to(result_of(), action_filter="Microsoft.Foo/*")
        assert "Microsoft.Foo/*" in text


class TestDispatch:
    def test_the_format_reaches_the_renderer(self) -> None:
        console = Console(
            file=StringIO(), width=100, force_terminal=False, no_color=True
        )
        render(result_of(permission()), OutputFormat.LIST, console)
        assert isinstance(console.file, StringIO)
        text = console.file.getvalue()
        # The chain view would have printed the role; this one must not.
        assert "ACTIVE" in text
        assert 'role "Owner"' not in text
