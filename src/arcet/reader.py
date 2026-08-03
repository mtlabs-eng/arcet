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
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
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
    DenyAssignmentRef,
    EligibleAssignment,
    ProviderOperation,
    RoleAssignment,
    RoleDefinition,
    parse_activated_assignment_ids,
    parse_deny_assignment,
    parse_eligible_assignment,
    parse_provider_operations,
    parse_role_assignment,
    parse_role_definition,
)
from arcet.auth import GRAPH_SCOPE
from arcet.groups import GroupRef, Membership, walk_membership
from arcet.model import IdentityKind, IdentityRef

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

    from arcet.diagnostics import Diagnostics

__all__ = ["ArmReader", "AzureSource", "GraphReader", "is_guid"]

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


def _fatal_or_reason(error: HttpResponseError) -> str:
    """Classify a failed read, letting authentication failures through.

    ClientAuthenticationError subclasses HttpResponseError, so without this it
    would be recorded as "this scope could not be read" — and an identity that
    could not be looked up would surface as an identity that does not exist.
    Reporting "no such user" when the truth is "you are not signed in" is the
    exact shape of wrong answer this tool exists to avoid.
    """
    if isinstance(error, ClientAuthenticationError):
        raise error
    return _reason(error)


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
            self._diagnostics.unreadable(
                "role assignments", scope, _fatal_or_reason(error)
            )
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
                "role definition", role_definition_id, _fatal_or_reason(error)
            )
            return None
        return parse_role_definition(definition.serialize(keep_readonly=True))

    def eligible_assignments(self, principal_id: str) -> tuple[EligibleAssignment, ...]:
        """Roles the principal may activate, directly or through a group."""
        if not is_guid(principal_id):
            msg = f"principal id is not a GUID: {principal_id!r}"
            raise ValueError(msg)
        scope = f"/subscriptions/{self._subscription_id}"
        try:
            found = self._client.role_eligibility_schedule_instances.list_for_scope(
                scope, filter=f"assignedTo('{principal_id}')"
            )
            return tuple(
                parse_eligible_assignment(item.serialize(keep_readonly=True))
                for item in found
            )
        except HttpResponseError as error:
            # Losing this does not shrink the answer, it removes a whole half
            # of it: everything the identity could become in five minutes.
            self._diagnostics.unreadable(
                "PIM eligibilities", scope, _fatal_or_reason(error)
            )
            return ()

    def activated_assignment_ids(self, principal_id: str) -> frozenset[str]:
        """Which active assignments exist because a PIM role was activated."""
        if not is_guid(principal_id):
            msg = f"principal id is not a GUID: {principal_id!r}"
            raise ValueError(msg)
        scope = f"/subscriptions/{self._subscription_id}"
        try:
            found = self._client.role_assignment_schedule_instances.list_for_scope(
                scope, filter=f"assignedTo('{principal_id}')"
            )
            return parse_activated_assignment_ids(
                [item.serialize(keep_readonly=True) for item in found]
            )
        except HttpResponseError as error:
            # Only costs a label on the chain, never a permission, so this one
            # is recorded and stepped over.
            self._diagnostics.unreadable(
                "PIM activation history", scope, _fatal_or_reason(error)
            )
            return frozenset()

    def deny_assignments(self) -> tuple[DenyAssignmentRef, ...]:
        """Deny assignments in scope, which v0.1 records but does not evaluate."""
        scope = f"/subscriptions/{self._subscription_id}"
        try:
            found = self._client.deny_assignments.list_for_scope(scope)
            return tuple(
                parse_deny_assignment(item.serialize(keep_readonly=True))
                for item in found
            )
        except HttpResponseError as error:
            self._diagnostics.unreadable(
                "deny assignments", scope, _fatal_or_reason(error)
            )
            return ()

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
                "provider operations catalogue", None, _fatal_or_reason(error)
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

    def _paged(self, path: str) -> list[dict[str, Any]]:
        """Follow every page of a Graph collection.

        Stopping at the first page would silently drop group memberships, and
        a missing membership is a missing permission.
        """
        items: list[dict[str, Any]] = []
        url = f"{GRAPH_BASE}{path}"
        while url:
            response = self._client.send_request(HttpRequest("GET", url))
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                break
            page = payload.get("value")
            if isinstance(page, list):
                items += [item for item in page if isinstance(item, dict)]
            next_link = payload.get("@odata.nextLink")
            url = next_link if isinstance(next_link, str) else ""
        return items

    def parent_groups(self, collection: str, object_id: str) -> tuple[GroupRef, ...]:
        """The groups an object belongs to, one level up.

        Directory roles and administrative units also come back from memberOf
        and are filtered out: they are not what grants Azure RBAC, and treating
        them as groups would put a step in the chain that explains nothing.
        """
        try:
            items = self._paged(
                f"/{collection}/{object_id}/memberOf?$select=id,displayName"
            )
        except HttpResponseError as error:
            self._diagnostics.unreadable(
                "group membership", object_id, _fatal_or_reason(error)
            )
            return ()
        return tuple(
            GroupRef(
                object_id=item.get("id") or "",
                display_name=item.get("displayName") or item.get("id") or "",
            )
            for item in items
            if item.get("@odata.type") == "#microsoft.graph.group" and item.get("id")
        )

    def transitive_group_ids(self, collection: str, object_id: str) -> frozenset[str]:
        """Every group Graph can reach, used only to check the walk.

        Failing to read this is not fatal: it costs the cross-check, not the
        answer, so it is reported and the walk stands on its own.
        """
        try:
            items = self._paged(
                f"/{collection}/{object_id}/transitiveMemberOf?$select=id"
            )
        except HttpResponseError as error:
            self._diagnostics.unreadable(
                "transitive group membership", object_id, _fatal_or_reason(error)
            )
            return frozenset()
        return frozenset(
            item["id"]
            for item in items
            if item.get("@odata.type") == "#microsoft.graph.group" and item.get("id")
        )

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
                self._diagnostics.unreadable(
                    "identity", identifier, _fatal_or_reason(error)
                )
                return None
            if payload is not None:
                return build_identity(payload, kind)
        return None


class AzureSource:
    """The live PermissionSource: the two readers, behind one protocol.

    Holds one piece of state, the kind of the identity found, because Graph
    exposes membership under a different collection for users and for service
    principals. Nothing is cached across runs — see CLAUDE.md, stateless.
    """

    def __init__(
        self,
        credential: TokenCredential,
        subscription_id: str,
        diagnostics: Diagnostics,
    ) -> None:
        self._arm = ArmReader(credential, subscription_id, diagnostics)
        self._graph = GraphReader(credential, diagnostics)
        self._collection = "users"

    def find_identity(self, identifier: str) -> IdentityRef | None:
        identity = self._graph.find_identity(identifier)
        if identity is not None:
            self._collection = (
                "servicePrincipals"
                if identity.kind is IdentityKind.SERVICE_PRINCIPAL
                else "users"
            )
        return identity

    def group_membership(self, object_id: str) -> Membership:
        def parents_of(current: str) -> tuple[GroupRef, ...]:
            # The subject hangs off its own collection; everything above it is
            # a group, whatever the subject was.
            collection = self._collection if current == object_id else "groups"
            return self._graph.parent_groups(collection, current)

        return walk_membership(object_id, parents_of)

    def transitive_group_ids(self, object_id: str) -> frozenset[str]:
        return self._graph.transitive_group_ids(self._collection, object_id)

    def role_assignments_for(self, object_id: str) -> tuple[RoleAssignment, ...]:
        return self._arm.role_assignments_for(object_id)

    def eligible_assignments(self, object_id: str) -> tuple[EligibleAssignment, ...]:
        return self._arm.eligible_assignments(object_id)

    def activated_assignment_ids(self, object_id: str) -> frozenset[str]:
        return self._arm.activated_assignment_ids(object_id)

    def deny_assignments(self) -> tuple[DenyAssignmentRef, ...]:
        return self._arm.deny_assignments()

    def role_definition(self, role_definition_id: str) -> RoleDefinition | None:
        return self._arm.role_definition(role_definition_id)

    def provider_operations(self) -> tuple[ProviderOperation, ...] | None:
        return self._arm.provider_operations()


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
