"""The AXI error contract: a code, a fault class, and recovery carried as data.

Two AXI CLIs shipped a 55-line ``errors.py`` that differed in four docstrings and
nothing else, which made this the most duplicated *contract* in the fleet. Copying it
here would have been mechanical. One thing is not, and it is the reason this module
can serve a command-line tool and a caller that is not one:

**Recovery is structured intent, never a rendered line.** Today's help lines have the
owning tool's name baked in at the point the error is raised --
``help_lines=["Run `ha-axi area list` to see the areas that exist"]`` -- so the
sentence belongs to one tool forever. Here the same fact is
:func:`run(("area", "list"), purpose="to see the areas that exist")`, and the tool's
name arrives when somebody renders it: :mod:`axi_toolkit.render.cli` for a shell,
:mod:`axi_toolkit.render.prose` for a caller that will never run one.

The vocabulary is closed -- :data:`KINDS` is the whole of it -- and every kind is a
:class:`Recovery` with the same shape, so a recovery survives ``as_dict`` /
``from_dict`` unchanged and can cross a process boundary as JSON. A kind carrying a
field that does not belong to it is rejected at construction: a mistyped recovery
should fail where it is written, not read as an empty one.

**The tool's name is never stored.** The structured kinds compose it at render time.
:func:`note` -- the escape hatch for prose that is not a command -- may write
``{tool}`` and nothing else, so even free text has a hole where the name goes rather
than the name itself. :func:`mentions_tool` is how a test proves it, and
``tests/test_render_cli.py`` runs that proof over every recovery line the two source
tools emit.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

__all__ = [
    "CLASSES",
    "CLASS_AUTH",
    "CLASS_CONFIG",
    "CLASS_INTERNAL",
    "CLASS_NOT_FOUND",
    "CLASS_PERMISSION",
    "CLASS_REFUSED",
    "CLASS_TRANSPORT",
    "CLASS_UNCLASSIFIED",
    "CLASS_USAGE",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_USAGE",
    "KINDS",
    "KIND_CHOOSE",
    "KIND_NOTE",
    "KIND_RETRY",
    "KIND_RUN",
    "KIND_SET_ENV",
    "TOOL_SLOT",
    "ApiError",
    "AuthFailed",
    "AxiError",
    "ConfigError",
    "ConnectionFailed",
    "Forbidden",
    "NotFound",
    "Recovery",
    "UsageError",
    "choose",
    "fault_class",
    "mentions_tool",
    "note",
    "retry",
    "run",
    "set_env",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


# ------------------------------------------------------------- fault classes
#
# The class is the fact a caller switches on before it can decide what to do next,
# and collapsing any two of them is a defect rather than a simplification: a rejected
# credential is fixed by minting a new token, a command this installation does not
# have is fixed by asking for something else and never by a new token, and a host that
# could not be reached is fixed by nothing at all -- it is the one class where
# retrying the identical command is the correct move.
#
# The classes are shared; the CODES table that assigns a code to one of them is not.
# A code names something specific to the system behind the tool (``NO_SUCH_AREA``,
# ``UNKNOWN_OPERATOR``), so each tool keeps its own closed table and passes it to
# :func:`fault_class`.

#: The invocation is wrong and nothing was sent. Change the command line.
CLASS_USAGE = "usage"
#: This machine is not set up to talk to the system. Change the environment.
CLASS_CONFIG = "config"
#: The system was not reached, or was reached and is not serving.
CLASS_TRANSPORT = "transport"
#: The credential was rejected. A new one is the fix.
CLASS_AUTH = "auth"
#: The credential was accepted and this account or client is not permitted. A new
#: credential for the same account does not help.
CLASS_PERMISSION = "permission"
#: Reached, permitted, and the subject named does not resolve to exactly one thing
#: that exists there -- absent, or ambiguous.
CLASS_NOT_FOUND = "not_found"
#: Reached, permitted, the subject exists, and this request was refused. Change the
#: arguments.
CLASS_REFUSED = "refused"
#: A bug in the tool. Nothing the caller did causes it and nothing it does fixes it.
CLASS_INTERNAL = "internal"
#: The fail-closed answer for a code the caller's table does not declare. Deliberately
#: not a member of :data:`CLASSES`: it is the absence of an answer, not an answer.
CLASS_UNCLASSIFIED = "unclassified"

#: Every class a reachable code may declare.
CLASSES = (
    CLASS_USAGE,
    CLASS_CONFIG,
    CLASS_TRANSPORT,
    CLASS_AUTH,
    CLASS_PERMISSION,
    CLASS_NOT_FOUND,
    CLASS_REFUSED,
    CLASS_INTERNAL,
)


def fault_class(code: str | None, codes: dict[str, str]) -> str:
    """The class ``codes`` declares for ``code``, or :data:`CLASS_UNCLASSIFIED`.

    Fails closed on an unknown code rather than guessing from the exception type it
    arrived on: the type is a coarser fact than the code -- one ``ConnectionFailed``
    is a missing Python package and another is a dropped socket -- and a guess that is
    usually right is exactly what a declared table exists to replace.
    """
    return codes.get(code or "", CLASS_UNCLASSIFIED)


# --------------------------------------------------------- the recovery vocabulary

#: Run a command this tool offers: ``Run `<tool> <args...>` <purpose>``.
KIND_RUN = "run"
#: Run the command that just failed again, with something added or changed.
KIND_RETRY = "retry"
#: Set an environment variable, which is the only channel a credential travels on.
KIND_SET_ENV = "set_env"
#: Offer a set of acceptable values: ``did you mean: a, b``.
KIND_CHOOSE = "choose"
#: Prose that is not a command. The one kind that may name the tool, and only through
#: :data:`TOOL_SLOT`.
KIND_NOTE = "note"

KINDS = (KIND_RUN, KIND_RETRY, KIND_SET_ENV, KIND_CHOOSE, KIND_NOTE)

#: The only placeholder a note may write. Substituted with the caller's own tool name.
TOOL_SLOT = "{tool}"

_DEFAULT_RUN_LEAD = "Run"
_DEFAULT_RETRY_LEAD = "Run the command again with"
_DEFAULT_SEPARATOR = " "

#: Fields each kind is allowed to set. Anything else is a construction error, so a
#: recovery written with the wrong keyword fails where it is written rather than
#: rendering as a shorter line than its author meant.
_ALLOWED: dict[str, frozenset] = {
    KIND_RUN: frozenset({"args", "purpose", "lead", "separator"}),
    KIND_RETRY: frozenset({"fragment", "purpose", "lead", "separator"}),
    KIND_SET_ENV: frozenset({"variable", "describes", "example", "reference"}),
    KIND_CHOOSE: frozenset({"label", "values"}),
    KIND_NOTE: frozenset({"fragment"}),
}

#: Any ``{...}`` other than the tool slot. A note is prose with exactly one hole in
#: it; a second placeholder means somebody is passing a template through, and the
#: value it wants belongs in a structured kind.
_FOREIGN_SLOT = re.compile(r"\{(?!tool\})[^}]*\}")


@dataclass(frozen=True)
class Recovery:
    """One suggested next step, as data.

    Construct through :func:`run`, :func:`retry`, :func:`set_env`, :func:`choose` or
    :func:`note` rather than directly -- they are the closed vocabulary, and they set
    the per-kind defaults that the renderers reproduce.
    """

    kind: str
    args: tuple = ()
    fragment: str = ""
    purpose: str = ""
    lead: str = ""
    separator: str = _DEFAULT_SEPARATOR
    variable: str = ""
    describes: str = ""
    example: str = ""
    reference: str = ""
    label: str = ""
    values: tuple = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown recovery kind: {self.kind!r}")
        allowed = _ALLOWED[self.kind]
        for name, empty in _OPTIONAL_DEFAULTS.items():
            if name in allowed:
                continue
            if getattr(self, name) != empty:
                raise ValueError(f"{self.kind} recovery cannot carry {name!r}")
        if self.kind == KIND_RUN and not self.args:
            raise ValueError("a run recovery names at least one argument")
        if self.kind == KIND_RETRY and not self.fragment:
            raise ValueError("a retry recovery names what to add")
        if self.kind == KIND_SET_ENV and not (self.variable and self.describes):
            raise ValueError("a set_env recovery names a variable and what to set it to")
        if self.kind == KIND_CHOOSE and not (self.label and self.values):
            raise ValueError("a choose recovery names a label and at least one value")
        if self.kind == KIND_NOTE:
            if not self.fragment:
                raise ValueError("a note recovery carries text")
            if _FOREIGN_SLOT.search(self.fragment):
                raise ValueError(
                    "a note may write {tool} and no other placeholder; "
                    f"found one in {self.fragment!r}"
                )

    # A note's prose is stored in ``fragment`` and read as ``text``: one slot, so
    # ``as_dict`` stays flat and a note round-trips through JSON like every other
    # kind, while the constructor and the renderers can still say what they mean.
    @property
    def text(self) -> str:
        return self.fragment

    def as_dict(self) -> dict:
        """A JSON-shaped dict carrying exactly the fields this kind uses."""
        out: dict = {"kind": self.kind}
        for name in sorted(_ALLOWED[self.kind]):
            value = getattr(self, name)
            if value == _OPTIONAL_DEFAULTS[name]:
                continue
            key = "text" if (self.kind == KIND_NOTE and name == "fragment") else name
            out[key] = list(value) if isinstance(value, tuple) else value
        return out

    @classmethod
    def from_dict(cls, data: dict) -> Recovery:
        """Rebuild a recovery from :meth:`as_dict`."""
        payload = dict(data)
        kind = payload.pop("kind", "")
        if "text" in payload:
            payload["fragment"] = payload.pop("text")
        for name in ("args", "values"):
            if name in payload:
                payload[name] = tuple(payload[name])
        return cls(kind=kind, **payload)

    def with_purpose(self, purpose: str) -> Recovery:
        """A copy carrying a different trailing clause."""
        return replace(self, purpose=purpose)


#: Every optional field and the value that means "not set". Read by ``__post_init__``
#: and ``as_dict`` so the per-kind rules stay a table rather than a chain of ifs.
_OPTIONAL_DEFAULTS: dict[str, Any] = {
    "args": (),
    "fragment": "",
    "purpose": "",
    "lead": "",
    "separator": _DEFAULT_SEPARATOR,
    "variable": "",
    "describes": "",
    "example": "",
    "reference": "",
    "label": "",
    "values": (),
}


def run(
    args: Iterable[str],
    *,
    purpose: str = "",
    lead: str = _DEFAULT_RUN_LEAD,
    separator: str = _DEFAULT_SEPARATOR,
) -> Recovery:
    """Run one of this tool's own commands.

    ``args`` are the words *after* the tool name, which is the whole point: the name
    is supplied by whoever renders this. ``lead`` is the clause before the command
    (``"Raise the limit with"`` is a real one) and ``separator`` is what joins the
    command to ``purpose`` -- a space usually, ``": "`` where the tool binds the
    explanation to the command with a colon.
    """
    return Recovery(
        kind=KIND_RUN,
        args=tuple(args),
        purpose=purpose,
        lead=lead,
        separator=separator,
    )


def retry(
    fragment: str,
    *,
    purpose: str = "",
    lead: str = _DEFAULT_RETRY_LEAD,
    separator: str = _DEFAULT_SEPARATOR,
) -> Recovery:
    """Run the command that just failed again, with ``fragment`` added or changed.

    Names no command, because the command is the one the caller just ran: the
    backticked fragment is a flag or a path, not an invocation.
    """
    return Recovery(
        kind=KIND_RETRY,
        fragment=fragment,
        purpose=purpose,
        lead=lead,
        separator=separator,
    )


def set_env(
    variable: str,
    describes: str,
    *,
    example: str = "",
    reference: str = "",
) -> Recovery:
    """Set an environment variable.

    ``example`` renders as ``, e.g. <example>`` and ``reference`` as
    ``; see <reference>`` -- the two spellings the source tools use, kept apart
    because one is a command to copy and the other is somewhere to read.
    """
    return Recovery(
        kind=KIND_SET_ENV,
        variable=variable,
        describes=describes,
        example=example,
        reference=reference,
    )


def choose(label: str, values: Iterable[str]) -> Recovery:
    """Offer the set of values that would have worked: ``did you mean: a, b``."""
    return Recovery(kind=KIND_CHOOSE, label=label, values=tuple(values))


def note(text: str) -> Recovery:
    """Prose that is not a command.

    The escape hatch, and the only kind that may name the tool -- as ``{tool}``, never
    as the name. ``"This is a bug in {tool}; the command did not complete"`` is a real
    one, and it is reusable by the sibling tool precisely because the name is a hole.
    """
    return Recovery(kind=KIND_NOTE, fragment=text)


def mentions_tool(recovery: Recovery) -> bool:
    """Whether rendering this recovery will name a tool at all.

    True for every :data:`KIND_RUN` (the command it names is one of the tool's own)
    and for a note that writes :data:`TOOL_SLOT`. A test uses it the other way round:
    a recovery for which this is false must render identically whatever tool name it
    is handed, and one for which it is true must render *differently* -- which is how
    "the name is not baked in" stops being a claim.
    """
    if recovery.kind == KIND_RUN:
        return True
    if recovery.kind == KIND_NOTE:
        return TOOL_SLOT in recovery.fragment
    return False


# --------------------------------------------------------------- the exceptions


class AxiError(Exception):
    """An error the agent should be able to read, understand and act on.

    ``recovery`` carries the specific next steps as data, per the AXI standard: on an
    error, suggest the fix rather than pointing at ``--help``. ``code`` is a literal
    from the owning tool's closed table -- always a literal, because a code built from
    whatever the server said (``f"HTTP_{status}"``) is vocabulary no caller can switch
    on and no table can ever complete.

    There is deliberately no ``help_lines``. Rendered lines are what
    :mod:`axi_toolkit.render` produces from ``recovery`` at the moment somebody knows
    which tool is asking.
    """

    exit_code = EXIT_ERROR

    def __init__(
        self,
        message: str,
        *,
        recovery: Iterable[Recovery] | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.recovery: tuple[Recovery, ...] = tuple(recovery or ())
        self.code = code

    def fault_class(self, codes: dict[str, str]) -> str:
        """The class ``codes`` declares for this error's code."""
        return fault_class(self.code, codes)

    def as_dict(self) -> dict:
        """The error as JSON-shaped data, recovery included and still unrendered."""
        return {
            "message": self.message,
            "code": self.code or "",
            "recovery": [item.as_dict() for item in self.recovery],
        }


class UsageError(AxiError):
    """A malformed invocation: unknown flag, missing argument, bad value."""

    exit_code = EXIT_USAGE


class ConfigError(AxiError):
    """Required environment configuration is missing or unusable."""


class ConnectionFailed(AxiError):
    """The system behind the tool could not be reached."""


class AuthFailed(AxiError):
    """The credential was rejected."""


class Forbidden(AxiError):
    """The credential was accepted and the caller was refused anyway.

    Deliberately neither an :class:`AuthFailed` nor an :class:`ApiError`. Not the
    former because a new credential for the same account does not help, and telling an
    agent to mint one sends it to fail a login against a system that may already have
    banned its address. Not the latter because a refusal that never reached the
    subject has nothing there to explain it.
    """


class NotFound(AxiError):
    """The requested subject does not resolve to one thing that exists."""


class ApiError(AxiError):
    """The system answered, and refused the request."""
