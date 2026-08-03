"""The read-only guarantee, enforced by the build rather than by intent.

CLAUDE.md says any code that calls a write API is a bug. This test is what
makes that statement checkable: it walks the package's syntax tree and fails if
a mutating SDK call or a non-GET request appears anywhere.

It is a blunt instrument and it will occasionally flag something harmless. That
is the right trade: a false positive costs one conversation, and a false
negative costs the promise the whole tool rests on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import arcet

PACKAGE_ROOT = Path(arcet.__file__).parent
SOURCES = sorted(PACKAGE_ROOT.rglob("*.py"))

#: Method names that mutate in the Azure SDKs. `begin_` covers the long-running
#: operations, which are all writes.
FORBIDDEN_METHODS = frozenset(
    {
        "create",
        "create_or_update",
        "delete",
        "patch",
        "post",
        "put",
        "remove",
        "replace",
        "update",
        "validate_move_resources",
    }
)
FORBIDDEN_PREFIXES = ("begin_",)

#: Anything that is not a read.
WRITE_VERBS = frozenset({"POST", "PUT", "PATCH", "DELETE", "MERGE"})


def test_the_package_has_sources_to_check() -> None:
    """Guards the guard: an empty glob would make everything below pass."""
    assert SOURCES


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_no_mutating_sdk_calls(source: Path) -> None:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    offenders = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (
            node.func.attr in FORBIDDEN_METHODS
            or node.func.attr.startswith(FORBIDDEN_PREFIXES)
        )
    ]
    assert offenders == [], f"{source.name} calls {offenders}; arcet never writes"


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_no_write_verbs(source: Path) -> None:
    """No string literal anywhere names a mutating HTTP method."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.upper() in WRITE_VERBS
    ]
    assert offenders == [], f"{source.name} mentions {offenders}"


def test_every_http_request_is_a_get() -> None:
    """Each HttpRequest is constructed with GET as a literal first argument.

    A method passed as a variable would slip past the check above, so the call
    shape itself is pinned.
    """
    for source in SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "HttpRequest":
                continue
            assert node.args, f"{source.name}: HttpRequest called without a method"
            method = node.args[0]
            assert isinstance(method, ast.Constant), (
                f"{source.name}: HttpRequest method must be a literal, "
                f"so that this test can check it"
            )
            assert method.value == "GET", (
                f"{source.name}: HttpRequest({method.value!r})"
            )


def test_no_module_imports_a_write_capable_management_client() -> None:
    """Only the authorization management client is imported, and only for reads.

    A new azure-mgmt-* import is the moment to think about whether it can
    write, so it fails here until someone does.
    """
    allowed = {"azure.mgmt.authorization"}
    for source in SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module.startswith("azure.mgmt"):
                assert module in allowed, f"{source.name} imports {module}"
