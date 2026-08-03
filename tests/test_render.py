"""Tests for the table and JSON renderers.

Fed entirely by in-memory results. The chain has to read well before any Azure
code exists, so this is where that is checked.
"""

from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

from arcet.model import (
    ActionKind,
    DerivationKind,
    DerivationStep,
    EffectivePermission,
    PermissionState,
    ResolutionResult,
    UnsupportedConstruct,
    UnsupportedConstructKind,
)
from arcet.render import (
    JSON_SCHEMA_VERSION,
    OutputFormat,
    render,
    render_json,
    render_table,
    result_to_dict,
)
from conftest import (
    ACTIVE_PERMISSION,
    DATA_PLANE_PERMISSION,
    ELIGIBLE_PERMISSION,
    SUBSCRIPTION,
    USER,
    output_of,
)


class TestTableWarnings:
    """Silence is the one failure this tool cannot afford."""

    def test_warnings_come_before_everything_else(
        self, incomplete_result: ResolutionResult, console: Console
    ) -> None:
        """A reader piping through `head` must still see them."""
        render_table(incomplete_result, console)
        text = output_of(console)
        assert text.index("may be incomplete") < text.index(USER.display_name)

    def test_every_warning_message_is_shown(
        self, incomplete_result: ResolutionResult, console: Console
    ) -> None:
        render_table(incomplete_result, console)
        text = output_of(console)
        for warning in incomplete_result.warnings:
            assert warning.message in text

    def test_warning_refs_are_shown(
        self, incomplete_result: ResolutionResult, console: Console
    ) -> None:
        render_table(incomplete_result, console)
        assert incomplete_result.warnings[0].ref in output_of(console)

    def test_the_count_is_stated(
        self, incomplete_result: ResolutionResult, console: Console
    ) -> None:
        render_table(incomplete_result, console)
        assert "2 constructions" in output_of(console)

    def test_singular_for_one_warning(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        result = ResolutionResult(
            identity=active_only_result.identity,
            subscription=active_only_result.subscription,
            permissions=active_only_result.permissions,
            warnings=(
                UnsupportedConstruct(
                    kind=UnsupportedConstructKind.ABAC_CONDITION,
                    message="one condition",
                ),
            ),
        )
        render_table(result, console)
        assert "1 construction detected" in output_of(console)

    def test_a_complete_result_says_nothing_about_completeness(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        """No banner when there is nothing to warn about."""
        render_table(active_only_result, console)
        assert "incomplete" not in output_of(console)


class TestTableSections:
    def test_both_sections_render_even_when_one_is_empty(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        """'Nothing active' and 'nothing eligible' are answers, not gaps."""
        render_table(active_only_result, console)
        text = output_of(console)
        assert "ACTIVE" in text
        assert "ELIGIBLE VIA PIM" in text

    def test_active_comes_before_eligible(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render_table(mixed_result, console)
        text = output_of(console)
        assert text.index("ACTIVE") < text.index("ELIGIBLE VIA PIM")

    def test_an_empty_section_says_none(
        self, eligible_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(eligible_only_result, console)
        text = output_of(console)
        active_block = text[text.index("ACTIVE") : text.index("ELIGIBLE VIA PIM")]
        assert "none" in active_block

    def test_an_empty_section_carries_no_subtitle(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        """A subtitle above nothing reads as though a list were coming."""
        render_table(active_only_result, console)
        text = output_of(console)
        eligible_block = text[text.index("ELIGIBLE VIA PIM") :]
        assert "can be activated" not in eligible_block

    def test_eligible_section_explains_itself(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        """The distinction that matters most is spelled out, not just coloured."""
        render_table(mixed_result, console)
        assert "not held now; can be activated" in output_of(console)

    def test_section_counts(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render_table(mixed_result, console)
        text = output_of(console)
        assert "ACTIVE — 2 permissions" in text
        assert "ELIGIBLE VIA PIM — 1 permission" in text

    def test_permissions_land_in_the_right_section(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render_table(mixed_result, console)
        text = output_of(console)
        boundary = text.index("ELIGIBLE VIA PIM")
        assert text.index(ACTIVE_PERMISSION.action) < boundary
        assert text.index(ELIGIBLE_PERMISSION.action) > boundary


class TestTableChain:
    def test_every_step_is_shown(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(active_only_result, console)
        text = output_of(console)
        for step in ACTIVE_PERMISSION.derivation:
            assert step.label in text

    def test_steps_keep_their_order(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(active_only_result, console)
        text = output_of(console)
        first, second = ACTIVE_PERMISSION.derivation
        assert text.index(first.label) < text.index(second.label)

    def test_each_step_is_indented_deeper(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(active_only_result, console)
        lines = output_of(console).splitlines()
        indents = [
            len(line) - len(line.lstrip())
            for line in lines
            if line.strip().startswith("└─")
        ]
        assert indents == sorted(indents)
        assert len(set(indents)) == len(indents)

    def test_the_scope_closes_the_chain(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(active_only_result, console)
        assert f"@ {ACTIVE_PERMISSION.scope}" in output_of(console)

    def test_data_plane_actions_are_marked(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        """Reading a secret's value is not the same as reading its properties."""
        render_table(mixed_result, console)
        text = output_of(console)
        marked = next(
            line for line in text.splitlines() if DATA_PLANE_PERMISSION.action in line
        )
        assert "data plane" in marked

    def test_control_plane_actions_are_not_marked(
        self, active_only_result: ResolutionResult, console: Console
    ) -> None:
        render_table(active_only_result, console)
        assert "data plane" not in output_of(console)


class TestTableEdges:
    def test_no_permissions_is_stated_outright(
        self, empty_result: ResolutionResult, console: Console
    ) -> None:
        render_table(empty_result, console)
        assert "No permissions found" in output_of(console)

    def test_the_header_names_identity_and_subscription(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render_table(mixed_result, console)
        text = output_of(console)
        assert USER.display_name in text
        assert SUBSCRIPTION in text

    def test_no_trailing_whitespace(
        self, incomplete_result: ResolutionResult, console: Console
    ) -> None:
        """Redirected output should be clean enough to diff between runs."""
        render_table(incomplete_result, console)
        lines = output_of(console).splitlines()
        assert [line for line in lines if line != line.rstrip()] == []

    def test_long_warnings_wrap_under_the_bullet(self, console: Console) -> None:
        """A warning that wraps to column zero is one people learn to skip."""
        result = ResolutionResult(
            identity=USER,
            subscription=SUBSCRIPTION,
            warnings=(
                UnsupportedConstruct(
                    kind=UnsupportedConstructKind.ABAC_CONDITION,
                    message=" ".join(["a condition that is very wordy indeed"] * 6),
                ),
            ),
        )
        render_table(result, console)
        wrapped = [
            line
            for line in output_of(console).splitlines()
            if line.startswith("     ") and "condition" in line
        ]
        assert wrapped, "expected the message to wrap under the bullet"

    def test_no_ansi_escapes_when_colour_is_off(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        """Redirecting to a file has to give stable, greppable text."""
        render_table(mixed_result, console)
        assert "\x1b[" not in output_of(console)

    def test_markup_in_labels_is_not_interpreted(self, console: Console) -> None:
        """Azure ids carry brackets; Rich must not read them as styling."""
        label = "role [bold]not styling[/bold]"
        result = ResolutionResult(
            identity=USER,
            subscription=SUBSCRIPTION,
            permissions=(
                EffectivePermission(
                    action="Some/action",
                    action_kind=ActionKind.CONTROL_PLANE,
                    state=PermissionState.ACTIVE,
                    scope="/subscriptions/x",
                    derivation=(
                        DerivationStep(
                            kind=DerivationKind.ROLE_ASSIGNMENT, label=label, ref="/x"
                        ),
                    ),
                ),
            ),
        )
        render_table(result, console)
        assert label in output_of(console)


class TestJson:
    def test_it_is_valid_json(self, mixed_result: ResolutionResult) -> None:
        json.loads(render_json(mixed_result))

    def test_schema_version_is_declared(self, mixed_result: ResolutionResult) -> None:
        assert json.loads(render_json(mixed_result))["schema"] == JSON_SCHEMA_VERSION

    def test_shape(self, active_only_result: ResolutionResult) -> None:
        """The full document, pinned. This is what jq consumers depend on."""
        assert json.loads(render_json(active_only_result)) == {
            "schema": 1,
            "identity": {
                "object_id": USER.object_id,
                "display_name": USER.display_name,
                "kind": "user",
            },
            "subscription": SUBSCRIPTION,
            "complete": True,
            "permissions": [
                {
                    "action": "Microsoft.KeyVault/vaults/secrets/read",
                    "action_kind": "control_plane",
                    "state": "active",
                    "scope": ACTIVE_PERMISSION.scope,
                    "derivation": [
                        {
                            "kind": "group_membership",
                            "label": 'group "Platform" → group "SRE" (nested)',
                            "ref": "/groups/aaaaaaaa-0000-0000-0000-000000000001",
                        },
                        {
                            "kind": "role_assignment",
                            "label": 'role "Key Vault Secrets User"',
                            "ref": ACTIVE_PERMISSION.scope,
                        },
                    ],
                }
            ],
            "warnings": [],
        }

    def test_complete_is_false_when_warnings_exist(
        self, incomplete_result: ResolutionResult
    ) -> None:
        """A consumer reading one field still learns the answer may be partial."""
        assert json.loads(render_json(incomplete_result))["complete"] is False

    def test_warnings_are_carried(self, incomplete_result: ResolutionResult) -> None:
        warnings = json.loads(render_json(incomplete_result))["warnings"]
        assert len(warnings) == 2
        assert warnings[0]["kind"] == "deny_assignment"
        assert warnings[0]["message"] == incomplete_result.warnings[0].message

    def test_absent_ref_is_null_not_empty(self) -> None:
        result = ResolutionResult(
            identity=USER,
            subscription=SUBSCRIPTION,
            warnings=(
                UnsupportedConstruct(
                    kind=UnsupportedConstructKind.UNRECOGNISED, message="new thing"
                ),
            ),
        )
        assert json.loads(render_json(result))["warnings"][0]["ref"] is None

    def test_permission_order_matches_the_table(
        self, mixed_result: ResolutionResult
    ) -> None:
        """Both formats inherit canonical order, so neither can disagree."""
        actions = [
            p["action"] for p in json.loads(render_json(mixed_result))["permissions"]
        ]
        assert actions == [p.action for p in mixed_result.permissions]

    def test_non_ascii_survives(self, mixed_result: ResolutionResult) -> None:
        """Chain labels use → and Azure display names carry accents."""
        assert "→" in render_json(mixed_result)

    def test_same_input_renders_identically(
        self, mixed_result: ResolutionResult
    ) -> None:
        assert render_json(mixed_result) == render_json(mixed_result)

    def test_compact_form(self, mixed_result: ResolutionResult) -> None:
        assert "\n" not in render_json(mixed_result, indent=None)

    def test_result_to_dict_is_plain_data(self, mixed_result: ResolutionResult) -> None:
        """No enum objects leak through; the string values are the contract."""
        data = result_to_dict(mixed_result)
        assert type(data["permissions"][0]["state"]) is str


class TestDispatch:
    def test_json_format(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render(mixed_result, OutputFormat.JSON, console)
        json.loads(output_of(console))

    def test_json_survives_a_narrow_terminal(
        self, mixed_result: ResolutionResult
    ) -> None:
        """Regression: Rich wrapped long lines and broke the JSON.

        A newline inserted inside a string is an unescaped control character,
        so `arcet --format json | jq` failed on any scope id wider than the
        window. The old tests used a 100-column console, which was wide enough
        to hide it.
        """
        narrow = Console(file=StringIO(), width=20, force_terminal=False, no_color=True)
        render(mixed_result, OutputFormat.JSON, narrow)
        json.loads(output_of(narrow))

    def test_table_format(
        self, mixed_result: ResolutionResult, console: Console
    ) -> None:
        render(mixed_result, OutputFormat.TABLE, console)
        assert "ACTIVE" in output_of(console)
