"""The four relations, and the mutations that prove a check can fail.

These are the comparisons every generated check is made of, so they are tested
directly rather than only through the checks that use them. The mutation tests are the
load-bearing half: if a relation ever offered no way to break itself, every check using
it would pass its vacuity proof by producing nothing to prove.
"""

from __future__ import annotations

import pytest

from conformance import relations

# ------------------------------------------------------------------- equal


def test_equal_holds_on_the_same_set_in_any_order():
    assert relations.equal(["b", "a"], ["a", "b"]) is None


def test_equal_names_an_invention_and_a_gap_separately():
    problem = relations.equal(["a", "invented"], ["a", "missing"])
    assert "held here and not by the authority: ['invented']" in problem
    assert "offered by the authority and not held here: ['missing']" in problem


def test_equal_compares_scalars_too():
    assert relations.equal(179, 179) is None
    assert "this package says 178" in relations.equal(178, 179)


# ------------------------------------------------------------------ covers


def test_covers_is_one_directional():
    """Headroom is fine; a shape reality produces that nothing here expresses is not."""
    assert relations.covers(["a", "b", "spare"], ["a", "b"]) is None
    assert "['b']" in relations.covers(["a"], ["a", "b"])


def test_covers_on_an_empty_population_holds():
    assert relations.covers([], []) is None


# -------------------------------------------------------------------- wire


def test_wire_holds_when_every_case_emits_the_captured_bytes():
    rows = [{"case": "x", "expected": "X"}, {"case": "y", "expected": "Y"}]
    assert relations.wire(str.upper, rows) is None


def test_wire_reports_the_first_divergence_with_both_sides():
    rows = [{"case": "x", "expected": "X"}, {"case": "y", "expected": "nope"}]
    problem = relations.wire(str.upper, rows)
    assert "case 'y'" in problem and "'nope'" in problem and "'Y'" in problem
    assert "case 'x'" not in problem


def test_wire_turns_an_exception_into_a_report_rather_than_a_traceback():
    def explode(case):
        raise RuntimeError("boom")

    assert "RuntimeError: boom" in relations.wire(explode, [{"case": "x", "expected": "X"}])


# ------------------------------------------------------------ differential


def test_differential_holds_when_both_sources_agree_and_this_package_matches():
    rows = [{"subject": "a", "ha": "same", "plex": "same"}]
    assert relations.differential(lambda name: "same", rows) is None


def test_a_disagreement_between_the_sources_is_a_failure_not_a_tie_to_break():
    """Picking a winner silently is how the divergence this package ends got started."""
    rows = [{"subject": "toon.py", "ha": "aaa", "plex": "bbb"}]
    problem = relations.differential(lambda name: "aaa", rows)
    assert "disagree about 'toon.py'" in problem
    assert "somebody says which is right and why" in problem


def test_matching_neither_source_is_a_failure():
    rows = [{"subject": "a", "ha": "same", "plex": "same"}]
    problem = relations.differential(lambda name: "different", rows)
    assert "both sources: 'same'" in problem and "this package: 'different'" in problem


# --------------------------------------------------------------- mutations


CASES = {
    "equal": (["a", "b"], ["a", "b"]),
    "covers": (["a", "b"], ["a", "b"]),
    "wire": (str.upper, [{"case": "x", "expected": "X"}]),
    "differential": (lambda name: "same", [{"subject": "a", "ha": "same", "plex": "same"}]),
}


@pytest.mark.parametrize("relation", sorted(CASES))
def test_every_relation_offers_at_least_one_way_to_break_it(relation):
    subject, captured = CASES[relation]
    assert list(relations.mutations(relation, subject, captured))


@pytest.mark.parametrize("relation", sorted(CASES))
def test_every_mutation_makes_the_relation_fail(relation):
    subject, captured = CASES[relation]
    assert relations.RELATIONS[relation](subject, captured) is None, "the case must start green"
    for description, mutated_subject, mutated_capture in relations.mutations(
        relation, subject, captured
    ):
        assert relations.RELATIONS[relation](mutated_subject, mutated_capture) is not None, (
            description
        )


def test_equal_on_a_scalar_is_broken_by_perturbing_it():
    broken = list(relations.mutations("equal", 179, 179))
    assert broken and all(relations.equal(s, c) is not None for _, s, c in broken)


def test_covers_on_an_empty_population_still_has_a_mutation():
    """An empty population would otherwise give a check nothing to prove itself with."""
    broken = list(relations.mutations("covers", [], []))
    assert broken
    for _, subject, captured in broken:
        assert relations.covers(subject, captured) is not None


def test_the_differential_is_broken_from_both_ends():
    subject, captured = CASES["differential"]
    labels = [
        description for description, _, _ in relations.mutations("differential", subject, captured)
    ]
    assert any("matches neither" in label for label in labels)
    assert any("disagree" in label for label in labels)
