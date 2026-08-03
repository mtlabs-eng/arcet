"""Tests for the resolution data model.

No Azure, no network, no fixtures on disk yet — milestone 1 is the shape of a
result, not where it comes from.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from arcet import model as model_module
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
    canonical_permissions,
)

ROLE_STEP = DerivationStep(
    kind=DerivationKind.ROLE_ASSIGNMENT,
    label='role "Key Vault Secrets User"',
    ref="/subscriptions/sub-1/resourceGroups/rg-prod",
)
GROUP_STEP = DerivationStep(
    kind=DerivationKind.GROUP_MEMBERSHIP,
    label='group "Platform" -> group "SRE" (nested)',
    ref="/groups/00000000-0000-0000-0000-000000000001",
)
PIM_STEP = DerivationStep(
    kind=DerivationKind.PIM_ELIGIBLE,
    label='role "User Access Administrator" (eligible)',
    ref="/subscriptions/sub-1",
)

IDENTITY = IdentityRef(
    object_id="00000000-0000-0000-0000-0000000000ff",
    display_name="user@empresa.pt",
    kind=IdentityKind.USER,
)


def permission(
    action: str = "Microsoft.KeyVault/vaults/secrets/read",
    *,
    action_kind: ActionKind = ActionKind.CONTROL_PLANE,
    state: PermissionState = PermissionState.ACTIVE,
    scope: str = "/subscriptions/sub-1",
    derivation: tuple[DerivationStep, ...] = (ROLE_STEP,),
) -> EffectivePermission:
    return EffectivePermission(
        action=action,
        action_kind=action_kind,
        state=state,
        scope=scope,
        derivation=derivation,
    )


class TestBlankFields:
    """Blank text is a bug upstream, and it surfaces where it was created."""

    @pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
    def test_derivation_step_rejects_blank_label(self, blank: str) -> None:
        with pytest.raises(ValueError, match="label"):
            DerivationStep(kind=DerivationKind.ROLE_ASSIGNMENT, label=blank, ref="/x")

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_derivation_step_rejects_blank_ref(self, blank: str) -> None:
        with pytest.raises(ValueError, match="ref"):
            DerivationStep(kind=DerivationKind.ROLE_ASSIGNMENT, label="l", ref=blank)

    def test_identity_rejects_blank_object_id(self) -> None:
        with pytest.raises(ValueError, match="object_id"):
            IdentityRef(object_id=" ", display_name="n", kind=IdentityKind.USER)

    def test_identity_rejects_blank_display_name(self) -> None:
        with pytest.raises(ValueError, match="display_name"):
            IdentityRef(object_id="id", display_name="", kind=IdentityKind.USER)

    def test_permission_rejects_blank_action(self) -> None:
        with pytest.raises(ValueError, match="action"):
            permission(action="")

    def test_permission_rejects_blank_scope(self) -> None:
        with pytest.raises(ValueError, match="scope"):
            permission(scope="  ")

    def test_result_rejects_blank_subscription(self) -> None:
        with pytest.raises(ValueError, match="subscription"):
            ResolutionResult(identity=IDENTITY, subscription="")

    def test_unsupported_construct_rejects_blank_message(self) -> None:
        with pytest.raises(ValueError, match="message"):
            UnsupportedConstruct(
                kind=UnsupportedConstructKind.DENY_ASSIGNMENT, message=""
            )

    def test_unsupported_construct_allows_absent_ref(self) -> None:
        construct = UnsupportedConstruct(
            kind=UnsupportedConstructKind.UNRECOGNISED, message="something new"
        )
        assert construct.ref is None

    def test_unsupported_construct_rejects_blank_ref(self) -> None:
        """Absent is a fact; blank is a dropped value pretending to be one."""
        with pytest.raises(ValueError, match="ref"):
            UnsupportedConstruct(
                kind=UnsupportedConstructKind.UNRECOGNISED, message="m", ref=" "
            )


class TestChainIsMandatory:
    """The chain is the product. A permission without one cannot exist."""

    def test_empty_derivation_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="derivation must not be empty"):
            permission(derivation=())

    def test_the_error_names_the_permission(self) -> None:
        with pytest.raises(ValueError, match=r"Microsoft\.Storage/read"):
            permission(action="Microsoft.Storage/read", derivation=())

    def test_a_single_step_is_enough(self) -> None:
        assert permission(derivation=(ROLE_STEP,)).derivation == (ROLE_STEP,)

    def test_derivation_order_is_preserved(self) -> None:
        """Subject first, origin last — the order it is read aloud in."""
        perm = permission(derivation=(GROUP_STEP, ROLE_STEP))
        assert perm.derivation == (GROUP_STEP, ROLE_STEP)

    def test_a_list_is_stored_as_a_tuple(self) -> None:
        """A caller must not be able to mutate a chain after handing it over."""
        chain = [GROUP_STEP, ROLE_STEP]
        perm = permission(derivation=chain)  # type: ignore[arg-type]
        chain.append(PIM_STEP)
        assert perm.derivation == (GROUP_STEP, ROLE_STEP)
        assert isinstance(perm.derivation, tuple)


class TestPimLabelling:
    def test_eligible_without_a_pim_step_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="PIM_ELIGIBLE"):
            permission(state=PermissionState.PIM_ELIGIBLE, derivation=(ROLE_STEP,))

    def test_eligible_with_a_pim_step_is_accepted(self) -> None:
        perm = permission(state=PermissionState.PIM_ELIGIBLE, derivation=(PIM_STEP,))
        assert perm.state is PermissionState.PIM_ELIGIBLE

    def test_eligible_finds_the_pim_step_anywhere_in_the_chain(self) -> None:
        perm = permission(
            state=PermissionState.PIM_ELIGIBLE, derivation=(GROUP_STEP, PIM_STEP)
        )
        assert perm.state is PermissionState.PIM_ELIGIBLE

    def test_active_may_carry_a_pim_step(self) -> None:
        """An activated PIM assignment is active, and says so in its chain."""
        perm = permission(state=PermissionState.ACTIVE, derivation=(PIM_STEP,))
        assert perm.state is PermissionState.ACTIVE


class TestImmutability:
    @pytest.mark.parametrize(
        ("obj", "attr"),
        [
            (ROLE_STEP, "label"),
            (IDENTITY, "display_name"),
            (permission(), "action"),
            (ResolutionResult(identity=IDENTITY, subscription="sub-1"), "subscription"),
        ],
    )
    def test_fields_cannot_be_reassigned(self, obj: object, attr: str) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, attr, "changed")

    def test_permissions_are_hashable(self) -> None:
        """Hashability is what makes exact-duplicate collapsing trivial."""
        assert len({permission(), permission()}) == 1


class TestCanonicalOrder:
    def test_sorted_by_action(self) -> None:
        b = permission(action="B/read")
        a = permission(action="A/read")
        assert canonical_permissions([b, a]) == (a, b)

    def test_control_plane_before_data_plane(self) -> None:
        data = permission(action="same/read", action_kind=ActionKind.DATA_PLANE)
        control = permission(action="same/read", action_kind=ActionKind.CONTROL_PLANE)
        assert canonical_permissions([data, control]) == (control, data)

    def test_active_before_eligible(self) -> None:
        eligible = permission(
            state=PermissionState.PIM_ELIGIBLE, derivation=(PIM_STEP,)
        )
        active = permission(state=PermissionState.ACTIVE)
        assert canonical_permissions([eligible, active]) == (active, eligible)

    def test_sorted_by_scope_last(self) -> None:
        wide = permission(scope="/subscriptions/sub-1")
        narrow = permission(scope="/subscriptions/sub-1/resourceGroups/rg-a")
        assert canonical_permissions([narrow, wide]) == (wide, narrow)

    def test_exact_duplicates_collapse(self) -> None:
        assert canonical_permissions([permission(), permission()]) == (permission(),)

    def test_same_action_by_different_chains_is_kept(self) -> None:
        """Two chains are two facts. Picking one would be a judgement call."""
        via_group = permission(derivation=(GROUP_STEP, ROLE_STEP))
        direct = permission(derivation=(ROLE_STEP,))
        assert len(canonical_permissions([via_group, direct])) == 2

    def test_input_order_does_not_change_output(self) -> None:
        """Determinism: the same set of facts renders the same way every run."""
        perms = [
            permission(action="B/read"),
            permission(action="A/read", action_kind=ActionKind.DATA_PLANE),
            permission(action="A/read"),
        ]
        assert canonical_permissions(perms) == canonical_permissions(reversed(perms))

    def test_empty_input(self) -> None:
        assert canonical_permissions([]) == ()


class TestResolutionResult:
    def test_permissions_are_canonical_on_construction(self) -> None:
        """Renderers inherit the ordering instead of each remembering to sort."""
        result = ResolutionResult(
            identity=IDENTITY,
            subscription="sub-1",
            permissions=(permission(action="B/read"), permission(action="A/read")),
        )
        assert [p.action for p in result.permissions] == ["A/read", "B/read"]

    def test_duplicates_collapse_on_construction(self) -> None:
        result = ResolutionResult(
            identity=IDENTITY,
            subscription="sub-1",
            permissions=(permission(), permission()),
        )
        assert len(result.permissions) == 1

    def test_lists_are_stored_as_tuples(self) -> None:
        result = ResolutionResult(
            identity=IDENTITY,
            subscription="sub-1",
            permissions=[permission()],  # type: ignore[arg-type]
            warnings=[
                UnsupportedConstruct(
                    kind=UnsupportedConstructKind.DENY_ASSIGNMENT, message="m"
                )
            ],  # type: ignore[arg-type]
        )
        assert isinstance(result.permissions, tuple)
        assert isinstance(result.warnings, tuple)

    def test_defaults_are_empty(self) -> None:
        result = ResolutionResult(identity=IDENTITY, subscription="sub-1")
        assert result.permissions == ()
        assert result.warnings == ()

    def test_is_complete_without_warnings(self) -> None:
        assert ResolutionResult(identity=IDENTITY, subscription="sub-1").is_complete

    def test_is_not_complete_with_warnings(self) -> None:
        """A result carrying warnings must never be presented as the whole truth."""
        result = ResolutionResult(
            identity=IDENTITY,
            subscription="sub-1",
            warnings=(
                UnsupportedConstruct(
                    kind=UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
                    message="could not list role assignments at /subscriptions/sub-1",
                    ref="/subscriptions/sub-1",
                ),
            ),
        )
        assert not result.is_complete

    def test_a_result_with_no_permissions_and_no_warnings_is_complete(self) -> None:
        """An identity genuinely holding nothing is a real, complete answer."""
        result = ResolutionResult(identity=IDENTITY, subscription="sub-1")
        assert result.permissions == ()
        assert result.is_complete


class TestEnums:
    def test_every_construct_kind_is_constructible(self) -> None:
        """Nothing is dropped for want of an enum member, UNRECOGNISED included."""
        for kind in UnsupportedConstructKind:
            assert UnsupportedConstruct(kind=kind, message="m").kind is kind

    def test_states_are_distinct(self) -> None:
        assert PermissionState.ACTIVE != PermissionState.PIM_ELIGIBLE

    def test_enum_values_are_stable_strings(self) -> None:
        """These reach the JSON output, so they are contract, not labels."""
        assert PermissionState.ACTIVE == "active"
        assert PermissionState.PIM_ELIGIBLE == "pim_eligible"
        assert ActionKind.CONTROL_PLANE == "control_plane"
        assert ActionKind.DATA_PLANE == "data_plane"
        assert UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS == (
            "insufficient_read_access"
        )


def test_the_model_does_not_depend_on_azure() -> None:
    """Milestone 1 is the shape of a result, not where it comes from.

    Keeping the model free of SDK imports is also what lets every later test
    build results by hand instead of reaching for the network.
    """
    tree = ast.parse(Path(model_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        name for name in imported if name.split(".")[0] in {"azure", "msgraph"}
    }
    assert not forbidden
