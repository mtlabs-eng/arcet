"""Tests for the action filter and the table cut-off.

Both exist because a real identity with Owner resolves to tens of thousands of
actions. Neither is allowed to make a partial answer look like a whole one.
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
from arcet.render import DEFAULT_TABLE_LIMIT, render_table
from arcet.resolve import filter_by_action

IDENTITY = IdentityRef(
    object_id="99999999-8888-7777-6666-555555555555",
    display_name="user@empresa.pt",
    kind=IdentityKind.USER,
)
STEP = DerivationStep(
    kind=DerivationKind.DIRECT_ASSIGNMENT, label='role "Owner"', ref="/a/1"
)
WARNING = UnsupportedConstruct(
    kind=UnsupportedConstructKind.DENY_ASSIGNMENT, message="1 deny assignment"
)


def permission(action: str) -> EffectivePermission:
    return EffectivePermission(
        action=action,
        action_kind=ActionKind.CONTROL_PLANE,
        state=PermissionState.ACTIVE,
        scope="/subscriptions/sub-1",
        derivation=(STEP,),
    )


def result_with(*actions: str, warnings: tuple = ()) -> ResolutionResult:
    return ResolutionResult(
        identity=IDENTITY,
        subscription="sub-1",
        permissions=tuple(permission(action) for action in actions),
        warnings=warnings,
    )


def console_of(width: int = 100) -> Console:
    return Console(file=StringIO(), width=width, force_terminal=False, no_color=True)


def text_of(console: Console) -> str:
    assert isinstance(console.file, StringIO)
    return console.file.getvalue()


class TestFilter:
    def test_an_exact_action(self) -> None:
        result = result_with("A/read", "B/read")
        assert [p.action for p in filter_by_action(result, "A/read").permissions] == [
            "A/read"
        ]

    def test_a_wildcard(self) -> None:
        result = result_with(
            "Microsoft.Authorization/roleAssignments/write",
            "Microsoft.Authorization/roleAssignments/read",
            "Microsoft.Storage/storageAccounts/read",
        )
        filtered = filter_by_action(result, "Microsoft.Authorization/*/write")
        assert [p.action for p in filtered.permissions] == [
            "Microsoft.Authorization/roleAssignments/write"
        ]

    def test_matching_nothing_is_a_real_answer(self) -> None:
        """ "No, this identity cannot do that" is the useful negative result."""
        result = result_with("A/read")
        assert filter_by_action(result, "B/*").permissions == ()

    def test_case_insensitive_like_arm(self) -> None:
        result = result_with("Microsoft.Storage/storageAccounts/read")
        assert filter_by_action(result, "microsoft.storage/*").permissions

    def test_the_chain_survives_filtering(self) -> None:
        """The whole point of matching is to then see why."""
        result = result_with("A/read")
        assert filter_by_action(result, "A/*").permissions[0].derivation == (STEP,)

    def test_warnings_are_never_filtered_out(self) -> None:
        """A narrowed answer must not be more confident than the wide one."""
        result = result_with("A/read", warnings=(WARNING,))
        filtered = filter_by_action(result, "B/*")
        assert filtered.warnings == (WARNING,)
        assert not filtered.is_complete

    def test_identity_and_subscription_are_kept(self) -> None:
        filtered = filter_by_action(result_with("A/read"), "A/*")
        assert filtered.identity == IDENTITY
        assert filtered.subscription == "sub-1"


class TestTableLimit:
    def test_a_short_result_is_not_cut(self) -> None:
        console = console_of()
        render_table(result_with("A/read", "B/read"), console)
        assert "not shown" not in text_of(console)

    def test_a_long_result_is_cut_and_says_so(self) -> None:
        console = console_of()
        result = result_with(*[f"Provider/action{i:04d}/read" for i in range(200)])
        render_table(result, console, limit=10)
        text = text_of(console)
        assert "showing 10 of 200" in text
        assert "190 not shown" in text

    def test_the_cut_names_the_way_out(self) -> None:
        """A truncation without a remedy is just a smaller answer."""
        console = console_of()
        render_table(result_with(*[f"A/a{i}" for i in range(60)]), console, limit=5)
        text = text_of(console)
        assert "--action" in text
        assert "--format json" in text

    def test_the_total_is_still_stated(self) -> None:
        console = console_of()
        render_table(result_with(*[f"A/a{i}" for i in range(60)]), console, limit=5)
        assert "ACTIVE — 60 permissions" in text_of(console)

    def test_only_the_limit_is_printed(self) -> None:
        # Zero-padded so that canonical order, which sorts action strings, runs
        # the same way as counting does.
        console = console_of()
        render_table(result_with(*[f"A/a{i:03d}" for i in range(60)]), console, limit=5)
        text = text_of(console)
        assert "A/a004" in text
        assert "A/a005" not in text

    def test_zero_means_no_limit(self) -> None:
        console = console_of()
        render_table(result_with(*[f"A/a{i}" for i in range(60)]), console, limit=0)
        text = text_of(console)
        assert "not shown" not in text
        assert "A/a59" in text

    def test_the_default_limit_is_a_screenful(self) -> None:
        assert 20 <= DEFAULT_TABLE_LIMIT <= 100


class TestFilteredEmptyMessage:
    def test_it_names_the_pattern(self) -> None:
        """Silence here would read as "resolved nothing", not as "no match"."""
        console = console_of()
        render_table(result_with(), console, action_filter="Microsoft.Foo/*")
        assert "Microsoft.Foo/*" in text_of(console)

    def test_without_a_filter_it_stays_generic(self) -> None:
        console = console_of()
        render_table(result_with(), console)
        assert "No permissions found" in text_of(console)
