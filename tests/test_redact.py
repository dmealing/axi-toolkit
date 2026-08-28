"""The credential boundary.

No credential shape is written down in this file. Every one is assembled at run time
from pieces, the way the source tools' own suites do it, because this repository is
public and its leak scanner reads test files too -- and because a scanner that had to
be taught to ignore its own tests would be one exemption away from ignoring a real
leak.

The ordering tests need their own note. For the five shapes the two tools carry between
them the order the rules run in is *not* observable -- each rule leaves a placeholder
the next one cannot match, so every ordering converges on the same bytes. That is why
neither tool ever wrote its order down. The two tests below are built to make the order
visible anyway, because the first shape somebody adds where it matters should not be
the thing that discovers what the order was.
"""

from __future__ import annotations

import base64
import json

import pytest

from axi_toolkit import redact
from axi_toolkit.redact import REDACTED, Redactor


def synthetic_jwt() -> str:
    """A JWT-shaped value, built rather than written.

    A literal ``eyJ...`` in a source file is a credential shape in a public repository
    even when the payload is nonsense, and the repository's own scanner is right to
    refuse one.
    """

    def segment(payload: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    return ".".join((segment({"alg": "HS256"}), segment({"sub": "synthetic"}), "c2lnbmF0dXJl"))


BEARER_VALUE = "abcdef" + "123456" + "ghijkl"
PLEX_VALUE = "plex" + "0123456789abcdef"
PLEX_PARAM = r"(?i)(X-Plex-Token=)[A-Za-z0-9._~-]{4,}"


@pytest.fixture
def boundary() -> Redactor:
    return Redactor()


# ------------------------------------------------------------------- literals


def test_a_registered_literal_never_survives(boundary):
    boundary.register_secret("a-very-secret-value")
    assert "a-very-secret-value" not in boundary.redact("token=a-very-secret-value trailing")
    assert REDACTED in boundary.redact("token=a-very-secret-value")


def test_a_literal_shorter_than_the_floor_is_not_registered(boundary):
    """Redacting a short string collides with ordinary words and corrupts output."""
    boundary.register_secret("abc")
    assert boundary.redact("abc def") == "abc def"


def test_the_floor_can_be_lowered_for_a_value_known_to_be_a_credential(boundary):
    """URL userinfo is a credential by where it came from, not by its shape."""
    boundary.register_secret("pw12", min_length=4)
    assert boundary.redact("pair is someone:pw12") == "pair is someone:<redacted>"


def test_none_and_empty_are_not_registered(boundary):
    boundary.register_secret(None)
    boundary.register_secret("")
    assert boundary.redact("anything at all") == "anything at all"


def test_the_longest_literal_wins_so_no_half_redacted_fragment_survives(boundary):
    """An overlapping pair must go whole, or the shorter half is left in the output."""
    boundary.register_secret("someone:example-secret", min_length=4)
    boundary.register_secret("example-secret", min_length=4)
    assert boundary.redact("pair is someone:example-secret") == "pair is <redacted>"


def test_resetting_secrets_keeps_registered_shapes(boundary):
    boundary.register_pattern(PLEX_PARAM)
    boundary.register_secret("a-very-secret-value")
    boundary.reset_secrets()
    assert "a-very-secret-value" in boundary.redact("a-very-secret-value")
    assert REDACTED in boundary.redact(f"?X-Plex-Token={PLEX_VALUE}")


def test_resetting_everything_drops_the_shapes_too(boundary):
    boundary.register_pattern(PLEX_PARAM)
    boundary.reset()
    assert boundary.registered_patterns() == ()


# --------------------------------------------------------------------- shapes


def test_a_bearer_header_keeps_its_prefix_and_loses_its_value(boundary):
    cleaned = boundary.redact(f"Authorization: Bearer {BEARER_VALUE}")
    assert cleaned == f"Authorization: Bearer {REDACTED}"


def test_a_jwt_is_redacted_whole_even_though_it_was_never_registered(boundary):
    token = synthetic_jwt()
    cleaned = boundary.redact(f"leaked {token} here")
    assert token not in cleaned
    assert cleaned == f"leaked {REDACTED} here"


def test_a_registered_shape_with_a_group_keeps_the_prefix(boundary):
    """A reader still needs to know which credential was suppressed."""
    boundary.register_pattern(PLEX_PARAM)
    cleaned = boundary.redact(f"http://host.example.com/art?X-Plex-Token={PLEX_VALUE}")
    assert cleaned.endswith(f"?X-Plex-Token={REDACTED}")


def test_a_registered_shape_with_no_group_is_replaced_whole(boundary):
    boundary.register_pattern(r"\bprobe-[A-Za-z0-9]{4,}")
    assert boundary.redact("value probe-abcd1234 end") == f"value {REDACTED} end"


def test_registering_the_same_shape_twice_is_a_no_op(boundary):
    boundary.register_pattern(PLEX_PARAM)
    boundary.register_pattern(PLEX_PARAM)
    assert boundary.registered_patterns() == (PLEX_PARAM,)


def test_registered_shapes_are_reported_in_the_order_they_run(boundary):
    first, second = PLEX_PARAM, r"(?i)([?&]token=)[A-Za-z0-9._~-]{8,}"
    boundary.register_pattern(first)
    boundary.register_pattern(second)
    assert boundary.registered_patterns() == (first, second)


# ---------------------------------------------------------------- the ordering


def test_a_registered_shape_runs_after_the_bearer_rule(boundary):
    """Built to make the order visible: for the tools' own shapes it is not.

    A no-group shape that spans the word ``Bearer`` swallows the prefix if it runs
    first. Because the built-in rule goes first and leaves an inert placeholder, the
    prefix survives and this shape no longer matches -- so the output says which
    order ran.
    """
    boundary.register_pattern(r"(?i)bearer\s+[A-Za-z0-9]+")
    cleaned = boundary.redact(f"Authorization: Bearer {BEARER_VALUE}")
    assert cleaned == f"Authorization: Bearer {REDACTED}"


def test_the_jwt_rule_runs_last_so_a_registered_shape_gets_its_chance(boundary):
    """The mirror image: a shape spanning a JWT still matches, because JWT goes last."""
    boundary.register_pattern(r"(?i)token [A-Za-z0-9_.-]+")
    assert boundary.redact(f"token {synthetic_jwt()}") == REDACTED


def test_a_literal_is_removed_before_any_shape_looks_at_the_text(boundary):
    """A literal is known to be a credential; a shape only suspects it."""
    boundary.register_pattern(r"(?i)(secret=)[a-z]+")
    boundary.register_secret("swordfish-value")
    assert boundary.redact("secret=swordfish-value") == "secret=<redacted>"


def test_nothing_that_is_not_a_credential_is_touched(boundary):
    """A redactor that cries wolf corrupts output people then stop trusting."""
    ordinary = "an ordinary sentence about a token, a bearer and a secret"
    assert boundary.redact(ordinary) == ordinary


# ------------------------------------------------------- the shared instance


def test_the_module_level_functions_act_on_one_shared_boundary():
    """One process, one output boundary: a CLI must not have to thread an object."""
    redact.reset()
    try:
        redact.register_secret("a-very-secret-value")
        redact.register_patterns([PLEX_PARAM])
        assert redact.redact("a-very-secret-value") == REDACTED
        assert redact.registered_patterns() == (PLEX_PARAM,)
        assert REDACTED in redact.redact(f"?X-Plex-Token={PLEX_VALUE}")
    finally:
        redact.reset()


def test_two_boundaries_keep_their_shapes_apart():
    """A caller embedding both tools must not leak one's patterns into the other."""
    mine, theirs = Redactor(), Redactor()
    mine.register_pattern(PLEX_PARAM)
    assert theirs.registered_patterns() == ()
    assert REDACTED not in theirs.redact(f"?X-Plex-Token={PLEX_VALUE}")
