"""The redaction boundary: register a secret, and get it back out of anything printed.

Taken from the two source tools' ``output.py``, which is where each of them keeps its
single write path. The document-rendering half of that module stays with each tool --
what is shared, and what has to hold identically in both, is this: a set of literal
secrets, a list of credential *shapes*, and one function that removes both.

The two copies differed in exactly one way, and the difference is the design here. One
tool carries two built-in shapes (a bearer header and a JWT); the other carries those
plus three of its own, for a credential that travels as a URL parameter. So the shapes
are not a fixed list: :func:`register_pattern` is how a tool adds its own, and the
order they run in is fixed and documented, because that order is observable.

**The order is: literals, then the bearer header, then registered patterns, then the
JWT.** Literals go first and longest-first, so an overlapping pair (``user:password``)
is replaced whole rather than leaving a half-redacted fragment behind. The JWT rule
goes last because it replaces its whole match rather than keeping a prefix, and a rule
that keeps a prefix should have had its chance first.

For the five shapes the two tools carry between them the order turns out not to be
observable -- every path converges, because the placeholder a rule leaves behind is
inert to the next one. That is why neither tool wrote the order down, and it is exactly
why it is written down here: the first shape somebody adds where it *does* matter would
otherwise be the thing that discovered it. ``tests/test_redact.py`` pins the two places
the order is visible, with shapes built to make it so.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from re import Pattern

__all__ = [
    "BEARER",
    "JWT",
    "MIN_SECRET_LENGTH",
    "REDACTED",
    "Redactor",
    "redact",
    "register_pattern",
    "register_patterns",
    "register_secret",
    "registered_patterns",
    "reset",
    "reset_secrets",
]

#: Placeholder substituted for anything that looks like a credential.
REDACTED = "<redacted>"

#: Below this length, redacting a literal does more damage than good: a short string
#: collides with ordinary words and would corrupt unrelated output. Lowered only for
#: values already known to be credentials by where they came from -- URL userinfo,
#: say -- rather than by their shape.
MIN_SECRET_LENGTH = 8

#: A bearer credential in an HTTP header. Keeps the ``Bearer `` prefix so the reader
#: can still see what kind of header was involved.
BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")

#: A JSON Web Token: three base64url segments, the first starting ``eyJ`` because it
#: encodes a JSON object. Both systems these tools talk to issue JWTs, which is why
#: this one is built in rather than registered.
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}")


class Redactor:
    """A set of literal secrets and credential shapes, and the filter over them.

    A class rather than only module state so a test can hold one in isolation, and so
    a caller embedding two tools at once can keep their shapes apart. The module-level
    functions below operate on one shared instance, which is what a CLI wants.
    """

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._patterns: list[Pattern[str]] = []

    # ------------------------------------------------------------------ literals

    def register_secret(self, value: str | None, *, min_length: int = MIN_SECRET_LENGTH) -> None:
        """Register a literal string that must never reach stdout or stderr."""
        if value and len(value) >= min_length:
            self._secrets.add(value)

    def reset_secrets(self) -> None:
        """Drop registered literals, keeping registered shapes."""
        self._secrets.clear()

    # ------------------------------------------------------------------- shapes

    def register_pattern(self, pattern: str | Pattern[str]) -> Pattern[str]:
        """Register a credential shape this caller's system produces.

        A pattern with a capturing group keeps group 1 and redacts the rest, which is
        how ``X-Plex-Token=abc123`` becomes ``X-Plex-Token=<redacted>`` rather than
        vanishing: the reader needs to know *which* credential was suppressed. A
        pattern with no group is replaced whole.

        Registering the same source twice is a no-op, so a module imported twice does
        not double the work.
        """
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        if all(existing.pattern != compiled.pattern for existing in self._patterns):
            self._patterns.append(compiled)
        return compiled

    def registered_patterns(self) -> tuple[str, ...]:
        """The source of each registered shape, in the order they run."""
        return tuple(pattern.pattern for pattern in self._patterns)

    def reset(self) -> None:
        """Drop literals and shapes both. Used by tests to isolate cases."""
        self._secrets.clear()
        self._patterns.clear()

    # ------------------------------------------------------------------- filter

    def redact(self, text: str) -> str:
        """Remove credentials from ``text`` by literal match and by shape."""
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(secret, REDACTED)
        text = _apply(BEARER, text)
        for pattern in self._patterns:
            text = _apply(pattern, text)
        return _apply(JWT, text)


def _apply(pattern: Pattern[str], text: str) -> str:
    if pattern.groups:
        return pattern.sub(lambda match: match.group(1) + REDACTED, text)
    return pattern.sub(REDACTED, text)


#: The instance a CLI uses. One process, one output boundary, one set of secrets.
_default = Redactor()


def register_secret(value: str | None, *, min_length: int = MIN_SECRET_LENGTH) -> None:
    """Register a literal on the shared redactor."""
    _default.register_secret(value, min_length=min_length)


def register_patterns(patterns: Iterable[str | Pattern[str]]) -> None:
    """Register several shapes on the shared redactor, in order."""
    for pattern in patterns:
        _default.register_pattern(pattern)


def register_pattern(pattern: str | Pattern[str]) -> Pattern[str]:
    """Register one shape on the shared redactor."""
    return _default.register_pattern(pattern)


def registered_patterns() -> tuple[str, ...]:
    """The shapes registered on the shared redactor, in the order they run."""
    return _default.registered_patterns()


def redact(text: str) -> str:
    """Remove credentials from ``text`` using the shared redactor."""
    return _default.redact(text)


def reset_secrets() -> None:
    """Drop the shared redactor's literals."""
    _default.reset_secrets()


def reset() -> None:
    """Drop the shared redactor's literals and shapes."""
    _default.reset()
