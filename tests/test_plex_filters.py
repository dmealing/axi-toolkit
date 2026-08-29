"""The music filter language: stars, fields, the one real inequality, dates, sorts.

``src/axi_toolkit/plex/filters.py`` is the pure half of the tool's ``music.py``.
Everything below is **new**, and the reason is the sharpest measurement this
extraction has produced: the tool's own suite has no direct test of any of these
functions at all. Every one of them is exercised through ``search``, ``pick`` and
``recent`` against a Plex double -- so the filter language arrived here with
nothing to port and nothing to inherit.

The Home Assistant half predicted this ratio and got it roughly right: four cases
of forty-five lines came across there, and none came across here.

What the conformance layer holds instead is the *comparison*: every scenario in
``plexFilterBehaviour`` is run against the tool's own copy and against this one,
and the two must answer identically. This file says what the answers mean.
"""

from __future__ import annotations

import pytest

from axi_toolkit.errors import TOOL_SLOT, AxiError, UsageError, mentions_tool
from axi_toolkit.plex import filters
from axi_toolkit.render import cli

# ------------------------------------------------------------------ stars
#
# Plex stores 0-10; everything printed and everything accepted is in stars, so a
# rating read out of one command can be passed straight into the next.


@pytest.mark.parametrize(
    ("points", "expected"),
    [(None, None), ("", None), (0, 0), (2, 1), (7, 3.5), (10, 5), ("10", 5)],
)
def test_a_plex_rating_reads_back_as_stars(points, expected):
    assert filters.stars(points) == expected


def test_an_unrated_item_is_null_rather_than_zero():
    """A number, so the output boundary prints it unquoted; ``None``, so an
    unrated item cannot be read as a zero rating."""
    assert filters.stars(None) is None
    assert filters.stars(0) == 0


def test_a_whole_number_of_stars_is_an_integer_and_a_half_is_not():
    assert isinstance(filters.stars(8), int)
    assert isinstance(filters.stars(7), float)


@pytest.mark.parametrize("raw", ["0", "0.5", "4", "4.5", "5", 3])
def test_a_rating_in_range_is_accepted_in_stars(raw):
    assert 0 <= filters.parse_stars(raw, flag="--rated-min") <= 5


@pytest.mark.parametrize("raw", ["6", "-1", "5.5"])
def test_a_rating_outside_the_scale_is_refused_in_stars_not_in_plex_points(raw):
    with pytest.raises(UsageError) as caught:
        filters.parse_stars(raw, flag="--rated-min")
    assert caught.value.code == "BAD_RATING"
    assert "stars from 0 to 5" in caught.value.message


@pytest.mark.parametrize("raw", ["high", None, "", "4 stars"])
def test_a_rating_that_is_not_a_number_is_refused_by_name(raw):
    with pytest.raises(UsageError) as caught:
        filters.parse_stars(raw, flag="--stars")
    assert caught.value.code == "BAD_RATING"
    assert "--stars" in caught.value.message


def test_the_refusal_names_the_flag_the_caller_typed():
    """The flag is an argument because two of them share this validator."""
    with pytest.raises(UsageError) as caught:
        filters.parse_stars("9", flag="--rated-min")
    assert cli.lines(caught.value.recovery, "plex-axi")[0] == (
        "Run the command again with `--rated-min 4`"
    )


# ------------------------------------------------------------- the field map


@pytest.mark.parametrize("libtype", filters.LIBTYPES)
def test_genre_and_style_resolve_against_the_artist_whatever_was_searched(libtype):
    """Plex hangs genres and styles off the artist, not off the track.

    A track-scoped genre filter returns nothing on a library tagged the ordinary
    way; ``artist.genre`` with ``libtype=track`` is Plex's own answer, and it
    returns the tracks of artists in that genre server-side, in one query.
    """
    assert filters.FIELD_MAP["genre"](libtype) == "artist.genre"
    assert filters.FIELD_MAP["style"](libtype) == "artist.style"


@pytest.mark.parametrize("libtype", filters.LIBTYPES)
def test_mood_scopes_to_whatever_was_searched(libtype):
    """Unlike genre, Plex's analysis writes moods at every level."""
    assert filters.FIELD_MAP["mood"](libtype) == f"{libtype}.mood"


def test_a_year_is_the_albums_year_even_on_a_track_search():
    assert filters.FIELD_MAP["year"]("track") == "album.year"


def test_every_flag_the_builder_reads_has_a_field():
    """The builder's flag list and the map are one vocabulary, not two."""
    filters_built, _, _ = filters.build_filters(
        dict.fromkeys(filters.FIELD_MAP, "Example Value"), "track"
    )
    assert len(filters_built) == len(filters.FIELD_MAP)


# ---------------------------------------------------------- the one inequality


def test_at_least_n_stars_is_written_as_greater_than_a_point_count():
    """Real Plex offers no "greater than or equals" for an integer at all.

    A music section advertises ``=``, ``!=``, ``>>=`` and ``<<=`` for the integer
    type, and both inequalities are strict. This flag was once built on the
    operator that does not exist, so it failed at every value on every real server
    while passing every test.
    """
    field, threshold, described = filters.rating_predicate("track", 4)
    assert field == "track.userRating>>"
    assert threshold == 7
    assert described == {
        "field": "track.userRating",
        "operator": filters.RATING_OPERATOR,
        "value": "7 (at least 4 stars)",
    }


def test_the_operator_echoed_back_is_the_predicate_that_ran():
    assert filters.RATING_OPERATOR == ">"


@pytest.mark.parametrize(
    ("stars_wanted", "threshold"), [(0.5, 0), (1, 1), (2, 3), (4, 7), (4.25, 8), (5, 9)]
)
def test_a_value_between_the_half_stars_plex_stores_rounds_the_way_it_was_meant(
    stars_wanted, threshold
):
    """``ceil(points) - 1``, not ``points - 1``.

    4.25 stars is 8.5 points, and the largest rating that is *not* at least that
    is 8, not 7.5 -- and a fractional threshold in the URL is a number the integer
    field would have to guess at.
    """
    assert filters.rating_predicate("track", stars_wanted)[1] == threshold


def test_a_rating_predicate_scopes_to_the_libtype_searched():
    assert filters.rating_predicate("album", 3)[0] == "album.userRating>>"


@pytest.mark.parametrize("value", [0, 0.0, -1])
def test_no_minimum_is_no_predicate_rather_than_a_vacuous_one(value):
    """``--rated-min 0`` is the bottom of the scale, so it constrains nothing.

    The alternative -- ``userRating > -1`` -- would quietly mean "rated at all",
    which on an ordinary library withholds most of it behind a flag that reads as
    "no minimum". "Rated at all" already has an exact spelling: ``0.5``.
    """
    assert filters.rating_predicate("track", value) == (None, None, None)


# --------------------------------------------------------------- build_filters


def test_nothing_asked_for_builds_nothing():
    assert filters.build_filters({}, "track") == ({}, [], "")


def test_a_blank_flag_is_not_a_filter():
    """An absent flag and an empty one mean the same thing: no predicate."""
    built, described, note = filters.build_filters(
        {"artist": "", "album": None, "track": "Example Track"}, "track"
    )
    assert built == {"track.title": "Example Track"}
    assert len(described) == 1
    assert note == ""


def test_every_filter_is_echoed_with_three_keys_in_one_order():
    """The echo is a promise about the request, so it cannot vary by code path."""
    _, described, _ = filters.build_filters({"artist": "Example Artist"}, "track")
    assert [list(row) for row in described] == [["field", "operator", "value"]]
    assert described[0]["operator"] == filters.BARE_OPERATOR


def test_a_rating_minimum_joins_the_filters_and_the_echo():
    built, described, note = filters.build_filters(
        {"artist": "Example Artist", "rated_min": "4"}, "track"
    )
    assert built == {"artist.title": "Example Artist", "track.userRating>>": 7}
    assert [row["field"] for row in described] == ["artist.title", "track.userRating"]
    assert note == ""


def test_a_vacuous_minimum_is_reported_rather_than_applied_silently():
    built, described, note = filters.build_filters({"rated_min": "0"}, "track")
    assert built == {}
    assert described == []
    assert note == filters.RATED_MIN_ZERO_NOTE
    assert "0.5" in note, "the note has to name the spelling that does mean 'rated at all'"


def test_the_vacuous_note_names_a_flag_and_never_a_tool():
    """It is a field of a successful answer, not a recovery, and it stays a string.

    Nothing in it belongs to one tool: a flag is the tool's own surface either way,
    and there is no tool *name* in it to bake in.
    """
    assert "axi" not in filters.RATED_MIN_ZERO_NOTE


def test_a_bad_rating_minimum_fails_the_whole_build():
    with pytest.raises(UsageError):
        filters.build_filters({"rated_min": "nine"}, "track")


def test_the_described_rows_are_mutable_because_the_operator_is_rewritten_later():
    """The probing layer replaces ``=`` with the title the server advertises."""
    _, described, _ = filters.build_filters({"artist": "Example Artist"}, "track")
    described[0]["operator"] = "contains"
    assert described[0]["operator"] == "contains"


# ----------------------------------------------------- the client-side refusal


def test_a_clean_search_is_not_refused():
    assert filters.assert_server_side({}) is None


def test_a_filter_the_server_never_saw_is_refused_rather_than_applied():
    """Anything left after the key is built is a PlexAPI operator, not a Plex one.

    plexapi applies it in Python after the server has already sliced the result
    set, so it fights the limit instead of narrowing the query -- and it looks
    like it worked.
    """
    with pytest.raises(AxiError) as caught:
        filters.assert_server_side({"viewCount__gt": 1, "userRating__gte": 8})
    assert caught.value.code == "CLIENT_SIDE_FILTER"
    assert "userRating__gte, viewCount__gt" in caught.value.message


def test_the_refusal_says_whose_bug_it_is_without_saying_whose_tool_it_is():
    """The one recovery here that names a tool, and it names it as a slot."""
    with pytest.raises(AxiError) as caught:
        filters.assert_server_side({"userRating__gte": 8})
    assert [item.fragment for item in caught.value.recovery] == [
        "This is a bug in {tool}: every filter must be a server-side Plex predicate",
        "Report it at https://github.com/dmealing/{tool}/issues",
    ]
    assert cli.lines(caught.value.recovery, "plex-axi") == [
        "This is a bug in plex-axi: every filter must be a server-side Plex predicate",
        "Report it at https://github.com/dmealing/plex-axi/issues",
    ]


# ------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30d", "30d"),
        ("-30d", "30d"),
        ("  30d  ", "30d"),
        ("6mon", "6mon"),
        ("2y", "2y"),
        ("90s", "90s"),
        ("2024-01-31", "2024-01-31"),
    ],
)
def test_a_period_or_a_date_is_accepted_and_the_sign_is_left_to_plexapi(raw, expected):
    """plexapi normalises a bare ``30d`` to ``-30d``; "30d ago" is how a caller says it."""
    assert filters.parse_relative_date(raw, flag="--since") == expected


@pytest.mark.parametrize("raw", ["last week", "30x", "2024-1-31", "", "d30"])
def test_a_malformed_period_is_refused_before_the_client_library_sees_it(raw):
    """plexapi answers one with a message about its own field key rather than the flag."""
    with pytest.raises(UsageError) as caught:
        filters.parse_relative_date(raw, flag="--since")
    assert caught.value.code == "BAD_PERIOD"
    assert "--since" in caught.value.message


def test_the_period_refusal_lists_the_units_that_do_work():
    with pytest.raises(UsageError) as caught:
        filters.parse_relative_date("last week", flag="--since")
    assert cli.lines(caught.value.recovery, "plex-axi") == [
        "Run the command again with `--since 30d`",
        "units: s seconds, m minutes, h hours, d days, w weeks, mon months, y years",
    ]


# ------------------------------------------------------------------- sorts


@pytest.mark.parametrize("raw", [None, ""])
def test_no_sort_is_no_sort(raw):
    assert filters.parse_sort(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("addedAt", "addedAt"),
        ("addedAt:desc", "addedAt:desc"),
        ("addedAt:DESC", "addedAt:desc"),
        ("  addedAt:asc  ", "addedAt:asc"),
        ("artist.titleSort,album.year:desc", "artist.titleSort,album.year:desc"),
    ],
)
def test_a_direction_is_normalised_and_a_bare_field_is_left_alone(raw, expected):
    """The field half is the server's to validate; only the direction is fixed here."""
    assert filters.parse_sort(raw) == expected


def test_the_field_is_taken_from_the_last_colon_not_the_first():
    """A real Plex sort key may be a comma-joined list of scoped fields."""
    assert (
        filters.parse_sort("artist.titleSort,album.year:asc") == "artist.titleSort,album.year:asc"
    )


def test_an_unknown_direction_is_a_usage_error_rather_than_a_404_on_the_results():
    """It reached the server untouched before, and Plex answers it with a 404.

    Which arrived as "the search results was not found on this server": a sentence
    about the library, exit code 1, for what is a typo in an argument.
    """
    with pytest.raises(UsageError) as caught:
        filters.parse_sort("addedAt:sideways")
    assert caught.value.code == "BAD_SORT"
    assert "asc or desc" in caught.value.message


def test_a_direction_with_no_field_says_which_half_is_missing():
    with pytest.raises(UsageError) as caught:
        filters.parse_sort(":desc")
    assert caught.value.code == "BAD_SORT"
    assert cli.lines(caught.value.recovery, "plex-axi")[0] == (
        "Run the command again with `--sort addedAt:desc`"
    )


def test_the_sort_refusal_offers_the_field_the_caller_actually_typed():
    with pytest.raises(UsageError) as caught:
        filters.parse_sort("addedAt:sideways")
    assert cli.lines(caught.value.recovery, "plex-axi")[0] == (
        "Run the command again with `--sort addedAt:desc`"
    )


# ------------------------------------------------------------ recovery is data

#: Every way this module refuses, as ``() -> None`` thunks. Written out rather
#: than discovered, because a sweep that found nothing would pass.
_REFUSALS = (
    lambda: filters.parse_stars("high", flag="--rated-min"),
    lambda: filters.parse_stars("6", flag="--stars"),
    lambda: filters.build_filters({"rated_min": "nine"}, "track"),
    lambda: filters.assert_server_side({"userRating__gte": 8}),
    lambda: filters.parse_relative_date("last week", flag="--since"),
    lambda: filters.parse_sort(":desc"),
    lambda: filters.parse_sort("addedAt:sideways"),
)


@pytest.mark.parametrize("refuse", _REFUSALS)
def test_no_recovery_this_module_raises_stores_a_tool_name(refuse):
    """A recovery that reproduced the tool's line by carrying its name is a copy.

    The rendered output cannot tell that apart from an extraction, so the intent is
    rendered a second time under another name and must not still say ``plex-axi``.
    """
    with pytest.raises(AxiError) as caught:
        refuse()
    for item in caught.value.recovery:
        assert "plex-axi" not in cli.line(item, "other-tool")
        if not mentions_tool(item):
            assert cli.line(item, "one") == cli.line(item, "another")


@pytest.mark.parametrize("refuse", _REFUSALS)
def test_every_refusal_carries_at_least_one_next_step(refuse):
    """On an error, suggest the fix rather than pointing at --help."""
    with pytest.raises(AxiError) as caught:
        refuse()
    assert caught.value.recovery
    assert all(cli.line(item, "plex-axi").strip() for item in caught.value.recovery)


def test_only_the_bug_report_writes_the_tool_slot():
    """The slot is the note's escape hatch; a refusal about an argument needs none."""
    with_slot = []
    for refuse in _REFUSALS:
        with pytest.raises(AxiError) as caught:
            refuse()
        with_slot.extend(
            item for item in caught.value.recovery if TOOL_SLOT in (item.fragment or "")
        )
    assert len(with_slot) == 2, "only the client-side-filter refusal names the tool at all"
