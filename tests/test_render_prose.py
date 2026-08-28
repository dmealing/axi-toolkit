"""The prose renderer: the same intent, for a caller that will never run a shell.

Two properties matter and the rest is wording. Every sentence names the tool it is
handed, so a caller embedding this package speaks as itself rather than as whichever
tool the error came from; and no sentence hands over a shell line the caller cannot
run, because a caller given one will claim it ran it.
"""

from __future__ import annotations

import pytest

from axi_toolkit.errors import choose, note, retry, run, set_env
from axi_toolkit.render import cli, prose

TOOL = "ha-axi"


@pytest.mark.parametrize(
    ("recovery", "expected"),
    [
        (run(("area", "list")), "Use ha-axi's `area list` command."),
        (
            run(("area", "list"), purpose="to see each area's id"),
            "To see each area's id, use ha-axi's `area list` command.",
        ),
        (
            run(("--timeout", "60", "<command>"), lead="Raise the limit with"),
            "Raise the limit with ha-axi's `--timeout 60 <command>`.",
        ),
        (
            retry("--limit 50"),
            "Run the same ha-axi command again with `--limit 50`.",
        ),
        (
            retry("--path <dir>", lead="Pass a writable repository root with"),
            "Pass a writable repository root with `--path <dir>`, then run it again with ha-axi.",
        ),
        (
            set_env("HA_URL", "your Home Assistant base URL"),
            "ha-axi reads HA_URL from the environment: set it to your Home Assistant base URL.",
        ),
        (
            set_env("HA_URL", "your base URL", example="export HA_URL=https://host.example.com"),
            "ha-axi reads HA_URL from the environment: set it to your base URL, "
            "e.g. export HA_URL=https://host.example.com.",
        ),
        (
            set_env(
                "PLEX_TOKEN", "an access token", reference="https://support.example.com/tokens"
            ),
            "ha-axi reads PLEX_TOKEN from the environment: set it to an access token; "
            "see https://support.example.com/tokens.",
        ),
        (
            choose("did you mean", ("light.turn_on", "light.turn_off")),
            "Did you mean: light.turn_on, light.turn_off.",
        ),
        (
            note("This is a bug in {tool}; the command did not complete"),
            "This is a bug in ha-axi; the command did not complete.",
        ),
        (
            note("Retry the command; a dropped connection is often a one-off"),
            "Retry the command; a dropped connection is often a one-off.",
        ),
    ],
)
def test_each_kind_becomes_a_sentence(recovery, expected):
    assert prose.sentence(recovery, TOOL) == expected


def test_sentences_renders_a_whole_block_in_order():
    block = (run(("doctor",)), note("Then look at the log"))
    assert prose.sentences(block, TOOL) == [
        "Use ha-axi's `doctor` command.",
        "Then look at the log.",
    ]


def test_an_author_who_ended_the_sentence_is_not_given_a_second_full_stop():
    assert prose.sentence(note("Nothing was sent to the server."), TOOL).endswith("server.")
    assert not prose.sentence(note("Nothing was sent."), TOOL).endswith("..")


def test_a_question_or_a_colon_also_counts_as_ended():
    assert prose.sentence(note("Which of these did you mean?"), TOOL).endswith("?")
    assert prose.sentence(note("Two things are wrong here:"), TOOL).endswith(":")


def test_capitalising_a_purpose_leaves_the_rest_of_it_alone():
    """`str.capitalize` would turn HA_URL into ha_url and a proper noun into a common one."""
    rendered = prose.sentence(
        run(("doctor",), purpose="to check HA_URL reaches Home Assistant"), TOOL
    )
    assert rendered == "To check HA_URL reaches Home Assistant, use ha-axi's `doctor` command."


def test_the_shell_separator_is_not_carried_into_prose():
    """A colon that bound an explanation to a command reads as a stray one in a sentence."""
    recovery = run(("doctor",), purpose="the library has not finished scanning", separator=": ")
    assert cli.line(recovery, TOOL).endswith("`: the library has not finished scanning")
    assert prose.sentence(recovery, TOOL) == (
        "The library has not finished scanning, use ha-axi's `doctor` command."
    )


def test_prose_never_offers_a_command_line_the_caller_cannot_run():
    """No sentence starts with the imperative a shell user reads as copy-and-paste."""
    for recovery in (run(("doctor",)), retry("--limit 50"), set_env("HA_URL", "a URL")):
        rendered = prose.sentence(recovery, TOOL)
        assert not rendered.startswith("Run `")
        assert f"`{TOOL} " not in rendered


@pytest.mark.parametrize(
    "recovery",
    [
        run(("doctor",)),
        retry("--limit 50"),
        set_env("HA_URL", "a URL"),
        note("A bug in {tool}"),
    ],
)
def test_every_sentence_names_the_tool_it_is_handed(recovery):
    assert "plex-axi" in prose.sentence(recovery, "plex-axi")
    assert "plex-axi" not in prose.sentence(recovery, "ha-axi")


def test_a_choice_names_no_tool_because_the_values_are_not_the_tools():
    """The one deliberate exception: these are the system's vocabulary, not the tool's."""
    rendered = prose.sentence(choose("did you mean", ("a", "b")), TOOL)
    assert TOOL not in rendered
