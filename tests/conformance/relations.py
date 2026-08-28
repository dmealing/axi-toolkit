"""The four relations a generated check can hold, and how to break each one.

A relation is picked by the projection kind the fact is declared under, never written
down beside the fact -- ``metaobjects/meta.axi-toolkit.yaml`` has no attribute for it, and
that is deliberate. A ``CapabilityFacts`` member gets :func:`equal`, a
``PopulationFacts`` member gets :func:`covers`, and so on, so the relation is a
consequence of where the fact was declared rather than a second thing to keep in step
with it.

Every relation returns ``None`` when it holds and a sentence when it does not, so a
generated check is one ``if`` and the failure explains itself without a traceback.

:func:`mutations` is the other half and the reason this module is not just five
comparisons. Each relation knows what breaking it looks like, so the harness can prove
every check still fails when it should. A check that has never failed is not yet a
check; ``test_requirements_generated.py`` runs each of these mutations and requires a
failure from each.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable

__all__ = ["covers", "differential", "equal", "mutations", "wire"]

_MISSING = object()


# ------------------------------------------------------------------- relations


def equal(subject: Any, captured: Any) -> str | None:
    """The library's own model of the fact is exactly the authority's.

    Both directions matter. A value the library holds and the authority does not is an
    invention -- which is what a hand-maintained table of what somebody believes a
    system offers always becomes. The other way round is a gap.
    """
    if isinstance(captured, list) or isinstance(subject, list):
        got, want = sorted(map(str, subject)), sorted(map(str, captured))
        if got == want:
            return None
        invented = [item for item in got if item not in want]
        missing = [item for item in want if item not in got]
        parts = []
        if invented:
            parts.append(f"held here and not by the authority: {invented}")
        if missing:
            parts.append(f"offered by the authority and not held here: {missing}")
        return "; ".join(parts)
    if subject == captured:
        return None
    return f"this package says {subject!r}; the authority says {captured!r}"


def covers(subject: Any, captured: Any) -> str | None:
    """Every shape the captured population contains is reachable here.

    One-directional on purpose. A cell this package can express that reality has never
    produced is headroom, not a defect; a cell reality produces that this package
    cannot express is the defect -- and it is the one branch coverage cannot find,
    because the branch does not exist to be left uncovered.
    """
    covered = set(map(str, subject))
    uncovered = [cell for cell in map(str, captured) if cell not in covered]
    if not uncovered:
        return None
    return (
        f"shapes present in the captured population with nothing here to express them: {uncovered}"
    )


def wire(subject: Callable[[str], Any], captured: Any) -> str | None:
    """Handed each captured input, this package emits the captured bytes.

    Reports the first divergence rather than all of them: the second is almost always
    the same cause, and a failure that fits on a screen gets read.
    """
    rows = list(captured)
    for row in rows:
        case, expected = row["case"], row["expected"]
        try:
            got = subject(case)
        except Exception as exc:
            return f"case {case!r} raised {type(exc).__name__}: {exc}"
        if got != expected:
            return f"case {case!r}\n  expected: {expected!r}\n  got     : {got!r}"
    return None


def differential(subject: Callable[[str], Any], captured: Any) -> str | None:
    """The two source copies agree, and this package matches what they agree on.

    Agreement is checked first and a disagreement is a failure, not a tie to be broken
    here. Two copies of one contract saying different things is precisely the defect
    this package exists to end, and picking a winner silently is how the divergence
    started. A person decides, in writing, and the row moves or the copies converge.
    """
    for row in list(captured):
        name, ha, plex = row["subject"], row["ha"], row["plex"]
        if ha != plex:
            return (
                f"the two source copies disagree about {name!r}\n"
                f"  ha-axi  : {ha!r}\n  plex-axi: {plex!r}\n"
                "  neither is adopted until somebody says which is right and why"
            )
        try:
            got = subject(name)
        except Exception as exc:
            return f"{name!r} raised {type(exc).__name__}: {exc}"
        if got != ha:
            return f"{name!r}\n  both sources: {ha!r}\n  this package: {got!r}"
    return None


RELATIONS = {
    "equal": equal,
    "covers": covers,
    "wire": wire,
    "differential": differential,
}


# ------------------------------------------------------------------- mutations


def mutations(relation: str, subject: Any, captured: Any) -> Iterator[tuple]:
    """Ways to break this check, as ``(what_was_broken, subject, captured)`` triples.

    Each one must make the relation report a failure. What is mutated is the *subject*
    wherever the claim is about this package, and the *capture* where the claim is
    about the two sources agreeing -- because that half has no subject to break.
    """
    if relation == "equal":
        if isinstance(captured, list):
            if captured:
                yield "a value the authority offers is missing here", list(captured)[1:], captured
            yield (
                "a value the authority does not offer is invented here",
                [*map(str, captured), "invented-by-this-package"],
                captured,
            )
        else:
            yield "the value differs from the authority's", _perturb(captured), captured
    elif relation == "covers":
        if captured:
            yield (
                "a shape the population contains is not expressible here",
                list(map(str, captured))[1:],
                captured,
            )
        else:
            yield (
                "a shape is added to the population that nothing here expresses",
                [],
                ["a-shape-nothing-expresses"],
            )
    elif relation == "wire":
        yield "the emitted bytes differ from the captured ones", _corrupt_wire(subject), captured
    elif relation == "differential":
        yield "this package matches neither source copy", _corrupt_wire(subject), captured
        if captured:
            yield "the two source copies disagree", subject, _disagree(captured)


def _perturb(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    return f"{value}-perturbed"


def _corrupt_wire(subject: Callable[[str], Any]) -> Callable[[str], Any]:
    def corrupted(case: str) -> Any:
        return f"{subject(case)} <corrupted by the vacuity self-test>"

    return corrupted


def _disagree(captured: Any) -> list:
    rows = [dict(row) for row in captured]
    rows[0]["plex"] = f"{rows[0]['plex']} <made to disagree by the vacuity self-test>"
    return rows
