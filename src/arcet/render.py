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
import re
import textwrap
from enum import StrEnum
from typing import Any

from rich import box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from arcet.model import (
    ActionKind,
    DerivationKind,
    EffectivePermission,
    PermissionState,
    ResolutionResult,
)

__all__ = [
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_TABLE_LIMIT",
    "JSON_SCHEMA_VERSION",
    "OutputFormat",
    "render",
    "render_grid",
    "render_json",
    "render_list",
    "render_table",
    "result_to_dict",
]


class OutputFormat(StrEnum):
    """How to render a resolution result. Lives here, next to the renderers."""

    #: The chain, indented. Answers "why", one permission at a time.
    TABLE = "table"
    #: One line per action. Answers "what", for scanning a lot at once.
    LIST = "list"
    #: A column per field, in the shape people expect from `az ... -o table`.
    GRID = "grid"
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

#: How many permissions each table section prints before cutting and saying so.
#: Chosen to fit a screen: an identity with Owner resolves to tens of thousands
#: of actions, and the table is for reading, not for exporting. JSON is never
#: truncated.
DEFAULT_TABLE_LIMIT = 50

#: The list view spends one line per action instead of four or five, so it can
#: afford to show more before cutting.
DEFAULT_LIST_LIMIT = 200

#: Shown against a data plane action in the list view. Reading a secret's value
#: is not the same grant as reading its properties, and the list is where that
#: distinction is easiest to lose.
_DATA_PLANE_TAG = "data plane"

#: How far the action column is padded before alignment is given up. Long
#: enough for the great majority of Azure actions, short enough that a rare
#: 80-character one does not reformat everything around it.
_ACTION_COLUMN_CAP = 58

#: Chain steps that name the role carrying a grant.
_ROLE_STEPS = (
    DerivationKind.ROLE_ASSIGNMENT,
    DerivationKind.DIRECT_ASSIGNMENT,
    DerivationKind.PIM_ELIGIBLE,
)

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


def render_table(
    result: ResolutionResult,
    console: Console | None = None,
    *,
    limit: int = DEFAULT_TABLE_LIMIT,
    action_filter: str | None = None,
) -> None:
    """Render a result for a human, to `console` or to stdout.

    Rich handles colour detection: piped output and NO_COLOR both come out
    plain, so redirecting to a file gives stable text.

    Long results are cut at `limit` per section and say so. An identity with
    Owner expands to tens of thousands of actions, and printing all of them is
    not an answer anyone reads — but truncating without saying so would make a
    partial list look like the whole one, so the count that was left out is
    always stated.
    """
    console = console or Console()

    if result.warnings:
        _print_warnings(result, console)

    _print_header(result, console)

    if not result.permissions:
        console.print()
        message = (
            f"No permission matching {action_filter!r} for this identity in this "
            f"subscription."
            if action_filter
            else "No permissions found for this identity in this subscription."
        )
        console.print(Text(message))
        return

    for state in _SECTION_ORDER:
        _print_section(result, state, console, limit=limit)


def _print_warnings(result: ResolutionResult, console: Console) -> None:
    """Announce, before anything else, that the answer may be partial."""
    count = len(result.warnings)
    noun = "construction" if count == 1 else "constructions"

    # Wrapped by hand rather than with rich.Padding, which pads every line out
    # to the full width and leaves trailing spaces in redirected output.
    body_width = max(_MIN_WRAP_WIDTH, console.width - len(_WARNING_CONTINUATION))

    # The headline wraps like the bullets do. Left to Rich it folded back to
    # column zero on a narrow terminal, putting "interpreted" alone against the
    # left margin — the same defect already fixed for the bullets, missed here.
    headline = f"result may be incomplete — {count} {noun} detected and not interpreted"
    for index, line in enumerate(
        textwrap.wrap(
            headline,
            width=body_width,
            initial_indent="⚠  ",
            subsequent_indent="   ",
        )
    ):
        console.print(Text(line, style="bold yellow"), soft_wrap=index > 0)
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
        ),
        # A subscription id plus a UPN already runs past 80 columns; folding it
        # puts "permissions" alone on its own line and reads like a mistake.
        soft_wrap=True,
    )


def _print_section(
    result: ResolutionResult,
    state: PermissionState,
    console: Console,
    *,
    limit: int = DEFAULT_TABLE_LIMIT,
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

    shown = permissions if limit <= 0 else permissions[:limit]
    hidden = count - len(shown)
    if hidden:
        # Stated up front, in the same colour as a warning. A truncation the
        # reader discovers only by counting is a truncation that misled them.
        console.print(
            Text.assemble(
                (f"showing {len(shown)} of {count}. ", "bold yellow"),
                (
                    f"{hidden} not shown — narrow with --action, "
                    f"or use --format json for all of them",
                    "yellow",
                ),
            )
        )

    for permission in shown:
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
        #
        # soft_wrap keeps each step on one logical line. Resource ids are long
        # and unbreakable, and letting Rich fold them restarts the text at
        # column zero, which destroys the indentation the chain is read by.
        console.print(Text(" " * indent + "└─ ").append(step.label), soft_wrap=True)
        indent += 3
    console.print(
        Text(" " * indent + f"@ {permission.scope}", style="dim"), soft_wrap=True
    )


def render_list(
    result: ResolutionResult,
    console: Console | None = None,
    *,
    limit: int = DEFAULT_LIST_LIMIT,
    action_filter: str | None = None,
) -> None:
    """Render one line per action, for scanning rather than for explaining.

    A grid with a column per field was the obvious alternative and does not
    survive real data: an action name, a scope and a nested group path add up
    to roughly 230 characters, so every column ends up elided even at 200
    columns wide. A truncated scope is one nobody can paste or act on.

    This drops the chain instead of shrinking it. You see what the identity can
    do; `--action` then shows why, in full, with nothing cut.
    """
    console = console or Console()

    if result.warnings:
        _print_warnings(result, console)
    _print_header(result, console)

    if not result.permissions:
        console.print()
        console.print(Text(_empty_message(action_filter)))
        return

    # Same action reached by several chains is one line with a count, not one
    # line per chain: the chains are exactly what this view is not showing.
    grouped: dict[tuple[str, ActionKind, PermissionState], int] = {}
    for permission in result.permissions:
        key = (permission.action, permission.action_kind, permission.state)
        grouped[key] = grouped.get(key, 0) + 1

    entries = list(grouped.items())
    shown = entries if limit <= 0 else entries[:limit]
    hidden = len(entries) - len(shown)

    console.print()
    if hidden:
        console.print(
            Text.assemble(
                (f"showing {len(shown)} of {len(entries)} actions. ", "bold yellow"),
                (
                    f"{hidden} not shown — narrow with --action, "
                    f"or use --format json for all of them",
                    "yellow",
                ),
            )
        )
        console.print()

    # Padding to the widest action would let one outlier stretch every row:
    # Microsoft.Authorization/roleEligibilityScheduleRequests/whenApprovalRequired/write
    # is 82 characters, and aligning to it pushes the count off the screen for
    # the other 199 lines. Rows past the cap simply lose their alignment, which
    # costs one row rather than all of them.
    width = min(
        max(len(action) for action, _, _ in (k for k, _ in shown)),
        _ACTION_COLUMN_CAP,
    )
    for (action, action_kind, state), paths in shown:
        line = Text()
        line.append(
            f"{_SECTION_TITLES[state].split()[0]:<9}", style=_SECTION_STYLES[state]
        )
        line.append(action)
        # Always at least two spaces: an action past the cap would otherwise
        # run straight into its own count — "…/write2 paths".
        line.append(" " * max(2, width + 2 - len(action)))
        if action_kind is ActionKind.DATA_PLANE:
            line.append(f"{_DATA_PLANE_TAG}  ", style="dim italic")
        noun = "path" if paths == 1 else "paths"
        line.append(f"{paths} {noun}", style="dim")
        console.print(line, soft_wrap=True)


def _unquote(noun: str, label: str) -> str:
    """Turn `group "Platform" → group "Ops"` into `Platform → Ops`.

    Written with a substitution rather than str.replace because the read-only
    guard in tests/test_readonly.py rejects any call named `replace`. That is a
    false positive, and the right response is to write around it: the guard
    earns its keep by being blunt, and carving an exception for rendering code
    is how a check like that stops meaning anything.
    """
    return re.sub(rf'{noun} "([^"]*)"', r"\1", label)


def _via(permission: EffectivePermission) -> str:
    """How the grant reaches the subject, in one cell.

    Group paths keep their arrows; the surrounding `group "…"` wrapper is
    dropped because the column heading already says what these are.
    """
    for step in permission.derivation:
        if step.kind is DerivationKind.GROUP_MEMBERSHIP:
            return _unquote("group", step.label)
    if permission.state is PermissionState.PIM_ELIGIBLE:
        return "PIM"
    return "Direct"


def _role(permission: EffectivePermission) -> str:
    """The role that carries the grant, without the `role "…"` wrapper."""
    for step in reversed(permission.derivation):
        if step.kind in _ROLE_STEPS:
            return _unquote("role", step.label)
    return ""


def render_grid(
    result: ResolutionResult,
    console: Console | None = None,
    *,
    limit: int = DEFAULT_TABLE_LIMIT,
    action_filter: str | None = None,
) -> None:
    """Render a column per field, in the shape `az ... -o table` produces.

    Cells wrap rather than truncate. A scope is 120 characters and there is no
    terminal wide enough to hold one beside an action name and a nested group
    path, so something has to give: either the row gets tall, or the scope
    stops being something anyone can paste. It gets tall.

    That makes this the least compact of the three views, which is worth
    knowing before choosing it. `--format list` is the dense one.
    """
    console = console or Console()

    if result.warnings:
        _print_warnings(result, console)

    # Labelled header rather than the inline one: with a boxed grid below it,
    # aligned labels read as part of the same object.
    console.print(
        Text.assemble(
            ("Principal:    ", "dim"), (result.identity.display_name, "bold")
        ),
        soft_wrap=True,
    )
    console.print(
        Text.assemble(("Subscription: ", "dim"), (result.subscription, "")),
        soft_wrap=True,
    )
    console.print(
        Text.assemble(("Permissions:  ", "dim"), (str(len(result.permissions)), ""))
    )

    if not result.permissions:
        console.print()
        console.print(Text(_empty_message(action_filter)))
        return

    shown = result.permissions if limit <= 0 else result.permissions[:limit]
    hidden = len(result.permissions) - len(shown)

    console.print()
    if hidden:
        console.print(
            Text.assemble(
                (f"showing {len(shown)} of {len(result.permissions)}. ", "bold yellow"),
                (
                    f"{hidden} not shown — narrow with --action, "
                    f"or use --format json for all of them",
                    "yellow",
                ),
            )
        )

    grid = Table(box=box.ASCII, show_lines=True, pad_edge=False)
    grid.add_column("STATUS", overflow="fold", style="")
    for heading in ("PERMISSION", "VIA", "ROLE", "SCOPE"):
        grid.add_column(heading, overflow="fold")

    for permission in shown:
        status = _SECTION_TITLES[permission.state].split()[0]
        action = permission.action
        if permission.action_kind is ActionKind.DATA_PLANE:
            action = f"{action}\n({_DATA_PLANE_TAG})"
        grid.add_row(
            Text(status, style=_SECTION_STYLES[permission.state]),
            action,
            _via(permission),
            _role(permission),
            permission.scope,
        )
    console.print(grid)


def _empty_message(action_filter: str | None) -> str:
    return (
        f"No permission matching {action_filter!r} for this identity in this "
        f"subscription."
        if action_filter
        else "No permissions found for this identity in this subscription."
    )


def render(
    result: ResolutionResult,
    output_format: OutputFormat,
    console: Console | None = None,
    *,
    limit: int = DEFAULT_TABLE_LIMIT,
    action_filter: str | None = None,
) -> None:
    """Render in the format asked for by --format.

    Only the table is ever cut. JSON is what a pipeline consumes, and a
    truncated machine format would be a silent lie to something that cannot
    read the warning line.
    """
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
    if output_format is OutputFormat.LIST:
        render_list(result, console, action_filter=action_filter)
        return
    if output_format is OutputFormat.GRID:
        render_grid(result, console, limit=limit, action_filter=action_filter)
        return
    render_table(result, console, limit=limit, action_filter=action_filter)
