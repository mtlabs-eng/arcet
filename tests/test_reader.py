"""Tests for the pure helpers in the read layer, and for Diagnostics.

The network calls themselves are a thin wrapper and are not exercised here;
what is exercised is everything that decides what those calls mean.
"""

from __future__ import annotations

import pytest

from arcet.diagnostics import Diagnostics
from arcet.model import IdentityKind, UnsupportedConstructKind
from arcet.reader import build_identity, is_guid

GUID = "99999999-8888-7777-6666-555555555555"


class TestIsGuid:
    @pytest.mark.parametrize(
        "value",
        [GUID, GUID.upper(), "00000000-0000-0000-0000-000000000000"],
    )
    def test_accepts_guids(self, value: str) -> None:
        assert is_guid(value)

    @pytest.mark.parametrize(
        "value",
        [
            "user@empresa.pt",
            "",
            "not-a-guid",
            GUID[:-1],
            f"{GUID} or 1=1",
            f"' or principalId ne '{GUID}",
        ],
    )
    def test_rejects_everything_else(self, value: str) -> None:
        """Also the shapes someone would try to smuggle into an OData filter."""
        assert not is_guid(value)


class TestBuildIdentity:
    def test_user_prefers_the_principal_name(self) -> None:
        identity = build_identity(
            {"id": GUID, "userPrincipalName": "user@empresa.pt", "displayName": "User"},
            IdentityKind.USER,
        )
        assert identity.display_name == "user@empresa.pt"
        assert identity.object_id == GUID
        assert identity.kind is IdentityKind.USER

    def test_service_principal_uses_its_display_name(self) -> None:
        identity = build_identity(
            {"id": GUID, "displayName": "ci-deployer", "appId": "app-1"},
            IdentityKind.SERVICE_PRINCIPAL,
        )
        assert identity.display_name == "ci-deployer"
        assert identity.kind is IdentityKind.SERVICE_PRINCIPAL

    def test_falls_back_to_the_object_id(self) -> None:
        """A directory that withholds names should still yield a usable answer."""
        identity = build_identity({"id": GUID}, IdentityKind.USER)
        assert identity.display_name == GUID


class TestDiagnostics:
    def test_starts_empty(self, diagnostics: Diagnostics) -> None:
        assert not diagnostics
        assert diagnostics.snapshot() == ()

    def test_records_in_order(self, diagnostics: Diagnostics) -> None:
        diagnostics.add(UnsupportedConstructKind.DENY_ASSIGNMENT, "first")
        diagnostics.add(UnsupportedConstructKind.ABAC_CONDITION, "second")
        assert [w.message for w in diagnostics.snapshot()] == ["first", "second"]

    def test_identical_findings_collapse(self, diagnostics: Diagnostics) -> None:
        """Repeating one warning per scope walked buries the others."""
        for _ in range(5):
            diagnostics.add(UnsupportedConstructKind.DENY_ASSIGNMENT, "same", "/scope")
        assert len(diagnostics) == 1

    def test_same_message_at_different_refs_is_kept(
        self, diagnostics: Diagnostics
    ) -> None:
        diagnostics.add(UnsupportedConstructKind.DENY_ASSIGNMENT, "same", "/a")
        diagnostics.add(UnsupportedConstructKind.DENY_ASSIGNMENT, "same", "/b")
        assert len(diagnostics) == 2

    def test_unreadable_is_an_insufficient_read_access(
        self, diagnostics: Diagnostics
    ) -> None:
        diagnostics.unreadable("role assignments", "/subscriptions/x", "not authorised")
        warning = diagnostics.snapshot()[0]
        assert warning.kind is UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS
        assert "role assignments" in warning.message
        assert "not authorised" in warning.message
        assert "may be missing" in warning.message
        assert warning.ref == "/subscriptions/x"

    def test_snapshot_is_immutable(self, diagnostics: Diagnostics) -> None:
        diagnostics.add(UnsupportedConstructKind.UNRECOGNISED, "one")
        snapshot = diagnostics.snapshot()
        diagnostics.add(UnsupportedConstructKind.UNRECOGNISED, "two")
        assert len(snapshot) == 1
