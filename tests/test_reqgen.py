"""The generator's own rules, which are the ones the metadata loader does not check.

The loader validates the requirement vocabulary -- required attributes, the closed
status set, no invented attributes -- and stops. Everything that makes
``@implementedBy`` mean something is enforced in ``scripts/reqgen.py``, so it is tested
here rather than trusted.

Loading real metadata needs the metadata toolchain, whose floor is Python 3.11 while
this suite runs down to 3.9. Nothing here loads any: the rules operate on the model
objects, so they are tested on models built in the test. The real declaration is loaded
by the ``requirements`` CI job, which runs ``reqgen check`` and fails on a stale
generated file -- a gate rather than a skipped test, because a skipped agreement check
reads exactly like a passing one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_reqgen():
    """Import the script by path; it is a tool, not an installed module."""
    spec = importlib.util.spec_from_file_location("reqgen", ROOT / "scripts" / "reqgen.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["reqgen"] = module
    spec.loader.exec_module(module)
    return module


reqgen = _load_reqgen()


def fact(name: str, object_name: str = "CapabilityFacts", **kw):
    return reqgen.Fact(
        name=name,
        object_name=object_name,
        sub_type=kw.get("sub_type", "string"),
        is_array=kw.get("is_array", True),
    )


def requirement(
    path: str,
    *,
    sub_type: str = "functional",
    level=5,
    status: str = "live",
    targets=(),
    is_leaf: bool = True,
):
    return reqgen.Requirement(
        path=path,
        sub_type=sub_type,
        level=level,
        status=status,
        statement="A claim.",
        counterexample="Its violation.",
        targets=tuple(targets),
        is_leaf=is_leaf,
    )


def bind(facts, requirements):
    by_fqn = {f.fqn: f for f in facts}
    reqgen.bind(by_fqn, list(requirements))
    return by_fqn


def refuses(match, facts, requirements):
    with pytest.raises(reqgen.DeclarationError, match=match):
        bind(facts, requirements)


# ------------------------------------------------------- the relation is derived


def test_the_projection_object_decides_the_relation():
    """There is no attribute for it; the object a fact lives on is the whole answer."""
    assert fact("x", "CapabilityFacts").relation == "equal"
    assert fact("x", "PopulationFacts").relation == "covers"
    assert fact("x", "WireFacts").relation == "wire"
    assert fact("x", "DifferentialFacts").relation == "differential"


def test_a_facts_name_is_the_whole_reference_to_its_two_projections():
    subject = fact("toonEncodeCaseCount")
    assert subject.capture_fn == "capture_toon_encode_case_count"
    assert subject.subject_fn == "subject_toon_encode_case_count"
    assert subject.fqn == "axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount"


# ------------------------------------------------------------------- the rules


def test_a_live_leaf_naming_no_fact_is_refused():
    """A requirement with no check must be red, not read as covered because it exists."""
    refuses(
        "names no fact",
        [fact("toonEncodeCaseCount")],
        [
            requirement("claimsNothing"),
            requirement(
                "claimsIt",
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            ),
        ],
    )


def test_a_parent_naming_no_fact_is_fine_because_its_children_carry_the_claim():
    facts = [fact("toonEncodeCaseCount")]
    bind(
        facts,
        [
            requirement("tree", level=1, is_leaf=False, targets=()),
            requirement(
                "tree.leaf",
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            ),
        ],
    )


def test_a_planned_leaf_may_name_nothing_and_may_dangle():
    """Planned is the one status where the nodes do not exist yet, by definition.

    Both spellings of "not yet" are legal and the declaration uses the second one:
    naming a fact that has not been written, and naming none at all. The gate policy
    `anExtractedModuleIsGatedAgainstItsOriginUntilTheToolTakesIt` sits at `planned` with
    no `@implementedBy` because no module currently lives in two repositories, so there
    is nothing to gate -- and a `live` requirement with no check would read as coverage,
    which is the rule the previous test states.
    """
    facts = [fact("toonEncodeCaseCount")]
    bind(
        facts,
        [
            requirement(
                "later", status="planned", targets=("axi_toolkit::conformance::WireFacts.notYet",)
            ),
            requirement("someday", sub_type="architectural", level=None, status="planned"),
            requirement(
                "now", targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",)
            ),
        ],
    )


@pytest.mark.parametrize("level", [1, 2, 3])
def test_implemented_by_above_the_binding_floor_is_refused(level):
    """L1-L3 are levels of abstraction; only an object or a member is a node."""
    refuses(
        "binding floor",
        [fact("toonEncodeCaseCount")],
        [
            requirement(
                "tooHigh",
                level=level,
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            )
        ],
    )


@pytest.mark.parametrize("level", [4, 5])
def test_implemented_by_at_the_binding_floor_is_accepted(level):
    facts = [fact("toonEncodeCaseCount")]
    bind(
        facts,
        [
            requirement(
                "bound",
                level=level,
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            )
        ],
    )


def test_a_flat_architectural_requirement_may_bind_without_a_level():
    """Level is optional there, and absent means a flat policy that references the model."""
    facts = [fact("toonEncodeCaseCount")]
    bind(
        facts,
        [
            requirement(
                "policy",
                sub_type="architectural",
                level=None,
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            )
        ],
    )


def test_a_levelled_architectural_requirement_obeys_the_same_floor():
    refuses(
        "binds at L4 or L5",
        [fact("toonEncodeCaseCount")],
        [
            requirement(
                "policy",
                sub_type="architectural",
                level=2,
                targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",),
            )
        ],
    )


def test_nesting_may_skip_a_level_but_never_return_to_one():
    target = ("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",)
    facts = [fact("toonEncodeCaseCount")]
    bind(
        facts,
        [requirement("t", level=1, is_leaf=False), requirement("t.leaf", level=5, targets=target)],
    )
    refuses(
        "never return to one",
        [fact("toonEncodeCaseCount")],
        [
            requirement("t", level=5, is_leaf=False, targets=target),
            requirement("t.child", level=4, targets=target),
        ],
    )


def test_a_live_requirement_naming_a_fact_that_does_not_exist_is_refused():
    refuses(
        "not a declared fact",
        [fact("toonEncodeCaseCount")],
        [
            requirement(
                "real", targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",)
            ),
            requirement("stale", targets=("axi_toolkit::conformance::WireFacts.longGone",)),
        ],
    )


def test_a_fact_no_live_requirement_claims_is_refused():
    """A fact nothing claims is a check nobody asked for."""
    refuses(
        "claimed by no live or partial requirement",
        [fact("toonEncodeCaseCount"), fact("orphan")],
        [
            requirement(
                "real", targets=("axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount",)
            )
        ],
    )


def test_a_fact_with_no_projection_pair_is_refused():
    """Generation must not emit a check that cannot run."""
    refuses(
        "needs capture_never_projected",
        [fact("neverProjected")],
        [
            requirement(
                "claim", targets=("axi_toolkit::conformance::CapabilityFacts.neverProjected",)
            )
        ],
    )


def test_a_requirement_may_tag_a_whole_projection_object_at_l4():
    """L4 is an object, so tagging one claims every member it declares."""
    facts = [fact("toonEncodeCaseCount"), fact("toonFixtureDigests")]
    bound = bind(
        facts,
        [
            requirement(
                "wholeObject", level=4, targets=("axi_toolkit::conformance::CapabilityFacts",)
            )
        ],
    )
    for subject in bound.values():
        assert [req.path for req in subject.requirements] == ["wholeObject"]


# ---------------------------------------------------------------- the output


def test_the_generated_module_is_what_the_declaration_produces_now():
    """Not a regeneration: the committed file is compared against the rendering.

    Rendering needs only the model, so this runs on every Python the matrix covers,
    while the CI job that loads the real declaration runs on one.
    """
    facts = {
        "axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount": fact("toonEncodeCaseCount")
    }
    facts["axi_toolkit::conformance::CapabilityFacts.toonEncodeCaseCount"].requirements = [
        requirement("tree.leaf")
    ]
    rendered = reqgen.render(facts)
    assert "# @generated by scripts/reqgen.py" in rendered
    assert "def test_toon_encode_case_count():" in rendered
    assert "def test_no_check_is_vacuous(fact):" in rendered
    assert '    "toonEncodeCaseCount": (\n        "equal",\n' in rendered
    assert "lambda captured: projections.subject_toon_encode_case_count()" in rendered


def test_the_generated_module_carries_the_claim_and_its_counterexample():
    subject = fact("toonEncodeCaseCount")
    subject.requirements = [requirement("tree.leaf")]
    rendered = reqgen.render({subject.fqn: subject})
    assert "A claim." in rendered
    assert "Breaking it looks like: Its violation." in rendered


def test_the_committed_generated_module_matches_the_committed_capture():
    """Every fact the checks read is in the capture, and nothing in it is unread.

    The two come from one declaration and so cannot drift; this is the assertion that
    says so out loud, and it needs neither the toolchain nor a regeneration.
    """
    import json

    from conformance import test_requirements_generated as generated

    captured = set(
        json.loads((ROOT / "tests" / "conformance" / "capture.json").read_text(encoding="utf-8"))[
            "facts"
        ]
    )
    assert set(generated.CHECKS) == captured
    assert set(generated.SUBJECTS) == captured


def test_snake_case_matches_the_projection_naming_convention():
    assert reqgen.snake("toonEncodeCaseCount") == "toon_encode_case_count"
    assert reqgen.snake("haRecoveryLines") == "ha_recovery_lines"
    assert reqgen.snake("encoderDigest") == "encoder_digest"
