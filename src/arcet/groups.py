"""Walking group membership, and keeping the path while doing it.

Graph will resolve nesting server-side through transitiveMemberOf, but it
answers with a flat set. A flat set cannot say *why* an identity is in a group,
and the why is the product. So membership is walked one level at a time and the
path is carried along.

The walk is then checked against the transitive set. Anything Graph can reach
that the walk did not is a gap, and a gap that nobody is told about is the
failure this tool exists to avoid.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "GroupPath",
    "GroupRef",
    "Membership",
    "walk_membership",
]

#: How deep nesting is followed before giving up and saying so. Real
#: directories are rarely deeper than a handful; a larger number here usually
#: means a cycle the visited set already caught, or a pathological tenant.
DEFAULT_MAX_DEPTH = 20


@dataclass(frozen=True, slots=True)
class GroupRef:
    """A group, as little of it as the chain needs."""

    object_id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class GroupPath:
    """How the subject reaches one group, nearest hop first."""

    groups: tuple[GroupRef, ...]

    @property
    def target(self) -> GroupRef:
        """The group this path arrives at."""
        return self.groups[-1]

    @property
    def is_nested(self) -> bool:
        return len(self.groups) > 1

    def label(self) -> str:
        """The chain step as a human reads it.

        Rendered as one step rather than one per hop, so that a six-deep
        nesting does not push the role that actually grants the permission six
        levels off the left margin.
        """
        joined = " → ".join(f'group "{group.display_name}"' for group in self.groups)
        return f"{joined} (nested)" if self.is_nested else joined


@dataclass(frozen=True, slots=True)
class Membership:
    """Every group the subject belongs to, and how it got there."""

    paths: tuple[GroupPath, ...]
    #: Groups reached by the walk, by object id.
    reached: frozenset[str]
    #: Anything the walk could not finish, in plain language.
    notes: tuple[str, ...] = ()

    def path_for(self, object_id: str) -> GroupPath | None:
        for path in self.paths:
            if path.target.object_id == object_id:
                return path
        return None


def walk_membership(
    root_id: str,
    parents_of: Callable[[str], Iterable[GroupRef]],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Membership:
    """Walk from the subject outwards, recording the path to each group.

    Breadth-first, so the first path found to a group is the shortest one. A
    group reachable by two routes is reported once, by the shorter: both are
    true, and the shorter is the one a reader can act on.

    Cycles are ordinary in directories — two groups can contain each other —
    so a visited set is what makes this terminate rather than an assumption
    that nobody has done that.
    """
    paths: list[GroupPath] = []
    visited: set[str] = {root_id}
    notes: list[str] = []
    truncated = False

    queue: deque[tuple[str, tuple[GroupRef, ...]]] = deque([(root_id, ())])
    while queue:
        current_id, prefix = queue.popleft()
        if len(prefix) >= max_depth:
            truncated = True
            continue
        for parent in parents_of(current_id):
            if parent.object_id in visited:
                continue
            visited.add(parent.object_id)
            path = (*prefix, parent)
            paths.append(GroupPath(groups=path))
            queue.append((parent.object_id, path))

    if truncated:
        notes.append(
            f"group nesting was followed to {max_depth} levels and stopped there"
        )

    return Membership(
        paths=tuple(paths),
        reached=frozenset(path.target.object_id for path in paths),
        notes=tuple(notes),
    )


def unreached(membership: Membership, transitive_ids: Iterable[str]) -> frozenset[str]:
    """Groups Graph can reach transitively that the walk did not.

    Non-empty means the walk is short of something — a branch we lacked
    permission to read, or a page we did not follow. The caller turns it into a
    warning rather than into a quietly smaller answer.
    """
    return frozenset(transitive_ids) - membership.reached
