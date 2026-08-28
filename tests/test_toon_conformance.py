"""The specification's own fixtures, run against this encoder.

``test_toon.py`` states the encoder's behaviour in this project's words, which is worth
having and is not the same thing as conformance: a rule nobody thought to write a test
for reads as passing. These are the specification's opinion, vendored byte-for-byte
(MIT; see ``src/axi_toolkit/toon_spec/PROVENANCE.md``), so "strict encoder" is a property
this suite checks rather than a claim the README makes.

The generated conformance layer already judges every case as one wire fact, against a
capture. This file is the same score stated where a person will look for it, and it
pins the published total: a fixture file that stopped being collected would otherwise
shrink the score in silence, which is exactly how a partial score ships.
"""

from __future__ import annotations

import pytest

from axi_toolkit import toon_spec
from axi_toolkit.toon import encode

#: The number of encode cases the vendored specification version publishes.
#:
#: The one deliberate literal in this repository, and it is a ratchet rather than an
#: expectation: every *value* a check compares against comes from the machine-written
#: capture, but the published total is the thing a refresh changes, and it has to be
#: edited by a person who noticed. See PROVENANCE.md's refresh recipe.
CASE_COUNT = 179


def test_the_score_is_179_of_179():
    """The headline claim, asserted rather than stated."""
    report = toon_spec.run(encode)
    assert report.failures == [], _explain(report)
    assert report.score == f"{CASE_COUNT}/{CASE_COUNT}"


@pytest.mark.parametrize("case", toon_spec.cases(), ids=toon_spec.case_id)
def test_each_published_case_encodes_to_the_specifications_bytes(case):
    """One test per case, so a failure names the case rather than the suite."""
    detail = f"{case.name} (spec section {case.spec_section or '?'})"
    assert encode(case.input, **toon_spec.encoder_kwargs(case)) == case.expected, detail


def test_the_whole_published_suite_runs():
    """A fixture that stops being collected must fail, not quietly shrink the score."""
    assert len(toon_spec.cases()) == CASE_COUNT


def test_every_vendored_fixture_matches_its_recorded_checksum():
    """A fixture edited to suit the encoder is no longer the specification's opinion."""
    assert toon_spec.digest_mismatches() == []


def test_every_fixture_file_is_an_encode_fixture():
    """Decode fixtures are not vendored; one arriving here would silently not run."""
    assert set(toon_spec.categories()) <= toon_spec.RUNNABLE_CATEGORIES


def test_no_case_expects_an_error():
    """No encode case is a should-error case today; one appearing needs handling here."""
    for path in toon_spec.fixture_files():
        import json

        for index, case in enumerate(json.loads(path.read_text(encoding="utf-8"))["tests"]):
            assert not case.get("shouldError"), f"{path.name}[{index}]"


def test_an_unrecognised_fixture_option_is_a_failure_not_a_skip():
    """Running a case with the wrong settings and reporting a pass is the worst outcome."""
    case = toon_spec.cases()[0]._replace(options={"someFutureOption": True})
    with pytest.raises(ValueError, match="does not apply"):
        toon_spec.encoder_kwargs(case)


def test_the_rig_can_judge_an_encoder_that_is_not_this_one():
    """The property that made the two tools' divergence measurable at all.

    ``run`` takes the encoder as an argument, so the same vendored files can score a
    different implementation. A rig that could only ever judge its own encoder could
    not have found that one copy scored 179 and the other 177.
    """

    def wrong(value, **kwargs):
        return "not the specification's bytes"

    report = toon_spec.run(wrong)
    assert report.passed == 0
    assert report.total == CASE_COUNT
    assert report.failures[0].got == "not the specification's bytes"


def _explain(report) -> str:
    return "\n".join(
        f"{toon_spec.case_id(failure.case)}: expected {failure.case.expected!r}, "
        f"got {failure.got!r}"
        for failure in report.failures[:5]
    )
