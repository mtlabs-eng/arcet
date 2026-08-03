"""Authentication, and the read-only guarantee that goes with it.

arcet never writes to Azure. Nothing in this package requests a credential for
anything but reading, and the token scopes below are the only two it ever asks
for. See CLAUDE.md, "O que isto NÃO é".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from azure.identity import DefaultAzureCredential

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

__all__ = ["ARM_SCOPE", "GRAPH_SCOPE", "build_credential"]

#: Token audience for role assignments and role definitions.
ARM_SCOPE = "https://management.azure.com/.default"
#: Token audience for resolving identities and group membership.
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def build_credential() -> TokenCredential:
    """Return the credential arcet reads with.

    DefaultAzureCredential walks the usual sources — environment, workload and
    managed identity, then the Azure CLI — which is what lets the same command
    work on a laptop and in a pipeline without flags.

    Interactive browser login is excluded on purpose. A security tool that
    silently opens a browser mid-pipeline is a tool that hangs a CI job, and a
    missing credential should fail loudly rather than prompt.
    """
    return DefaultAzureCredential(
        exclude_interactive_browser_credential=True,
    )
