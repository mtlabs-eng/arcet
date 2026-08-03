"""Collecting what was detected and not interpreted.

Every read path takes a Diagnostics and records anything it could not resolve.
The accuracy rule in CLAUDE.md turns on this: a construct that is dropped
silently makes the answer wrong in a way the reader cannot see, so the only
sanctioned way to not handle something is to say so.
"""

from __future__ import annotations

from arcet.model import UnsupportedConstruct, UnsupportedConstructKind

__all__ = ["Diagnostics"]


class Diagnostics:
    """A growing list of constructs detected and not interpreted.

    Deliberately mutable and passed down through the readers: a resolver that
    had to thread warnings back up through every return value would eventually
    drop one, and dropping one is the failure this class exists to prevent.
    """

    def __init__(self) -> None:
        self._items: list[UnsupportedConstruct] = []

    def add(
        self,
        kind: UnsupportedConstructKind,
        message: str,
        ref: str | None = None,
    ) -> None:
        construct = UnsupportedConstruct(kind=kind, message=message, ref=ref)
        # Identical findings collapse. Repeating "deny assignment not
        # evaluated" once per scope walked buries the other warnings.
        if construct not in self._items:
            self._items.append(construct)

    def unreadable(self, what: str, ref: str | None, reason: str) -> None:
        """Record a read that failed because our credentials could not see it.

        Azure answers an unauthorised list with fewer rows, not an error, so
        wherever we *do* get an error it is the only chance we have to tell the
        reader that the picture is short of something.
        """
        self.add(
            UnsupportedConstructKind.INSUFFICIENT_READ_ACCESS,
            f"could not read {what} ({reason}); some permissions may be missing",
            ref,
        )

    def snapshot(self) -> tuple[UnsupportedConstruct, ...]:
        """The warnings recorded so far, in the order they were found."""
        return tuple(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        """True when something was not interpreted.

        Spelled out because the truthiness of a warnings container is exactly
        the kind of thing that reads backwards at a call site.
        """
        return bool(self._items)
