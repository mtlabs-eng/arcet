"""Rendering a resolution result as a table and as JSON.

Nothing here talks to Azure. Both renderers take a `ResolutionResult` that is
already in canonical order, so neither sorts and neither can disagree with the
other about what came first.

Two properties are load-bearing in both formats:

* Active and PIM-eligible are separated structurally, not by a glyph. Someone
  skimming, or reading without colour, still cannot confuse "has access" with
  "can have access in five minutes".
* A result carrying warnings never renders as though it were complete. In the
  table the warnings come first, because a reader who pipes through `head`
  must still see them.
"""

from __future__ import annotations

import json
import textwrap
from enum import StrEnum
from typing import Any

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from arcet.model import (
    ActionKind,
    EffectivePermission,
    PermissionState,
    ResolutionResult,
)

__all__ = [
    "JSON_SCHEMA_VERSION",
    "OutputFormat",
    "render",
    "render_json",
    "render_table",
    "result_to_dict",
]


class OutputFormat(StrEnum):
    """How to render a resolution result. Lives here, next to the renderers."""

    TABLE = "table"
    JSON = "json"


#: Bumped only when the JSON shape changes in a way that breaks a consumer.
#: Anyone piping `--format json` into jq is depending on this.
JSON_SCHEMA_VERSION = 1

_SECTION_TITLES = {
    PermissionState.ACTIVE: "ACTIVE",
    PermissionState.PIM_ELIGIBLE: "ELIGIBLE VIA PIM",
}
_SECTION_SUBTITLES = {
    PermissionState.ACTIVE: None,
    PermissionState.PIM_ELIGIBLE: "not held now; can be activated",
}
_SECTION_STYLES = {
    PermissionState.ACTIVE: "green",
    PermissionState.PIM_ELIGIBLE: "yellow",
}

# Sections always render in this order, including when one of them is empty.
# "nothing active, three things one activation away" is an answer worth
# stating outright rather than leaving the reader to infer from a gap.
_SECTION_ORDER = (PermissionState.ACTIVE, PermissionState.PIM_ELIGIBLE)

#: Continuation indent for wrapped warning text, aligned under the bullet.
_WARNING_CONTINUATION = "     "
#: Floor for the wrap width, so a very narrow terminal degrades rather than
#: producing one character per line.
_MIN_WRAP_WIDTH = 20


def result_to_dict(result: ResolutionResult) -> dict[str, Any]:
    """Convert a result into plain JSON-serialisable data.

    Enum values go out as their string form, which is contract: those strings
    are what a consumer matches on.
    """
    return {
        "schema": JSON_SCHEMA_VERSION,
        "identity": {
            "object_id": result.identity.object_id,
            "display_name": result.identity.display_name,
            "kind": result.identity.kind.value,
        },
        "subscription": result.subscription,
        # Named `complete` rather than mirroring `is_complete`, so a consumer
        # reading only this field learns that the answer may be partial.
        "complete": result.is_complete,
        "permissions": [
            {
                "action": permission.action,
                "action_kind": permission.action_kind.value,
                "state": permission.state.value,
                "scope": permission.scope,
                "derivation": [
                    {"kind": step.kind.value, "label": step.label, "ref": step.ref}
                    for step in permission.derivation
                ],
            }
            for permission in result.permissions
        ],
        "warnings": [
            {
                "kind": warning.kind.value,
                "message": warning.message,
                "ref": warning.ref,
            }
            for warning in result.warnings
        ],
    }


def render_json(result: ResolutionResult, *, indent: int | None = 2) -> str:
    """Render a result as JSON.

    Keys keep insertion order rather than being sorted, so the shape stays the
    one documented above. The content order is already canonical.
    """
    return json.dumps(result_to_dict(result), indent=indent, ensure_ascii=False)


def render_table(result: ResolutionResult, console: Console | None = None) -> None:
    """Render a result for a human, to `console` or to stdout.

    Rich handles colour detection: piped output and NO_COLOR both come out
    plain, so redirecting to a file gives stable text.
    """
    console = console or Console()

    if result.warnings:
        _print_warnings(result, console)

    _print_header(result, console)

    if not result.permissions:
        console.print()
        console.print(
            Text("No permissions found for this identity in this subscription."),
        )
        return

    for state in _SECTION_ORDER:
        _print_section(result, state, console)


def _print_warnings(result: ResolutionResult, console: Console) -> None:
    """Announce, before anything else, that the answer may be partial."""
    count = len(result.warnings)
    noun = "construction" if count == 1 else "constructions"
    console.print(
        Text.assemble(
            ("⚠  ", "bold yellow"),
            (
                f"result may be incomplete — {count} {noun} detected "
                f"and not interpreted",
                "bold yellow",
            ),
        )
    )
    # Wrapped by hand rather than with rich.Padding, which pads every line out
    # to the full width and leaves trailing spaces in redirected output.
    body_width = max(_MIN_WRAP_WIDTH, console.width - len(_WARNING_CONTINUATION))
    for warning in result.warnings:
        for line in textwrap.wrap(
            warning.message,
            width=body_width,
            initial_indent="   • ",
            subsequent_indent=_WARNING_CONTINUATION,
        ):
            console.print(Text(line))
        if warning.ref:
            # On its own line: Azure scope ids are long enough that appending
            # them wraps the message, and a warning that wraps badly is a
            # warning people learn to skip.
            console.print(Text(_WARNING_CONTINUATION + warning.ref, style="dim"))
    console.print()


def _print_header(result: ResolutionResult, console: Console) -> None:
    total = len(result.permissions)
    noun = "permission" if total == 1 else "permissions"
    console.print(
        Text.assemble(
            (result.identity.display_name, "bold"),
            ("  ·  ", "dim"),
            (f"subscription {result.subscription}", ""),
            ("  ·  ", "dim"),
            (f"{total} {noun}", "dim"),
        )
    )


def _print_section(
    result: ResolutionResult, state: PermissionState, console: Console
) -> None:
    permissions = [p for p in result.permissions if p.state is state]
    count = len(permissions)
    noun = "permission" if count == 1 else "permissions"
    style = _SECTION_STYLES[state]

    console.print()
    console.print(
        Rule(
            Text(f"{_SECTION_TITLES[state]} — {count} {noun}", style=f"bold {style}"),
            align="left",
            style=style,
        )
    )
    if not permissions:
        # No subtitle here: "not held now; can be activated" above an empty
        # section reads as though something were about to be listed.
        console.print(Text("none", style="dim"))
        return

    subtitle = _SECTION_SUBTITLES[state]
    if subtitle:
        console.print(Text(subtitle, style="dim"))

    for permission in permissions:
        console.print()
        _print_permission(permission, console)


def _print_permission(permission: EffectivePermission, console: Console) -> None:
    """Print one action and the chain that explains it.

    Only data plane actions carry a marker. Control plane is the ordinary case,
    and reading a secret's *value* is the one worth making impossible to miss;
    the JSON output always states `action_kind` outright either way.
    """
    heading = Text(permission.action, style="bold")
    if permission.action_kind is ActionKind.DATA_PLANE:
        heading.append("  · data plane", style="dim italic")
    console.print(heading)

    indent = 2
    for step in permission.derivation:
        # Text, never markup: labels and refs carry quotes and brackets that
        # Rich would otherwise try to interpret as styling.
        console.print(Text(" " * indent + "└─ ").append(step.label))
        indent += 3
    console.print(Text(" " * indent + f"@ {permission.scope}", style="dim"))


def render(
    result: ResolutionResult,
    output_format: OutputFormat,
    console: Console | None = None,
) -> None:
    """Render in the format asked for by --format."""
    if output_format is OutputFormat.JSON:
        # soft_wrap is what makes this valid JSON. Without it Rich wraps long
        # lines to the terminal width, and a newline inserted inside a string
        # is an unescaped control character: `arcet --format json | jq` fails
        # on any scope id longer than the window. Found by running it, not by
        # a test — the tests used a console wide enough to hide it.
        (console or Console()).print(
            render_json(result), markup=False, highlight=False, soft_wrap=True
        )
        return
    render_table(result, console)
