"""Tests for the grid view.

A column per field, in the shape `az ... -o table` produces. Cells wrap rather
than truncate: an Azure scope is around 120 characters and no terminal holds
one beside an action and a nested group path, so either the row gets tall or
the scope stops being something anyone can paste. It gets tall.
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
from arcet.render import OutputFormat, render, render_grid

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
    kind=DerivationKind.DIRECT_ASSIGNMENT, label='role "Contributor"', ref="/a/1"
)
GROUP = DerivationStep(
    kind=DerivationKind.GROUP_MEMBERSHIP,
    label='group "Platform" → group "Ops" (nested)',
    ref="/g/1",
)
ROLE = DerivationStep(
    kind=DerivationKind.ROLE_ASSIGNMENT, label='role "Owner"', ref="/a/2"
)
PIM = DerivationStep(
    kind=DerivationKind.PIM_ELIGIBLE,
    label='role "User Access Administrator" (eligible, not active)',
    ref="/a/3",
)


def permission(
    action: str = "Microsoft.Storage/storageAccounts/delete",
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


def render_to(result: ResolutionResult, width: int = 100, **kwargs: object) -> str:
    console = Console(file=StringIO(), width=width, force_terminal=False, no_color=True)
    render_grid(result, console, **kwargs)  # type: ignore[arg-type]
    assert isinstance(console.file, StringIO)
    return console.file.getvalue()


class TestColumns:
    def test_every_heading_is_present(self) -> None:
        text = render_to(result_of(permission()))
        for heading in ("STATUS", "PERMISSION", "VIA", "ROLE", "SCOPE"):
            assert heading in text

    def test_a_direct_assignment_says_direct(self) -> None:
        assert "Direct" in render_to(result_of(permission()))

    def test_a_group_path_fills_the_via_column(self) -> None:
        text = render_to(result_of(permission(derivation=(GROUP, ROLE))), width=140)
        # The `group "…"` wrapper is dropped; the heading already says what it is.
        assert "Platform → Ops (nested)" in text
        assert 'group "Platform"' not in text

    def test_an_eligibility_says_pim(self) -> None:
        text = render_to(
            result_of(permission(state=PermissionState.PIM_ELIGIBLE, derivation=(PIM,)))
        )
        assert "PIM" in text
        assert "ELIGIBLE" in text

    def test_the_role_column_loses_its_quotes(self) -> None:
        text = render_to(result_of(permission(derivation=(GROUP, ROLE))), width=140)
        assert "Owner" in text
        assert 'role "Owner"' not in text

    def test_data_plane_is_marked(self) -> None:
        """Reading a secret's value is not the same grant as reading its name."""
        text = render_to(
            result_of(
                permission(
                    "Microsoft.KeyVault/vaults/secrets/getSecret/action",
                    kind=ActionKind.DATA_PLANE,
                )
            )
        )
        assert "data plane" in text

    def test_control_plane_is_not_marked(self) -> None:
        assert "data plane" not in render_to(result_of(permission()))


class TestNothingIsTruncated:
    def test_a_long_scope_survives_in_full(self) -> None:
        """Wrapped across cells, but every character is still there."""
        text = render_to(result_of(permission(scope=LONG_SCOPE)))
        joined = "".join(
            part.strip() for line in text.splitlines() for part in line.split("|")
        )
        assert "storageAccounts/stplatformprod001" in joined
        assert "rg-platform-prod" in joined

    def test_no_ellipsis(self) -> None:
        assert "…" not in render_to(result_of(permission(scope=LONG_SCOPE)))


class TestHeaderAndLimit:
    def test_the_header_is_labelled(self) -> None:
        text = render_to(result_of(permission()))
        assert "Principal:" in text
        assert "Subscription:" in text
        assert "Permissions:" in text

    def test_a_long_result_is_cut_and_says_so(self) -> None:
        many = [permission(f"Provider/action{i:04d}/read") for i in range(60)]
        text = render_to(result_of(*many), limit=10)
        assert "showing 10 of 60" in text
        assert "50 not shown" in text

    def test_zero_means_no_limit(self) -> None:
        many = [permission(f"Provider/action{i:04d}/read") for i in range(60)]
        assert "not shown" not in render_to(result_of(*many), limit=0)

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
        assert text.index("may be incomplete") < text.index("Principal:")

    def test_no_permissions(self) -> None:
        assert "No permissions found" in render_to(result_of())

    def test_no_match_names_the_filter(self) -> None:
        text = render_to(result_of(), action_filter="Microsoft.Foo/*")
        assert "Microsoft.Foo/*" in text


class TestDispatch:
    def test_the_format_reaches_the_renderer(self) -> None:
        console = Console(
            file=StringIO(), width=120, force_terminal=False, no_color=True
        )
        render(result_of(permission()), OutputFormat.GRID, console)
        assert isinstance(console.file, StringIO)
        assert "PERMISSION" in console.file.getvalue()
