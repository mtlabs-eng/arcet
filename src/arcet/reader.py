"""The thin layer that talks to Azure.

Everything here is deliberately dumb: fetch, hand the payload to a parser in
`arm.py`, record a warning if the fetch failed. The logic worth being sure
about lives in the pure modules, which the tests reach without a tenant.

Read-only is enforced by construction rather than by intent. Only GET requests
are issued, only list and get operations are called, and a guard test fails the
build if a write verb or a mutating SDK method appears anywhere in the package.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from azure.core import PipelineClient
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.core.pipeline.policies import (
    BearerTokenCredentialPolicy,
    ContentDecodePolicy,
    RetryPolicy,
    UserAgentPolicy,
)
from azure.core.rest import HttpRequest
from azure.mgmt.authorization import AuthorizationManagementClient

from arcet import __version__
from arcet.arm import (
    ProviderOperation,
    RoleAssignment,
    RoleDefinition,
    parse_provider_operations,
    parse_role_assignment,
    parse_role_definition,
)
from arcet.auth import GRAPH_SCOPE
from arcet.model import IdentityKind, IdentityRef

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

    from arcet.diagnostics import Diagnostics

__all__ = ["ArmReader", "GraphReader", "is_guid"]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_GUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def is_guid(value: str) -> bool:
    """Whether a string is a bare GUID."""
    return bool(_GUID.match(value))


def _reason(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    if status == 403:
        return "not authorised"
    if status == 401:
        return "credentials rejected"
    if status is not None:
        return f"HTTP {status}"
    return type(error).__name__


class ArmReader:
    """Role assignments, role definitions and the operations catalogue."""

    def __init__(
        self,
        credential: TokenCredential,
        subscription_id: str,
        diagnostics: Diagnostics,
    ) -> None:
        self._diagnostics = diagnostics
        self._subscription_id = subscription_id
        self._client = AuthorizationManagementClient(credential, subscription_id)

    def role_assignments_for(self, principal_id: str) -> tuple[RoleAssignment, ...]:
        """Every assignment held by a principal in this subscription.

        The principal id is checked against the GUID shape before it reaches
        the OData filter. It arrives from a Graph lookup rather than from the
        user, but an unvalidated string interpolated into a query is a habit
        worth not having in a security tool.
        """
        if not is_guid(principal_id):
            msg = f"principal id is not a GUID: {principal_id!r}"
            raise ValueError(msg)

        scope = f"/subscriptions/{self._subscription_id}"
        try:
            found = self._client.role_assignments.list_for_subscription(
                filter=f"principalId eq '{principal_id}'"
            )
            # serialize() gives back the wire shape, nested properties and all,
            # which is the same shape the fixtures encode. The parser the tests
            # exercise is therefore the parser that runs here.
            return tuple(
                parse_role_assignment(item.serialize(keep_readonly=True))
                for item in found
            )
        except HttpResponseError as error:
            self._diagnostics.unreadable("role assignments", scope, _reason(error))
            return ()

    def role_definition(self, role_definition_id: str) -> RoleDefinition | None:
        """Resolve a role definition, built-in or custom.

        Returning None is not the same as returning an empty role: the caller
        warns, because a role we could not read is a set of permissions we
        cannot account for.
        """
        try:
            definition = self._client.role_definitions.get_by_id(role_definition_id)
        except HttpResponseError as error:
            self._diagnostics.unreadable(
                "role definition", role_definition_id, _reason(error)
            )
            return None
        return parse_role_definition(definition.serialize(keep_readonly=True))

    def provider_operations(self) -> tuple[ProviderOperation, ...] | None:
        """The catalogue used to expand wildcards.

        None means it could not be read, which the caller turns into literal
        patterns plus a warning rather than into a smaller answer.
        """
        try:
            providers = self._client.provider_operations_metadata.list()
            payloads = [
                provider.serialize(keep_readonly=True) for provider in providers
            ]
        except HttpResponseError as error:
            self._diagnostics.unreadable(
                "provider operations catalogue", None, _reason(error)
            )
            return None
        return parse_provider_operations(payloads)


class GraphReader:
    """Identity lookup against Microsoft Graph.

    Built on the azure-core pipeline that the SDK already brings, so it costs
    no extra dependency and still gets token refresh and retries.
    """

    def __init__(self, credential: TokenCredential, diagnostics: Diagnostics) -> None:
        self._diagnostics = diagnostics
        self._client: PipelineClient[HttpRequest, Any] = PipelineClient(
            base_url=GRAPH_BASE,
            policies=[
                UserAgentPolicy(base_user_agent=f"arcet/{__version__}"),
                BearerTokenCredentialPolicy(credential, GRAPH_SCOPE),
                ContentDecodePolicy(),
                RetryPolicy(),
            ],
        )

    def _get(self, path: str) -> dict[str, Any] | None:
        """Issue one GET. Returns None when the object is simply not there."""
        response = self._client.send_request(HttpRequest("GET", f"{GRAPH_BASE}{path}"))
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def find_identity(self, identifier: str) -> IdentityRef | None:
        """Resolve a UPN or object id to an identity.

        A GUID could name either a user or a service principal, so both are
        tried. Anything else is treated as a user principal name.
        """
        attempts: tuple[tuple[str, IdentityKind], ...]
        if is_guid(identifier):
            attempts = (
                (f"/users/{identifier}", IdentityKind.USER),
                (f"/servicePrincipals/{identifier}", IdentityKind.SERVICE_PRINCIPAL),
            )
        else:
            attempts = ((f"/users/{identifier}", IdentityKind.USER),)

        for path, kind in attempts:
            try:
                payload = self._get(path)
            except ResourceNotFoundError:
                continue
            except HttpResponseError as error:
                self._diagnostics.unreadable("identity", identifier, _reason(error))
                return None
            if payload is not None:
                return build_identity(payload, kind)
        return None


def build_identity(payload: dict[str, Any], kind: IdentityKind) -> IdentityRef:
    """Turn a Graph user or service principal payload into an IdentityRef.

    The display name falls back through the fields Graph may withhold, ending
    at the object id, so that a directory which hides names still yields a
    result the reader can act on rather than an error.
    """
    object_id = payload.get("id") or ""
    display_name = (
        payload.get("userPrincipalName")
        or payload.get("displayName")
        or payload.get("appId")
        or object_id
    )
    return IdentityRef(object_id=object_id, display_name=display_name, kind=kind)
