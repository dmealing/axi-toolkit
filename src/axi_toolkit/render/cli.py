"""Recovery intent, rendered for a shell.

This is the renderer that has to be exactly right. Both source tools assert their own
help and recovery text in their own suites, so a line that reads *slightly*
differently after extraction is not a cosmetic change -- it is a diff those suites
fail on, in a repository that did not change. ``tests/test_render_cli.py`` holds this
to account against every literal recovery line either tool emits today, byte for byte.

:func:`parse` is the inverse, and it is here for two reasons rather than one. It is
the migration aid -- it turns a tool's existing literal into the intent that replaces
it -- and it is what makes the byte-for-byte claim cover the *whole* corpus instead of
a sample somebody chose. A line :func:`parse` cannot express is a gap in the
vocabulary, reported as one, and never a line quietly skipped.

The one rule that governs both directions: **the tool's name enters here and nowhere
earlier.** A parsed intent that still contains the name anywhere but the command it
names is refused as a command and kept as prose with a ``{tool}`` slot, so the
resulting intent is one the sibling tool could render as its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..errors import (
    KIND_CHOOSE,
    KIND_RETRY,
    KIND_RUN,
    KIND_SET_ENV,
    TOOL_SLOT,
    Recovery,
    note,
)

__all__ = ["line", "lines", "parse", "parse_all"]

_DEFAULT_SEPARATOR = " "

# `Set <VAR> to <describes>`, with the two trailing spellings the source tools use.
_SET_ENV = re.compile(r"^Set (?P<variable>[A-Z][A-Z0-9_]*) to (?P<rest>.+)$")
_EXAMPLE = ", e.g. "
_REFERENCE = "; see "

# The first backtick-delimited span on the line, and what sits either side of it.
_BACKTICKED = re.compile(r"^(?P<lead>[^`]*)`(?P<body>[^`]*)`(?P<rest>.*)$", re.DOTALL)


def line(recovery: Recovery, tool: str) -> str:
    """One recovery, as the line ``tool`` would print."""
    kind = recovery.kind
    if kind == KIND_RUN:
        command = " ".join((tool, *recovery.args))
        return _with_tail(f"{recovery.lead} `{command}`", recovery)
    if kind == KIND_RETRY:
        return _with_tail(f"{recovery.lead} `{recovery.fragment}`", recovery)
    if kind == KIND_SET_ENV:
        out = f"Set {recovery.variable} to {recovery.describes}"
        if recovery.example:
            out += f"{_EXAMPLE}{recovery.example}"
        if recovery.reference:
            out += f"{_REFERENCE}{recovery.reference}"
        return out
    if kind == KIND_CHOOSE:
        return f"{recovery.label}: {', '.join(recovery.values)}"
    return recovery.text.replace(TOOL_SLOT, tool)


def lines(recoveries: Iterable[Recovery], tool: str) -> list[str]:
    """Every recovery in order, as the lines ``tool`` would print."""
    return [line(item, tool) for item in recoveries]


def _with_tail(head: str, recovery: Recovery) -> str:
    """Append the trailing clause, if this recovery has one.

    The separator is carried rather than assumed because the tools use two: a space
    for ``Run `x` to see y``, and ``": "`` where the explanation is bound to the
    command with a colon. It is appended whenever it is not the default even with an
    empty purpose, which is what lets a line ending in bare punctuation round-trip.
    """
    if recovery.purpose or recovery.separator != _DEFAULT_SEPARATOR:
        return f"{head}{recovery.separator}{recovery.purpose}"
    return head


def parse(text: str, tool: str) -> Recovery:
    """The intent that renders back to ``text`` for ``tool``.

    Succeeds for any line a tool would actually print: prose that fits no structured
    kind becomes a note carrying the same bytes with the tool's name replaced by
    :data:`~axi_toolkit.errors.TOOL_SLOT`. An empty line raises, because an empty
    suggestion is worse than none -- it occupies the slot that should have held the
    fix -- and the tools already drop blank help lines before printing them. It
    is the caller's job to notice that -- ``kind == "note"`` on something that looks
    like a command is the signal that the vocabulary is missing a shape, and the
    population check in ``tests/conformance`` is what turns that signal into a failure.

    :func:`line` composed with this is the identity on every line either source tool
    emits; that is asserted, not assumed.
    """
    if not text.strip():
        raise ValueError("an empty line is not a recovery")
    structured = _parse_set_env(text) or _parse_backticked(text, tool)
    if structured is not None and not _names_tool_outside_command(structured, tool):
        return structured
    return note(text.replace(tool, TOOL_SLOT))


def parse_all(texts: Iterable[str], tool: str) -> list[Recovery]:
    return [parse(text, tool) for text in texts]


def _parse_set_env(text: str) -> Recovery | None:
    match = _SET_ENV.match(text)
    if match is None:
        return None
    rest = match.group("rest")
    example = reference = ""
    # Order matters only in that each spelling is looked for once, from the right: a
    # reference is a URL and may itself contain ", e.g. " in no realistic case, while
    # a describes clause routinely contains a comma.
    if _REFERENCE in rest:
        rest, _, reference = rest.rpartition(_REFERENCE)
    if _EXAMPLE in rest:
        rest, _, example = rest.rpartition(_EXAMPLE)
    if not rest:
        return None
    return Recovery(
        kind=KIND_SET_ENV,
        variable=match.group("variable"),
        describes=rest,
        example=example,
        reference=reference,
    )


def _parse_backticked(text: str, tool: str) -> Recovery | None:
    match = _BACKTICKED.match(text)
    if match is None:
        return None
    lead, body, rest = match.group("lead"), match.group("body"), match.group("rest")
    if not lead.endswith(" "):
        # `foo` at the very start of a line, or one glued to the preceding word: no
        # lead clause to carry, so this is prose rather than a suggestion to run.
        return None
    separator, purpose = _split_tail(rest)
    if body == tool or body.startswith(tool + " "):
        args = tuple(body[len(tool) :].split())
        if not args:
            return None
        return Recovery(
            kind=KIND_RUN,
            args=args,
            purpose=purpose,
            lead=lead[:-1],
            separator=separator,
        )
    if not body:
        return None
    return Recovery(
        kind=KIND_RETRY,
        fragment=body,
        purpose=purpose,
        lead=lead[:-1],
        separator=separator,
    )


def _split_tail(rest: str) -> tuple[str, str]:
    """Divide what follows the closing backtick into a separator and a purpose."""
    if not rest:
        return _DEFAULT_SEPARATOR, ""
    index = rest.find(" ")
    if index == -1:
        return rest, ""
    return rest[: index + 1], rest[index + 1 :]


def _names_tool_outside_command(recovery: Recovery, tool: str) -> bool:
    """Whether the tool's name survives anywhere it would be baked in.

    A ``run`` may name the tool in the command it names -- that is composed at render
    time and is the whole point. Anywhere else, and in any other kind, a literal name
    would make the intent belong to one tool forever, which is the property this
    package exists to remove.
    """
    return any(
        tool in value
        for value in (recovery.lead, recovery.purpose, recovery.fragment, recovery.describes)
    )
