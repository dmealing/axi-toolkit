"""The official TOON conformance fixtures, vendored beside the encoder they judge.

They live inside the package rather than under ``tests/`` on purpose. Two AXI CLIs
each carried their own copy of both the encoder and these fixtures; one copy got a
``MUST``-rule fix and the other did not, and the divergence was invisible until
somebody ran both against the same files. One copy of the encoder fixes that only if
there is also one copy of the thing that judges it -- so a tool taking this package
gets the rig too, and asserts its own score with :func:`run` rather than re-vendoring
179 cases and hoping they stayed in step.

Nothing here imports :mod:`axi_core.toon`. The fixtures are the specification's
opinion and the encoder is this package's; keeping the two modules apart is what lets
:func:`run` be handed some *other* encoder -- which is exactly how the divergence
between the two tools was measured in the first place.

Provenance, the licence and the refresh recipe are in ``PROVENANCE.md`` beside this
file. ``checksums.txt`` records what each file hashed to when it was vendored, and
:func:`digest_mismatches` is how a fixture edited to suit a failing encoder stops
being a silent edit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable, NamedTuple

__all__ = [
    "ENCODE_ROOT",
    "KNOWN_OPTIONS",
    "ROOT",
    "RUNNABLE_CATEGORIES",
    "Case",
    "Failure",
    "Report",
    "cases",
    "digest_mismatches",
    "encoder_kwargs",
    "fixture_files",
    "recorded_digests",
    "run",
]

#: The vendored tree: the fixtures, their licence, their provenance, their checksums.
ROOT = Path(__file__).resolve().parent

#: Only the encode half is vendored. The encoder has no decoder, so decode fixtures
#: would be fourteen files nothing can run -- see PROVENANCE.md.
ENCODE_ROOT = ROOT / "encode"

CHECKSUMS = ROOT / "checksums.txt"

#: Fixture option names this rig knows how to turn into encoder arguments. An
#: unrecognised one is a failure rather than a skip: running a case with the wrong
#: settings and reporting a pass is worse than not running it.
KNOWN_OPTIONS = frozenset({"delimiter", "indentSize"})

#: Fixture categories this rig runs. Upstream also publishes decode fixtures; those
#: are not vendored, and one arriving in ``encode/`` must fail rather than be
#: collected and silently not run.
RUNNABLE_CATEGORIES = frozenset({"encode"})


class Case(NamedTuple):
    """One published encode case, identified by file and index.

    Never by the fixture's prose ``name``: upstream rewrites those whenever the
    specification's terminology moves, and a runner keyed on them breaks on a refresh
    that changed no expected byte.
    """

    file: str
    index: int
    name: str
    spec_section: str
    input: Any
    expected: str
    options: dict


class Failure(NamedTuple):
    case: Case
    got: str


class Report(NamedTuple):
    passed: int
    total: int
    failures: list[Failure]

    @property
    def score(self) -> str:
        """``"179/179"`` -- the form the assessments quote."""
        return f"{self.passed}/{self.total}"


def fixture_files() -> list[Path]:
    """Every vendored fixture file, in a stable order."""
    return sorted(ENCODE_ROOT.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def categories() -> list[str]:
    """The ``category`` each fixture file declares.

    A decode fixture arriving in this directory would otherwise be collected and
    silently not run; naming the categories out loud is what makes that visible.
    """
    return [str(_load(path).get("category", "")) for path in fixture_files()]


def cases() -> list[Case]:
    """Every published encode case, in file-then-index order."""
    out: list[Case] = []
    for path in fixture_files():
        for index, case in enumerate(_load(path)["tests"]):
            out.append(
                Case(
                    file=path.name,
                    index=index,
                    name=str(case.get("name", "")),
                    spec_section=str(case.get("specSection", "")),
                    input=case["input"],
                    expected=case["expected"],
                    options=dict(case.get("options") or {}),
                )
            )
    return out


def case_id(case: Case) -> str:
    """``"primitives-34"`` -- what a failing case is called in a test report."""
    return f"{case.file[: -len('.json')]}-{case.index}"


def option_names() -> list[str]:
    """Every option name any published case uses, deduplicated and sorted."""
    return sorted({name for case in cases() for name in case.options})


def exercised_delimiters() -> list[str]:
    """Every delimiter the published cases ask for, including the implied default.

    A delimiter the fixtures exercise and the encoder rejects is a conformance gap
    that no per-case assertion names, because the case fails for the wrong reason.
    """
    seen = {","}
    for case in cases():
        if "delimiter" in case.options:
            seen.add(str(case.options["delimiter"]))
    return sorted(seen)


def encoder_kwargs(case: Case) -> dict:
    """Map a case's options onto this package's encoder keywords.

    The specification spells the indentation option ``indentSize`` and the encoder's
    keyword is ``indent``. That is a difference in the encoder's API surface (spec
    section 13), not in a byte it emits, and the mapping lives in exactly one place so
    no vendored file has to be edited to run.

    Raises :class:`ValueError` on an option this rig does not apply, rather than
    dropping it: a case run with default settings and reported as a pass is the
    failure mode the whole vendoring exercise exists to prevent.
    """
    unknown = set(case.options) - KNOWN_OPTIONS
    if unknown:
        raise ValueError(
            f"{case_id(case)} uses fixture options this rig does not apply: {sorted(unknown)}"
        )
    kwargs: dict = {}
    if "delimiter" in case.options:
        kwargs["delimiter"] = case.options["delimiter"]
    if "indentSize" in case.options:
        kwargs["indent"] = case.options["indentSize"]
    return kwargs


def recorded_digests() -> dict[str, str]:
    """The SHA-256 of each file as recorded when the tree was vendored."""
    recorded: dict[str, str] = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            recorded[name.strip()] = digest
    return recorded


def actual_digests() -> dict[str, str]:
    """The SHA-256 of each file as it stands on disk now."""
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in fixture_files()}


def digest_mismatches() -> list[str]:
    """File names whose content no longer matches the vendored upstream copy.

    Includes a file present in one of the two views and not the other, because a
    fixture deleted and a fixture edited are the same failure from here.
    """
    recorded, actual = recorded_digests(), actual_digests()
    return sorted(
        name for name in set(recorded) | set(actual) if recorded.get(name) != actual.get(name)
    )


def run(encode: Callable[..., str], only: Iterable[Case] | None = None) -> Report:
    """Encode every published case with ``encode`` and report the score.

    ``encode`` is a parameter rather than an import so this rig can judge a *different*
    implementation -- which is how the two tools' copies were found to score 179 and
    177 against the identical files.
    """
    selected = list(cases() if only is None else only)
    failures: list[Failure] = []
    for case in selected:
        got = encode(case.input, **encoder_kwargs(case))
        if got != case.expected:
            failures.append(Failure(case=case, got=got))
    return Report(passed=len(selected) - len(failures), total=len(selected), failures=failures)
