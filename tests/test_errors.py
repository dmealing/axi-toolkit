"""The error contract, and the one property the whole extraction turns on.

Everything here is about recovery being data. The tools' copies of ``errors.py`` were
byte-identical apart from four docstrings, so copying the exception hierarchy is
mechanical and is tested lightly. What is not mechanical -- and what these tests are
mostly about -- is that a recovery cannot be written down with a tool's name in it,
cannot carry a field that belongs to another kind, and survives a round trip through
JSON so a caller that is not a CLI can act on it.
"""

from __future__ import annotations

import json

import pytest

from axi_core import errors
from axi_core.errors import (
    ApiError,
    AuthFailed,
    AxiError,
    ConfigError,
    ConnectionFailed,
    Forbidden,
    NotFound,
    Recovery,
    UsageError,
    choose,
    note,
    retry,
    run,
    set_env,
)

EVERY_KIND = (
    run(("area", "list"), purpose="to see the areas that exist"),
    run(("--timeout", "60", "<command>"), lead="Raise the limit with"),
    run(
        ("doctor",),
        purpose="a library that has not finished scanning has no metadata",
        separator=": ",
    ),
    retry("--limit 50"),
    retry("--path <dir>", lead="Pass a writable repository root with"),
    set_env("EXAMPLE_URL", "the base URL", example="export EXAMPLE_URL=https://host.example.com"),
    set_env("EXAMPLE_TOKEN", "an access token", reference="https://docs.example.com/tokens"),
    choose("did you mean", ("light.turn_on", "light.turn_off")),
    note("Retry the command; a dropped connection is often a one-off"),
    note("This is a bug in {tool}; the command did not complete"),
)


# ------------------------------------------------------------ recovery as data


def test_every_kind_survives_a_round_trip_through_json():
    """A recovery has to cross a process boundary intact to be worth calling data."""
    for original in EVERY_KIND:
        rebuilt = Recovery.from_dict(json.loads(json.dumps(original.as_dict())))
        assert rebuilt == original, original


def test_as_dict_carries_only_the_fields_the_kind_uses():
    """A dict full of empty slots is a shape, not a fact."""
    assert run(("doctor",)).as_dict() == {"kind": "run", "args": ["doctor"], "lead": "Run"}
    assert note("plain").as_dict() == {"kind": "note", "text": "plain"}


def test_a_kind_cannot_carry_another_kinds_field():
    """A mistyped recovery fails where it is written, not where it renders short."""
    with pytest.raises(ValueError, match="cannot carry 'args'"):
        Recovery(kind="note", fragment="text", args=("nope",))
    with pytest.raises(ValueError, match="cannot carry 'variable'"):
        Recovery(kind="run", args=("doctor",), variable="EXAMPLE_URL")


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown recovery kind"):
        Recovery(kind="incantation")


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: run(()), "at least one argument"),
        (lambda: retry(""), "names what to add"),
        (lambda: set_env("", "something"), "names a variable"),
        (lambda: set_env("VAR", ""), "names a variable"),
        (lambda: choose("did you mean", ()), "at least one value"),
        (lambda: note(""), "carries text"),
    ],
)
def test_an_empty_recovery_is_refused(factory, match):
    """An empty suggestion is worse than none: it occupies the slot that had the fix."""
    with pytest.raises(ValueError, match=match):
        factory()


def test_a_note_may_write_the_tool_slot_and_no_other_placeholder():
    """The one hole is the tool's name. A second means a template is being smuggled through."""
    assert note("A bug in {tool}").text == "A bug in {tool}"
    with pytest.raises(ValueError, match=r"\{tool\} and no other placeholder"):
        note("a {count} of things")


def test_mentions_tool_tells_the_two_sorts_of_recovery_apart():
    assert errors.mentions_tool(run(("doctor",)))
    assert errors.mentions_tool(note("a bug in {tool}"))
    assert not errors.mentions_tool(note("a dropped connection is often a one-off"))
    assert not errors.mentions_tool(retry("--limit 50"))
    assert not errors.mentions_tool(set_env("EXAMPLE_URL", "the base URL"))
    assert not errors.mentions_tool(choose("did you mean", ("a",)))


def test_with_purpose_leaves_the_original_alone():
    original = run(("doctor",))
    assert original.with_purpose("to test the connection").purpose == "to test the connection"
    assert original.purpose == ""


# ------------------------------------------------------------- fault classes


def test_a_declared_code_resolves_to_its_class():
    table = {"UNREACHABLE": errors.CLASS_TRANSPORT, "UNAUTHORIZED": errors.CLASS_AUTH}
    assert errors.fault_class("UNREACHABLE", table) == errors.CLASS_TRANSPORT
    assert errors.fault_class("UNAUTHORIZED", table) == errors.CLASS_AUTH


def test_an_unknown_code_fails_closed_rather_than_guessing():
    """Being visibly unclassified beats being quietly filed under the wrong class."""
    assert errors.fault_class("NEVER_DECLARED", {}) == errors.CLASS_UNCLASSIFIED
    assert errors.fault_class(None, {}) == errors.CLASS_UNCLASSIFIED


def test_unclassified_is_not_a_member_of_the_declared_classes():
    """It is the absence of an answer, so a table that offered it would be lying."""
    assert errors.CLASS_UNCLASSIFIED not in errors.CLASSES


def test_the_error_carries_its_own_class_lookup():
    table = {"TIMEOUT": errors.CLASS_TRANSPORT}
    raised = ConnectionFailed("it did not answer", code="TIMEOUT")
    assert raised.fault_class(table) == errors.CLASS_TRANSPORT


# ---------------------------------------------------------------- exceptions


def test_exit_codes_are_the_ones_both_tools_declare():
    assert (errors.EXIT_OK, errors.EXIT_ERROR, errors.EXIT_USAGE) == (0, 1, 2)


def test_only_a_usage_error_exits_two():
    """The distinction a shell caller acts on: bad invocation against everything else."""
    assert UsageError("bad flag").exit_code == errors.EXIT_USAGE
    for kind in (
        AxiError,
        ConfigError,
        ConnectionFailed,
        AuthFailed,
        Forbidden,
        NotFound,
        ApiError,
    ):
        assert kind("failed").exit_code == errors.EXIT_ERROR, kind


def test_forbidden_is_neither_an_auth_failure_nor_an_api_error():
    """A new credential for the same account does not help, so the class must differ."""
    raised = Forbidden("not permitted")
    assert not isinstance(raised, (AuthFailed, ApiError))
    assert isinstance(raised, AxiError)


def test_an_error_reports_itself_as_data_with_the_recovery_unrendered():
    raised = NotFound(
        "no area named 'nowhere'",
        code="NO_SUCH_AREA",
        recovery=[run(("area", "list"), purpose="to see the areas that exist")],
    )
    assert raised.as_dict() == {
        "message": "no area named 'nowhere'",
        "code": "NO_SUCH_AREA",
        "recovery": [
            {
                "kind": "run",
                "args": ["area", "list"],
                "lead": "Run",
                "purpose": "to see the areas that exist",
            }
        ],
    }


def test_an_error_with_no_recovery_carries_an_empty_tuple_not_none():
    raised = AxiError("something went wrong")
    assert raised.recovery == ()
    assert raised.as_dict()["recovery"] == []


def test_there_is_no_help_lines_attribute_to_fall_back_to():
    """The whole extraction turns on this: rendered lines are produced, never stored.

    A ``help_lines`` slot left in place for convenience would be taken, and the first
    caller to take it would bake a tool's name back into the error.
    """
    assert not hasattr(AxiError("x"), "help_lines")
