"""The shell renderer, pinned to the bytes the two source tools print today.

The corpus check -- every literal recovery line either tool emits, round-tripped byte
for byte -- is generated, because the corpus is a captured fact and belongs in
``capture.json`` rather than in a list somebody typed. What is here is the other half:
each rendering rule stated once, in the open, so a reader can see what the renderer
does without reconstructing it from 232 examples, and so the renderer is pinned
independently of the parser that feeds the corpus check.

The last group is the property the extraction exists for. A recovery renders with the
caller's tool name and nobody else's, and a recovery that names no tool renders the
same whoever asks.
"""

from __future__ import annotations

import pytest

from axi_core.errors import choose, note, retry, run, set_env
from axi_core.render import cli

TOOL = "ha-axi"


# ------------------------------------------------------------------ rendering


@pytest.mark.parametrize(
    ("recovery", "expected"),
    [
        (run(("doctor",)), "Run `ha-axi doctor`"),
        (
            run(("area", "list"), purpose="to see each area's id"),
            "Run `ha-axi area list` to see each area's id",
        ),
        (
            run(("--help",), purpose="for the full reference"),
            "Run `ha-axi --help` for the full reference",
        ),
        (
            run(("--timeout", "60", "<command>"), lead="Raise the limit with"),
            "Raise the limit with `ha-axi --timeout 60 <command>`",
        ),
        (
            run(
                ("doctor",),
                purpose="a library that has not finished scanning has no metadata",
                separator=": ",
            ),
            "Run `ha-axi doctor`: a library that has not finished scanning has no metadata",
        ),
        (retry("--limit 50"), "Run the command again with `--limit 50`"),
        (
            retry("--debug", purpose="for a diagnostic trace on stderr", lead="Re-run with"),
            "Re-run with `--debug` for a diagnostic trace on stderr",
        ),
        (
            set_env(
                "HA_URL",
                "your Home Assistant base URL",
                example="export HA_URL=https://host.example.com",
            ),
            "Set HA_URL to your Home Assistant base URL, e.g. export HA_URL=https://host.example.com",
        ),
        (
            set_env(
                "PLEX_TOKEN", "a Plex access token", reference="https://support.example.com/tokens"
            ),
            "Set PLEX_TOKEN to a Plex access token; see https://support.example.com/tokens",
        ),
        (
            set_env("HA_TOKEN", "a long-lived access token"),
            "Set HA_TOKEN to a long-lived access token",
        ),
        (
            choose("did you mean", ("light.turn_on", "light.turn_off")),
            "did you mean: light.turn_on, light.turn_off",
        ),
        (
            note("Retry the command; a dropped connection is often a one-off"),
            "Retry the command; a dropped connection is often a one-off",
        ),
        (
            note("This is a bug in {tool}; the command did not complete"),
            "This is a bug in ha-axi; the command did not complete",
        ),
        (
            note("usage: {tool} [command] [subcommand] [args] [flags]"),
            "usage: ha-axi [command] [subcommand] [args] [flags]",
        ),
    ],
)
def test_each_rule_renders_the_line_the_tools_print(recovery, expected):
    assert cli.line(recovery, TOOL) == expected


def test_lines_renders_a_whole_recovery_block_in_order():
    block = (run(("doctor",)), note("and then look at the log"))
    assert cli.lines(block, TOOL) == ["Run `ha-axi doctor`", "and then look at the log"]


def test_a_non_default_separator_survives_an_empty_purpose():
    """A line ending in bare punctuation round-trips; the separator carries it."""
    assert cli.line(run(("doctor",), separator="."), TOOL) == "Run `ha-axi doctor`."


# --------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Run `ha-axi area list` to see each area's id", "run"),
        ("Raise the limit with `ha-axi --timeout 60 <command>`", "run"),
        ("Every local client still works without it: run `ha-axi clients`", "run"),
        ("Run the command again with `--limit 50`", "retry"),
        ("Pass a writable repository root with `--path <dir>`", "retry"),
        ("Set HA_URL to your base URL, e.g. export HA_URL=https://host.example.com", "set_env"),
        ("Retry the command; a dropped connection is often a one-off", "note"),
        ("usage: ha-axi [command] [subcommand] [args] [flags]", "note"),
    ],
)
def test_a_line_parses_to_the_kind_that_describes_it(text, kind):
    assert cli.parse(text, TOOL).kind == kind


def test_parsing_and_rendering_are_inverses():
    lines = [
        "Run `ha-axi area list` to see each area's id",
        "Run `ha-axi doctor`",
        "Raise the limit with `ha-axi --timeout 60 <command>`",
        "Run the command again with `--limit 50`",
        "Set HA_TOKEN to a long-lived access token",
        "Retry the command; a dropped connection is often a one-off",
    ]
    assert [cli.line(cli.parse(text, TOOL), TOOL) for text in lines] == lines


def test_a_line_naming_the_tool_outside_its_command_becomes_a_note_with_a_slot():
    """Two invocations in one line cannot be one `run`, and must not bake in a name."""
    text = "Run `ha-axi rate --help` or `ha-axi playlist --help` for the writes on offer"
    parsed = cli.parse(text, TOOL)
    assert parsed.kind == "note"
    assert "ha-axi" not in parsed.text
    assert parsed.text.count("{tool}") == 2
    assert cli.line(parsed, TOOL) == text


def test_a_backticked_fragment_that_embeds_the_tool_name_becomes_a_note():
    text = "Install it with `pip install 'ha-axi'` or `pip install websockets`"
    parsed = cli.parse(text, TOOL)
    assert parsed.kind == "note"
    assert "ha-axi" not in parsed.text
    assert cli.line(parsed, TOOL) == text


def test_prose_with_no_structure_still_becomes_something_renderable():
    assert cli.parse("`--flag` at the very start", TOOL).kind == "note"
    assert cli.parse("units: s seconds, m minutes, h hours", TOOL).kind == "note"


def test_an_empty_line_is_refused_rather_than_becoming_an_empty_note():
    """An empty suggestion occupies the slot that should have carried the fix."""
    with pytest.raises(ValueError, match="not a recovery"):
        cli.parse("   ", TOOL)


def test_parse_all_keeps_order():
    texts = ["Run `ha-axi doctor`", "and then look at the log"]
    assert [item.kind for item in cli.parse_all(texts, TOOL)] == ["run", "note"]


# --------------------------------------------- the tool's name is never stored


@pytest.mark.parametrize(
    "recovery",
    [
        retry("--limit 50"),
        set_env("HA_URL", "your base URL"),
        choose("did you mean", ("a", "b")),
        note("Retry the command; a dropped connection is often a one-off"),
    ],
)
def test_a_recovery_that_names_no_tool_renders_the_same_for_any_tool(recovery):
    assert cli.line(recovery, "ha-axi") == cli.line(recovery, "some-other-axi")


@pytest.mark.parametrize(
    "recovery",
    [run(("doctor",), purpose="to test the connection"), note("This is a bug in {tool}")],
)
def test_a_recovery_that_names_a_tool_names_the_one_it_is_handed(recovery):
    """The whole point: the same intent belongs to whichever tool renders it."""
    mine = cli.line(recovery, "ha-axi")
    theirs = cli.line(recovery, "plex-axi")
    assert mine != theirs
    assert "plex-axi" not in mine
    assert "ha-axi" not in theirs
