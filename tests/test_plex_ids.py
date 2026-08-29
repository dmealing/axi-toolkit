"""The identifier boundary: which `plex://` string may be printed, and which never.

``src/axi_toolkit/plex/ids.py`` is the tool's ``ids.py``, moved whole. One thing
changed, and it is the reason this move was not a copy: ``validate_rating_key``
took an ``invocation`` string that already began with the tool's name, and it now
takes ``command`` -- the words after it -- so the recovery it raises is intent and
the name arrives at the renderer. The conformance layer proves the rendered bytes
are the tool's own; what is below states the behaviour in this project's words.

**What came across.** The tool's ``tests/test_ids.py`` is 149 lines and ten test
functions. Six of them address the module and are here under "ported"; the other
four drive ``search``, ``track``, ``rate`` and ``playlist`` end to end against a
Plex double, and they test the command path rather than this module.

The rest is new. ``media_id_for``, ``handoff`` and ``stability_note`` were covered
only through the command path, so after the move they would have arrived with no
direct coverage at all -- which is the same ratio the Home Assistant half reported,
and the reason it is worth writing down twice.
"""

from __future__ import annotations

import pytest

from axi_toolkit.errors import TOOL_SLOT, UsageError, mentions_tool
from axi_toolkit.plex import ids
from axi_toolkit.render import cli

#: Obviously synthetic, and the right shape: a machineIdentifier is a long
#: hexadecimal string, and this module builds a URL out of it verbatim.
MACHINE_ID = "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"

#: A guid is a namespace and 24 hexadecimal characters. This one is invented.
CATALOGUE_GUID = "plex://track/a1b2c3d4e5f60718293a0100"


class Item:
    """What ``plexapi`` hands back, reduced to the two attributes read here."""

    def __init__(self, rating_key=311, guid=CATALOGUE_GUID):
        self.ratingKey = rating_key
        self.guid = guid


# ------------------------------------------------------------------- ported
#
# The six cases from the tool's own suite that address this module. Only the
# import path and the keyword that carries the caller's own command differ.


def test_the_content_id_names_the_server_as_well_as_the_item():
    """The canonical form, not the one a consumer calls legacy."""
    assert ids.media_content_id(MACHINE_ID, 311) == f"plex://{MACHINE_ID}/311"


def test_a_content_id_is_never_built_from_a_guid():
    """The `plex://track/<hex>` form raises inside a consumer rather than failing."""
    with pytest.raises(ValueError):
        ids.media_content_id(MACHINE_ID, "0000000000000000000000a1")


def test_a_content_id_needs_the_machine_identifier():
    with pytest.raises(ValueError):
        ids.media_content_id("", 311)


@pytest.mark.parametrize(
    "value",
    [
        CATALOGUE_GUID,
        "plex://0f0f0f0f/311",
        "plex://311",
        "not-a-key",
        "",
        "12a",
    ],
)
def test_only_a_decimal_rating_key_is_accepted(value):
    with pytest.raises(UsageError):
        ids.validate_rating_key(value, command=("track",))


def test_a_guid_is_rejected_by_name_rather_than_crashing():
    """The collision is real: a guid is a legitimate Plex identifier."""
    with pytest.raises(UsageError) as caught:
        ids.validate_rating_key(CATALOGUE_GUID, command=("track",))
    assert caught.value.code == "GUID_NOT_RATING_KEY"
    assert "guid" in caught.value.message


def test_a_media_id_is_rejected_with_the_field_that_carries_the_number():
    with pytest.raises(UsageError) as caught:
        ids.validate_rating_key("plex://abc/311", command=("track",))
    assert caught.value.code == "MEDIA_ID_NOT_RATING_KEY"


# ------------------------------------------------------------- the accepting path


@pytest.mark.parametrize(("raw", "expected"), [("311", "311"), ("  311  ", "311"), (311, "311")])
def test_a_rating_key_comes_back_as_the_bare_number(raw, expected):
    assert ids.validate_rating_key(raw, command=("track",)) == expected


# ---------------------------------------------------- the rows and the handoff
#
# New here. Both functions were reached only through commands in the tool, and
# both are about what happens when an item is *not* ideal -- which is the case a
# command-level test tends not to have a fixture for.


def test_a_row_without_a_usable_rating_key_is_a_null_cell_rather_than_a_failure():
    """A list row is not an error path.

    An item the server described without a usable rating key must render as a
    null cell -- not abort the command, and not fall back to some other
    ``plex://`` string that happens to be to hand.
    """
    assert ids.media_id_for(MACHINE_ID, Item(rating_key="")) is None
    assert ids.media_id_for(MACHINE_ID, Item(rating_key="a1b2c3d4e5f60718293a0100")) is None
    assert ids.media_id_for(MACHINE_ID, object()) is None


def test_a_row_without_a_machine_identifier_is_a_null_cell_too():
    assert ids.media_id_for("", Item()) is None


def test_a_row_with_both_gets_the_canonical_form():
    assert ids.media_id_for(MACHINE_ID, Item()) == f"plex://{MACHINE_ID}/311"


def test_the_handoff_is_four_labelled_fields_in_one_order():
    """The block is identifiers and nothing else, and the order is the contract."""
    block = ids.handoff(MACHINE_ID, Item())
    assert list(block) == ["media_id", "rating_key", "guid", "note"]
    assert block["media_id"] == f"plex://{MACHINE_ID}/311"
    assert block["rating_key"] == 311
    assert block["guid"] == CATALOGUE_GUID
    assert block["note"] == ids.STABILITY_NOTE


def test_the_handoff_refuses_rather_than_inventing_a_media_id():
    """An item with no rating key has no truthful media id, so there is no block."""
    with pytest.raises(ValueError):
        ids.handoff(MACHINE_ID, Item(rating_key=""))


# ------------------------------------------------------------ the stability note


def test_the_note_promises_durability_for_a_catalogue_guid():
    assert ids.stability_note(CATALOGUE_GUID) == ids.STABILITY_NOTE
    assert ids.stability_note() == ids.STABILITY_NOTE
    assert ids.stability_note("") == ids.STABILITY_NOTE


@pytest.mark.parametrize("guid", ["local://311", "  local://311  "])
def test_the_note_withdraws_the_promise_for_a_locally_matched_item(guid):
    """Form six: the guid is the rating key with a scheme in front of it.

    "Keep the guid, it survives" is false for these items, and it is at its most
    dangerous exactly where it is most likely to be believed -- someone pasting an
    identifier into a configuration file.
    """
    assert ids.stability_note(guid) == ids.LOCAL_STABILITY_NOTE
    assert "changes with it" in ids.LOCAL_STABILITY_NOTE


def test_the_handoff_carries_the_withdrawn_promise_for_a_local_guid():
    block = ids.handoff(MACHINE_ID, Item(guid="local://311"))
    assert block["note"] == ids.LOCAL_STABILITY_NOTE


# ---------------------------------------------------------- recovery is data
#
# The half of the move that was not mechanical. A recovery here is intent; the
# tool's name is put back by `render.cli` and is nowhere in what was raised.


def _raised(value, command=("track",)):
    with pytest.raises(UsageError) as caught:
        ids.validate_rating_key(value, command=command)
    return caught.value


@pytest.mark.parametrize(
    "value", [CATALOGUE_GUID, "local://311", "plex://0f0f0f0f/311", "not-a-key", ""]
)
def test_no_recovery_this_module_raises_stores_a_tool_name(value):
    """Rendered for two different tools, a recovery differs everywhere it names one.

    A line that reproduces the tool's own bytes by *carrying* its name is copied
    rather than extracted, and the rendered output alone cannot tell the two apart.
    """
    for item in _raised(value).recovery:
        assert "plex-axi" not in cli.line(item, "other-tool")
        if not mentions_tool(item):
            assert cli.line(item, "one") == cli.line(item, "another")


def test_the_command_a_caller_names_is_the_command_the_recovery_offers():
    """The words are the caller's; the name in front of them is the renderer's."""
    error = _raised("local://311", command=("playlist", "add", "'Example Playlist'"))
    assert cli.lines(error.recovery, "plex-axi")[1] == (
        "Run `plex-axi playlist add 'Example Playlist' 311`"
    )
    assert cli.lines(error.recovery, "other-tool")[1] == (
        "Run `other-tool playlist add 'Example Playlist' 311`"
    )


def test_the_local_guid_recovery_names_the_number_sitting_in_the_argument():
    """The one case where the answer is inside the argument rather than elsewhere."""
    assert cli.lines(_raised("local://311").recovery, "plex-axi")[1] == "Run `plex-axi track 311`"


def test_a_rendered_invocation_is_refused_rather_than_taken_apart():
    """``run`` would explode a string into its characters, and the line would look fine.

    Which is the whole danger: the tool passes ``"plex-axi track"`` today, and a
    silent per-character split would produce a plausible-looking recovery that no
    reader would question.
    """
    with pytest.raises(TypeError) as caught:
        ids.validate_rating_key("not-a-key", command="plex-axi track")
    assert "words after the tool name" in str(caught.value)


def test_a_command_with_no_words_is_refused():
    with pytest.raises(ValueError):
        ids.validate_rating_key("not-a-key", command=())


def test_no_recovery_writes_the_tool_slot_into_a_command():
    """The slot is the note's escape hatch, and this module needs none of it."""
    for value in (CATALOGUE_GUID, "local://311", "plex://0f0f0f0f/311", "not-a-key"):
        for item in _raised(value).recovery:
            assert TOOL_SLOT not in item.fragment
