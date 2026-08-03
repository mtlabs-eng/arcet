"""Tests for the membership walk.

Directories contain cycles, groups reachable two ways, and branches we may not
be allowed to read. All three have to end in something a reader can trust.
"""

from __future__ import annotations

import pytest

from arcet.groups import GroupRef, walk_membership

PLATFORM = GroupRef(object_id="g-platform", display_name="Platform")
SRE = GroupRef(object_id="g-sre", display_name="SRE")
INFRA = GroupRef(object_id="g-infra", display_name="Infra")
LEGACY = GroupRef(object_id="g-legacy", display_name="Legacy")

USER = "u-1"


def graph(edges: dict[str, tuple[GroupRef, ...]]):
    def parents_of(object_id: str) -> tuple[GroupRef, ...]:
        return edges.get(object_id, ())

    return parents_of


class TestWalk:
    def test_no_groups(self) -> None:
        membership = walk_membership(USER, graph({}))
        assert membership.paths == ()
        assert membership.reached == frozenset()

    def test_one_direct_group(self) -> None:
        membership = walk_membership(USER, graph({USER: (PLATFORM,)}))
        assert len(membership.paths) == 1
        assert membership.paths[0].label() == 'group "Platform"'
        assert not membership.paths[0].is_nested

    def test_nested_groups_keep_the_path(self) -> None:
        """The flat set would say Infra; only the path says how we got there."""
        membership = walk_membership(
            USER, graph({USER: (PLATFORM,), "g-platform": (SRE,), "g-sre": (INFRA,)})
        )
        path = membership.path_for("g-infra")
        assert path is not None
        assert path.label() == (
            'group "Platform" → group "SRE" → group "Infra" (nested)'
        )

    def test_every_group_gets_its_own_path(self) -> None:
        membership = walk_membership(
            USER, graph({USER: (PLATFORM,), "g-platform": (SRE,)})
        )
        assert membership.reached == {"g-platform", "g-sre"}

    def test_a_cycle_terminates(self) -> None:
        """Two groups can contain each other. That must not be a hang."""
        membership = walk_membership(
            USER,
            graph({USER: (PLATFORM,), "g-platform": (SRE,), "g-sre": (PLATFORM,)}),
        )
        assert membership.reached == {"g-platform", "g-sre"}

    def test_self_referencing_group(self) -> None:
        membership = walk_membership(
            USER, graph({USER: (PLATFORM,), "g-platform": (PLATFORM,)})
        )
        assert len(membership.paths) == 1

    def test_the_subject_is_never_a_step(self) -> None:
        membership = walk_membership(USER, graph({USER: (PLATFORM,), "g-platform": ()}))
        assert all(
            USER not in [g.object_id for g in p.groups] for p in membership.paths
        )

    def test_a_group_reachable_twice_is_reported_once_by_the_shorter_route(
        self,
    ) -> None:
        """Both routes are true; the shorter is the one a reader can act on."""
        membership = walk_membership(
            USER,
            graph(
                {
                    USER: (PLATFORM, SRE),
                    "g-platform": (SRE,),
                }
            ),
        )
        path = membership.path_for("g-sre")
        assert path is not None
        assert path.groups == (SRE,)
        assert len(membership.paths) == 2

    def test_depth_is_capped_and_said_so(self) -> None:
        chain = {USER: (PLATFORM,), "g-platform": (SRE,), "g-sre": (INFRA,)}
        membership = walk_membership(USER, graph(chain), max_depth=2)
        assert membership.notes
        assert "2 levels" in membership.notes[0]
        assert membership.path_for("g-infra") is None

    def test_no_note_when_the_walk_completes(self) -> None:
        membership = walk_membership(USER, graph({USER: (PLATFORM,)}), max_depth=5)
        assert membership.notes == ()

    def test_path_for_unknown_group(self) -> None:
        membership = walk_membership(USER, graph({USER: (PLATFORM,)}))
        assert membership.path_for("g-nope") is None


class TestCrossCheck:
    def test_nothing_missing(self) -> None:
        from arcet.groups import unreached

        membership = walk_membership(USER, graph({USER: (PLATFORM,)}))
        assert unreached(membership, {"g-platform"}) == frozenset()

    def test_a_group_graph_reaches_but_the_walk_did_not(self) -> None:
        """The whole reason the cross-check exists."""
        from arcet.groups import unreached

        membership = walk_membership(USER, graph({USER: (PLATFORM,)}))
        assert unreached(membership, {"g-platform", "g-legacy"}) == {"g-legacy"}

    def test_an_empty_transitive_set_reports_nothing(self) -> None:
        """Failing to read the cross-check must not invent a gap."""
        from arcet.groups import unreached

        membership = walk_membership(USER, graph({USER: (PLATFORM,)}))
        assert unreached(membership, frozenset()) == frozenset()


class TestLabels:
    @pytest.mark.parametrize(
        ("groups", "expected"),
        [
            ((PLATFORM,), 'group "Platform"'),
            ((PLATFORM, SRE), 'group "Platform" → group "SRE" (nested)'),
            (
                (PLATFORM, SRE, LEGACY),
                'group "Platform" → group "SRE" → group "Legacy" (nested)',
            ),
        ],
    )
    def test_label(self, groups: tuple[GroupRef, ...], expected: str) -> None:
        from arcet.groups import GroupPath

        assert GroupPath(groups=groups).label() == expected
