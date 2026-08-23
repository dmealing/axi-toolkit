"""Recovery intent, rendered as a sentence for a caller that is not a shell.

The same :class:`~axi_core.errors.Recovery` the CLI renderer turns into
``Run `ha-axi area list` to see each area's id`` becomes, here,
``To see each area's id, use ha-axi's `area list` command.`` -- which is the form a
caller embedding this package wants when it has to tell a person, or a model, what
went wrong and what to do about it.

The difference is not decoration. A programmatic caller cannot run the shell line, and
handing it one invites it to claim it did. A sentence naming the tool says who owns
the fix without implying the caller is about to execute it.

Every sentence names the tool that owns the command -- and the name arrives as an
argument, so the *caller's* tool is named rather than whichever tool happened to raise
the error. Two kinds legitimately do not name it: a :data:`~axi_core.errors.KIND_CHOOSE`
offers values that belong to the system rather than to the tool, and a note names it
only if its author wrote :data:`~axi_core.errors.TOOL_SLOT`.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..errors import (
    KIND_CHOOSE,
    KIND_RETRY,
    KIND_RUN,
    KIND_SET_ENV,
    TOOL_SLOT,
    Recovery,
)

__all__ = ["sentence", "sentences"]

_DEFAULT_RUN_LEAD = "Run"
_DEFAULT_RETRY_LEAD = "Run the command again with"
_TERMINATORS = ".!?:"


def sentence(recovery: Recovery, tool: str) -> str:
    """One recovery, as a sentence naming ``tool``."""
    kind = recovery.kind
    if kind == KIND_RUN:
        command = " ".join(recovery.args)
        if recovery.lead != _DEFAULT_RUN_LEAD:
            return _terminate(f"{_capitalise(recovery.lead)} {tool}'s `{command}`{_tail(recovery)}")
        if recovery.purpose:
            return _terminate(f"{_capitalise(recovery.purpose)}, use {tool}'s `{command}` command")
        return _terminate(f"Use {tool}'s `{command}` command")
    if kind == KIND_RETRY:
        if recovery.lead == _DEFAULT_RETRY_LEAD:
            return _terminate(
                f"Run the same {tool} command again with `{recovery.fragment}`{_tail(recovery)}"
            )
        return _terminate(
            f"{_capitalise(recovery.lead)} `{recovery.fragment}`{_tail(recovery)}, "
            f"then run it again with {tool}"
        )
    if kind == KIND_SET_ENV:
        out = (
            f"{tool} reads {recovery.variable} from the environment: set it to {recovery.describes}"
        )
        if recovery.example:
            out += f", e.g. {recovery.example}"
        if recovery.reference:
            out += f"; see {recovery.reference}"
        return _terminate(out)
    if kind == KIND_CHOOSE:
        # No tool named: the values are the system's vocabulary, not the tool's.
        return _terminate(f"{_capitalise(recovery.label)}: {', '.join(recovery.values)}")
    return _terminate(recovery.text.replace(TOOL_SLOT, tool))


def sentences(recoveries: Iterable[Recovery], tool: str) -> list[str]:
    """Every recovery in order, each as a sentence naming ``tool``."""
    return [sentence(item, tool) for item in recoveries]


def _tail(recovery: Recovery) -> str:
    """The purpose clause, always joined with a plain space.

    The CLI renderer carries the source tool's own separator so it can reproduce a
    line byte for byte. Prose owes nothing to that: it is writing a new sentence, and
    a colon that bound an explanation to a shell command reads as a stray one here.
    """
    return f" {recovery.purpose}" if recovery.purpose else ""


def _capitalise(text: str) -> str:
    """Upper-case the first character and leave every other one alone.

    ``str.capitalize`` would lower-case the rest, which turns ``HA_URL`` into
    ``ha_url`` and a Home Assistant into a home assistant.
    """
    return text[:1].upper() + text[1:] if text else text


def _terminate(text: str) -> str:
    """End the sentence, unless the author already did."""
    return text if text[-1:] in _TERMINATORS else text + "."
