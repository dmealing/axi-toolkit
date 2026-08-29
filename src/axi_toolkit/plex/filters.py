"""The music filter language: stars, fields, operators, dates and sorts.

The pure half of a Plex music search. Everything here takes plain values --
a flag's raw argument, a libtype, a dictionary of parsed flags -- and returns
plain values or raises. Nothing takes a ``server`` or a ``section``, and nothing
imports ``plexapi``; the probing layer that reads a section's advertised fields
and the layer that classifies ``plexapi``'s exceptions are the tool's, and stay
there.

Two decisions carried across from the tool are the difference between a music
search and a search that merely returns music-shaped rows:

**Filters, not keyword arguments.** A numeric predicate written as
``userRating__gte=8`` means three different things depending on how it is
reached: through ``Library.search`` it is emitted verbatim into the URL and
applied nowhere; through ``LibrarySection.search`` it becomes a *client-side*
post-filter applied after ``limit`` has already sliced the results; and only
through ``filters={"userRating>>": 7}`` is it a real, server-validated Plex
predicate over the whole set. :func:`build_filters` produces only the third
form, and :func:`assert_server_side` fails loudly if a client-side filter ever
sneaks back in.

And the operator in that third form is not a free choice either. ``>>`` is
Plex's "is greater than" and it is the *only* inequality a real music section
offers for an integer -- the ``>=`` that looks like the natural spelling of "at
least" is not defined for any type, so "at least four stars" is written as
"greater than seven points". See :data:`RATING_OPERATOR`.

**Recovery is data here, and was a rendered line in the tool.** Every
``help_lines`` entry became a :class:`~axi_toolkit.errors.Recovery`; the tool's
name arrives at :mod:`axi_toolkit.render.cli`, and the conformance layer proves
the bytes are the ones the tool prints today rather than asserting it.
"""

from __future__ import annotations

import math
import re

from ..errors import AxiError, UsageError, note, retry

__all__ = [
    "ABSOLUTE_DATE",
    "BARE_OPERATOR",
    "FIELD_MAP",
    "LIBTYPES",
    "POINTS_PER_STAR",
    "RATED_MIN_ZERO_NOTE",
    "RATING_OPERATOR",
    "RELATIVE_DATE",
    "SORT_DIRECTIONS",
    "assert_server_side",
    "build_filters",
    "describe_filter",
    "parse_relative_date",
    "parse_sort",
    "parse_stars",
    "rating_predicate",
    "stars",
]

#: The three libtypes a music library holds, in the order they are listed.
LIBTYPES = ("track", "album", "artist")

#: Plex stores a user rating as 0-10; a star is two points. Every rating a tool
#: built on this prints and every rating it accepts is in stars, so that a rating
#: read out of one command can be passed straight into `--rated-min` on the next.
POINTS_PER_STAR = 2


def stars(user_rating):
    """A Plex 0-10 user rating as 0-5 stars, or ``None`` when it is unrated.

    Returned as a number rather than a formatted string so the output boundary
    prints it unquoted, and so an unrated item reads as ``null`` rather than as
    an empty cell that could be mistaken for a zero rating.
    """
    if user_rating in (None, ""):
        return None
    value = float(user_rating) / POINTS_PER_STAR
    return int(value) if value.is_integer() else value


# ------------------------------------------------------------------- filters


#: Which Plex field each search flag maps to, per libtype searched.
#:
#: Two of these are scoping decisions rather than translations, and both are
#: load-bearing:
#:
#: * **genre and style resolve against the artist.** In a Plex music library
#:   genres and styles are carried by the artist, not by the track; a
#:   track-scoped genre filter returns nothing on a library tagged the ordinary
#:   way. Scoping to `artist.genre` with `libtype=track` is Plex's own answer --
#:   it returns the tracks of artists in that genre, server-side, in one query.
#: * **mood scopes to whatever was searched.** Unlike genre, Plex's analysis
#:   writes moods at every level, so `--mood` on a track search means the
#:   track's own mood and on an artist search the artist's.
#:
#: Any field may be combined with any libtype: Plex resolves `track.title` on an
#: artist search as "artists having a track by that name", which is a real and
#: useful query rather than an error.
FIELD_MAP = {
    "artist": lambda libtype: "artist.title",
    "album": lambda libtype: "album.title",
    "track": lambda libtype: "track.title",
    "genre": lambda libtype: "artist.genre",
    "style": lambda libtype: "artist.style",
    "mood": lambda libtype: f"{libtype}.mood",
    "year": lambda libtype: "album.year",
}

#: The operator each filter carries on the wire. A field given without a suffix
#: normalises to ``=``, and what ``=`` *means* is a property of the field's
#: type: "contains" on a string, "is" on a tag or an integer. The label printed
#: back is therefore read from the section's own operator table by the probing
#: layer rather than guessed once for all fields here.
BARE_OPERATOR = "="

#: What ``--rated-min`` prints back. Not ``>=``: **real Plex offers no
#: "greater than or equals" for an integer at all.** A music section advertises
#: exactly ``=``, ``!=``, ``>>=`` and ``<<=`` for the integer type, and both
#: inequalities are *strict* -- ``>>=`` is "is greater than", ``<<=`` is "is less
#: than". The ``<=``/``>=`` that appear under the *string* type are Plex's
#: "begins with" and "ends with", which is how they came to look like numeric
#: comparisons.
#:
#: This flag was built on the one that does not exist, so it failed at every
#: value on every real server while passing every test in the tool. "At least N
#: stars" is therefore ``userRating > (2N - 1)``, and ``>`` is what is printed
#: back because it is what the predicate actually is.
RATING_OPERATOR = ">"

#: What ``--rated-min 0`` means, said out loud rather than decided silently.
#:
#: Zero is the bottom of the scale, so it constrains nothing, and that is the
#: reading taken here. The alternative -- ``userRating > -1`` -- would quietly
#: mean "rated at all", which on an ordinary library withholds the overwhelming
#: majority of it behind a flag that reads as "no minimum". And "rated at all"
#: already has an exact spelling: ``--rated-min 0.5`` is ``userRating > 0``.
#: Given one spelling for each idea, the vacuous reading is the one worth
#: keeping for the vacuous value.
#:
#: It stays a string rather than becoming a :class:`~axi_toolkit.errors.Recovery`
#: because it is not one: :func:`build_filters` hands it back as a field of a
#: *successful* answer, printed in the document rather than beside an error, and
#: it names a flag rather than a tool -- so there is no name in it to bake in.
RATED_MIN_ZERO_NOTE = (
    "--rated-min 0 is the bottom of the scale, so no rating filter was applied: "
    "this is every item, rated or not. Run `--rated-min 0.5` for the rated ones"
)


def describe_filter(field: str, operator: str, value: str) -> dict:
    """One echoed filter: the predicate that ran, in the caller's terms.

    Several of these are built across a tool's commands, and every one of them
    is these three keys in this order -- the echo is a promise about the
    request, so a row that gained a fourth key on one path and not another would
    make it a promise about one code path instead. The probing layer rewrites
    the operator in place afterwards with the title the server itself
    advertises, so this hands back a plain mutable dict rather than anything
    tidier.
    """
    return {"field": field, "operator": operator, "value": value}


def parse_stars(raw, *, flag: str) -> float:
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        raise UsageError(
            f"{flag} needs a rating in stars from 0 to 5, got {raw!r}",
            recovery=(retry(f"{flag} 4"),),
            code="BAD_RATING",
        ) from None
    if not 0 <= value <= 5:
        raise UsageError(
            f"{flag} is in stars from 0 to 5, got {value:g}",
            recovery=(
                retry(f"{flag} 4"),
                note(
                    "Ratings print in stars too, so a rating read from a result can be passed back"
                ),
            ),
            code="BAD_RATING",
        )
    return value


def rating_predicate(libtype: str, value: float) -> tuple:
    """The Plex predicate for "at least ``value`` stars", and how to echo it.

    Returns ``(field, threshold, described)``, or three ``None``s when the
    request imposes no constraint -- see :data:`RATED_MIN_ZERO_NOTE`.

    The threshold is ``ceil(points) - 1`` rather than ``points - 1`` so that a
    value between the half-stars Plex can store rounds the way the caller meant:
    4.25 stars is 8.5 points, and the largest rating that is *not* at least that
    is 8, not 7.5 -- and a fractional threshold in the URL is a number the
    integer field would have to guess at.
    """
    if value <= 0:
        return None, None, None
    threshold = math.ceil(value * POINTS_PER_STAR) - 1
    return (
        f"{libtype}.userRating>>",
        threshold,
        describe_filter(
            f"{libtype}.userRating",
            RATING_OPERATOR,
            f"{threshold} (at least {value:g} star{'' if value == 1 else 's'})",
        ),
    )


def build_filters(parsed, libtype: str) -> tuple:
    """Turn the per-field flags into Plex filters, and describe what was applied.

    Returns ``(filters, described, note)`` where ``filters`` is the dictionary
    handed to ``MusicSection.search``, ``described`` is the rows printed back so
    the caller can see the actual predicate rather than guessing it, and ``note``
    is set only when a flag was accepted and deliberately applied nothing.
    """
    filters: dict = {}
    described: list = []
    applied_note = ""

    for flag in ("artist", "album", "track", "genre", "mood", "style", "year"):
        value = parsed.get(flag)
        if value in (None, ""):
            continue
        field = FIELD_MAP[flag](libtype)
        filters[field] = value
        described.append(describe_filter(field, BARE_OPERATOR, value))

    raw_rating = parsed.get("rated_min")
    if raw_rating not in (None, ""):
        value = parse_stars(raw_rating, flag="--rated-min")
        # `userRating>>` is Plex's "is greater than", and it is the only
        # inequality a real server offers for an integer. Two lookalikes are
        # not: `userRating__gte` is not a Plex operator at all -- it survives
        # into the URL untranslated through the weak search path and becomes a
        # client-side post-filter through the strong one -- and `userRating>`
        # normalises to a `>=` the server refuses outright.
        field, threshold, row = rating_predicate(libtype, value)
        if field is None:
            applied_note = RATED_MIN_ZERO_NOTE
        else:
            filters[field] = threshold
            described.append(row)

    return filters, described, applied_note


def assert_server_side(leftover: dict) -> None:
    """Refuse to run a search the client library would filter client-side.

    Anything left in ``kwargs`` after ``_buildSearchKey`` is a PlexAPI operator
    rather than a Plex one: plexapi applies it in Python *after* the server has
    already sliced the result set, so it fights the limit instead of narrowing
    the query. It is never what the caller meant, and it looks like it worked.

    Public here and private in the tool, for one reason: there the caller was
    the next function down the same module, and here the caller is the probing
    layer that stayed behind. A leading underscore on a name another module has
    to import says the opposite of what it means.
    """
    if leftover:
        names = ", ".join(sorted(leftover))
        raise AxiError(
            f"refusing to filter on {names} after the server has already answered",
            recovery=(
                note("This is a bug in {tool}: every filter must be a server-side Plex predicate"),
                note("Report it at https://github.com/dmealing/{tool}/issues"),
            ),
            code="CLIENT_SIDE_FILTER",
        )


#: A relative date as Plex spells it: a count and a unit. plexapi normalises a
#: bare ``30d`` to ``-30d`` and passes it through, so a tool accepts the form
#: without the sign -- "30d ago" is how a caller says it.
RELATIVE_DATE = re.compile(r"^-?\d+(mon|[smhdwy])$")
ABSOLUTE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_relative_date(raw, *, flag: str) -> str:
    """Validate a relative date before the client library sees it.

    plexapi answers a malformed value with ``BadRequest`` naming its own field
    key, which is a message about the library rather than about the flag that
    was typed.
    """
    value = str(raw).strip()
    if RELATIVE_DATE.match(value):
        # The sign is plexapi's to add: it normalises `30d` to `-30d` and a
        # caller who wrote the minus meant the same thing.
        return value.lstrip("-")
    if ABSOLUTE_DATE.match(value):
        return value
    raise UsageError(
        f"{flag} needs a period like 30d, 6mon or 2y, or a date as YYYY-MM-DD, got {raw!r}",
        recovery=(
            retry(f"{flag} 30d"),
            note("units: s seconds, m minutes, h hours, d days, w weeks, mon months, y years"),
        ),
        code="BAD_PERIOD",
    )


#: The two directions Plex's sort parameter defines. Matched case-insensitively
#: and normalised, because `--type Track` is already accepted in any case and a
#: tool that took one and refused the other would be arbitrary about it.
SORT_DIRECTIONS = ("asc", "desc")


def parse_sort(raw, *, flag: str = "--sort"):
    """Validate ``field[:direction]`` before the client library builds a URL.

    Only the field half was ever checked. plexapi validates that against the
    section's advertised sorts and the tool's exception classification turns the
    refusal into a usage error naming every sort the server offers -- but the
    *direction* reached the server untouched, and an unknown one there is not a
    400. Plex answers it with a 404 on the result set, which arrived as "the
    search results was not found on this server": a sentence about the library,
    exit code 1, for what is a typo in an argument.

    The field is taken from the left of the last colon rather than the first,
    because a real Plex sort key may itself be a comma-joined list of scoped
    fields and none of them contains a colon.
    """
    if raw in (None, ""):
        return None
    value = str(raw).strip()
    field, separator, direction = value.rpartition(":")
    if not separator:
        return value
    if not field:
        raise UsageError(
            f"{flag} needs a field before the direction, got {value!r}",
            recovery=(
                retry(f"{flag} addedAt:desc"),
                note(
                    "Run the same command with a bad field name to see the sorts this server offers"
                ),
            ),
            code="BAD_SORT",
        )
    lowered = direction.strip().lower()
    if lowered not in SORT_DIRECTIONS:
        raise UsageError(
            f"{flag} direction must be {' or '.join(SORT_DIRECTIONS)}, got {direction!r}",
            recovery=(
                retry(f"{flag} {field}:desc"),
                note("The field half is checked against this server; only the direction is fixed"),
            ),
            code="BAD_SORT",
        )
    return f"{field}:{lowered}"
