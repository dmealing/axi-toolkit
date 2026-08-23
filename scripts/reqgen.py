#!/usr/bin/env python3
"""Turn the declared requirements into checks, a capture, and a proof they can fail.

``metaobjects/meta.axi-core.yaml`` is the source of truth. This script is the only
thing that reads it, and it emits three artefacts from that one declaration:

* ``tests/conformance/capture.json`` -- every expected value, read from the two
  authorities by machine and never edited by hand (``reqgen capture``);
* ``tests/conformance/test_requirements_generated.py`` -- one check per fact, plus a
  vacuity self-test that breaks each one in turn (``reqgen generate``);
* a verdict on whether the committed copy of that file is what the declaration would
  produce now (``reqgen check``).

**Why generate rather than hand-write the checks.** A prior measurement was honest
about this: thirty-one lines of plain pytest reading the same capture caught every
defect, and generation costs more lines than it saves per check. It earns its place on
four categorical things, and if a design loses any of them it should be simplified back
to plain pytest instead:

1. **There is nowhere to type an expected value.** Not by convention -- the metadata
   registry is sealed (ADR-0023), so an ``@expected`` attribute is ``ERR_UNKNOWN_ATTR``
   at load time. The declaration *cannot* hold one.
2. **A requirement with no check is red.** A live or partial leaf requirement tagging
   no fact fails generation, so a claim nobody checked cannot read as covered because
   somebody wrote it down.
3. **The capture and the checks cannot drift apart.** Both come from the same fact
   members: a capture cannot hold a fact no check reads, and a check cannot name a fact
   the capture does not produce.
4. **The vacuity self-test comes free**, because the relation knows what breaking it
   looks like.

**What this script enforces that the loader does not.** The Python loader validates the
requirement vocabulary -- required attributes, the closed ``@status`` set, no invented
attributes -- and stops there. The rules that make ``@implementedBy`` mean something are
checked here: the L4/L5 binding floor, nesting that never goes back up, references that
resolve, and the two rules above. A violation is a generation failure with the node
named, never a warning.

Usage:
  scripts/reqgen.py capture     read both authorities and write the capture
  scripts/reqgen.py generate    write the generated check module
  scripts/reqgen.py check       fail if the committed module is stale
  scripts/reqgen.py list        print the declaration as a table
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
METADATA_DIR = REPO_ROOT / "metaobjects"
CONFORMANCE_DIR = REPO_ROOT / "tests" / "conformance"
PROJECTIONS = CONFORMANCE_DIR / "projections.py"
CAPTURE_PATH = CONFORMANCE_DIR / "capture.json"
GENERATED_PATH = CONFORMANCE_DIR / "test_requirements_generated.py"

#: The package every fact and requirement is declared in.
PACKAGE = "axi_core::conformance"

#: Which relation each projection kind implies. The kind is the object a fact is
#: declared on, so the relation is a consequence of where the fact lives rather than a
#: second thing to keep in step with it -- and there is no attribute to spell it.
RELATION_BY_OBJECT = {
    "CapabilityFacts": "equal",
    "PopulationFacts": "covers",
    "WireFacts": "wire",
    "DifferentialFacts": "differential",
}

#: Statuses whose ``@implementedBy`` may name nodes that do not exist. On ``planned``
#: they do not exist yet; on the other two they are meant to be gone.
DANGLING_OK = frozenset({"planned", "abandoned", "superseded"})

#: Statuses that make a claim about the code as it stands.
ACTIVE = frozenset({"live", "partial"})

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


class DeclarationError(Exception):
    """The declaration is wrong. Named node, stated rule, no generation."""


def snake(name: str) -> str:
    return _CAMEL.sub("_", name).lower()


# ------------------------------------------------------------------- the model


class Fact:
    __slots__ = ("is_array", "name", "object", "relation", "requirements", "sub_type")

    def __init__(self, name: str, object_name: str, sub_type: str, is_array: bool) -> None:
        self.name = name
        self.object = object_name
        self.sub_type = sub_type
        self.is_array = is_array
        self.relation = RELATION_BY_OBJECT[object_name]
        self.requirements: list[Requirement] = []

    @property
    def fqn(self) -> str:
        return f"{PACKAGE}::{self.object}.{self.name}"

    @property
    def capture_fn(self) -> str:
        return f"capture_{snake(self.name)}"

    @property
    def subject_fn(self) -> str:
        return f"subject_{snake(self.name)}"


class Requirement:
    __slots__ = (
        "counterexample",
        "is_leaf",
        "level",
        "path",
        "statement",
        "status",
        "sub_type",
        "targets",
    )

    def __init__(self, path, sub_type, level, status, statement, counterexample, targets, is_leaf):
        self.path = path
        self.sub_type = sub_type
        self.level = level
        self.status = status
        self.statement = statement
        self.counterexample = counterexample
        self.targets = targets
        self.is_leaf = is_leaf


def load_declaration() -> tuple[dict, list]:
    """Load the metadata strictly, and read the facts and requirements out of it."""
    try:
        from metaobjects import MetaDataLoader
    except ImportError as exc:  # pragma: no cover -- the message is the whole value
        raise SystemExit(
            "reqgen needs the metaobjects loader, which validates the declaration "
            "before anything is generated from it.\n"
            "    python3.11 -m pip install 'axi-core[reqgen]'\n"
            f"({exc})"
        ) from exc

    result = MetaDataLoader.from_directory(str(METADATA_DIR), strict=True)
    if result.errors:
        raise DeclarationError(
            "the declaration does not load:\n" + "\n".join(f"  {error}" for error in result.errors)
        )

    facts: dict[str, Fact] = {}
    requirements: list[Requirement] = []
    for node in result.root.children():
        if node.type == "object" and node.name in RELATION_BY_OBJECT:
            for member in node.fields():
                fact = Fact(
                    name=member.name,
                    object_name=node.name,
                    sub_type=member.sub_type,
                    is_array=bool(member.resolved_is_array()),
                )
                facts[fact.fqn] = fact
        elif node.type == "requirement":
            _collect_requirement(node, (), requirements)
    if not facts:
        raise DeclarationError("no projection object declares a fact; there is nothing to check")
    return facts, requirements


def _collect_requirement(node, prefix: tuple, out: list) -> None:
    attrs = dict(node.attrs())
    path = (*prefix, node.name)
    children = [child for child in node.children() if child.type == "requirement"]
    out.append(
        Requirement(
            path=".".join(path),
            sub_type=node.sub_type,
            level=attrs.get("level"),
            status=str(attrs.get("status", "")),
            statement=" ".join(str(attrs.get("statement", "")).split()),
            counterexample=" ".join(str(attrs.get("counterexample", "")).split()),
            targets=tuple(attrs.get("implementedBy") or ()),
            is_leaf=not children,
        )
    )
    for child in children:
        _collect_requirement(child, path, out)


# -------------------------------------------------------------- the extra rules


def bind(facts: dict[str, Fact], requirements: list) -> None:
    """Apply the rules the loader does not, and tie each fact to its claims."""
    problems: list[str] = []
    by_path = {req.path: req for req in requirements}

    for req in requirements:
        where = f"{req.sub_type} {req.path!r}"

        # The binding floor. `@implementedBy` resolves to nodes in the model, and only
        # an object (L4) or a member (L5) is a node; an organisational level carrying
        # one is claiming to be implemented by an abstraction.
        if req.targets:
            if req.sub_type == "functional" and req.level not in (4, 5):
                problems.append(
                    f"{where} carries @implementedBy at level {req.level}; "
                    "the binding floor is L4 (an object) or L5 (a member)"
                )
            elif (
                req.sub_type == "architectural"
                and req.level is not None
                and req.level not in (4, 5)
            ):
                problems.append(
                    f"{where} carries @implementedBy at level {req.level}; "
                    "a levelled architectural requirement binds at L4 or L5 only"
                )

        # Nesting agrees with the level: skipping one is legal, going back up is not.
        parent_path = req.path.rpartition(".")[0]
        parent = by_path.get(parent_path)
        if (
            parent is not None
            and parent.level is not None
            and req.level is not None
            and req.level <= parent.level
        ):
            problems.append(
                f"{where} is level {req.level} inside a level {parent.level} parent; "
                "nesting may skip a level but never return to one"
            )

        # A requirement with no check is red. Only leaves: a parent's claim is made by
        # the children it contains, which is what nesting means here.
        if req.is_leaf and req.status in ACTIVE and not req.targets:
            problems.append(
                f"{where} is {req.status} and names no fact. A requirement with no check "
                "must be red rather than read as covered because somebody wrote it down"
            )

        for target in req.targets:
            if target in facts:
                facts[target].requirements.append(req)
                continue
            if _names_projection_object(target):
                for fact in facts.values():
                    if fact.fqn.startswith(target + "."):
                        fact.requirements.append(req)
                continue
            if req.status not in DANGLING_OK:
                problems.append(
                    f"{where} names {target!r}, which is not a declared fact. "
                    f"A {req.status} requirement's references must resolve"
                )

    declared = _projection_functions()
    for fact in sorted(facts.values(), key=lambda f: f.fqn):
        if not any(req.status in ACTIVE for req in fact.requirements):
            problems.append(
                f"fact {fact.fqn} is claimed by no live or partial requirement. "
                "A fact nothing claims is a check nobody asked for"
            )
        for function in (fact.capture_fn, fact.subject_fn):
            if function not in declared:
                problems.append(
                    f"fact {fact.fqn} needs {function}() in tests/conformance/projections.py"
                )

    if problems:
        raise DeclarationError("\n".join(f"  - {problem}" for problem in problems))


def _names_projection_object(target: str) -> bool:
    return any(target == f"{PACKAGE}::{name}" for name in RELATION_BY_OBJECT)


def _projection_functions() -> set[str]:
    """The projection function names, read without importing the module.

    Generation must work without this package installed -- the metadata toolchain
    needs Python 3.11 and the test matrix runs down to 3.9, so the two never have to
    be in the same interpreter.
    """
    tree = ast.parse(PROJECTIONS.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


# --------------------------------------------------------------------- capture


def do_capture(facts: dict[str, Fact]) -> int:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from conformance import projections

    captured = {}
    for fact in sorted(facts.values(), key=lambda f: f.name):
        captured[fact.name] = getattr(projections, fact.capture_fn)()
    payload = {
        "_comment": (
            "Machine-written by scripts/reqgen.py from the authorities named in "
            "tests/conformance/projections.py. Every expected value in this repository "
            "is here, and none of it is hand-edited: a value typed by a person is a "
            "belief about the authority, which is the belief the checks exist to test."
        ),
        "facts": captured,
    }
    CAPTURE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(v) if isinstance(v, list) else 1 for v in captured.values())
    print(f"reqgen capture: {len(captured)} facts, {total} recorded values -> {_rel(CAPTURE_PATH)}")
    return 0


# ------------------------------------------------------------------ generation


_HEADER = '''\
# @generated by scripts/reqgen.py from metaobjects/meta.axi-core.yaml -- DO NOT EDIT.
#
# Regenerate with `python3.11 scripts/reqgen.py generate`; CI fails if this file and
# the declaration disagree. Editing it by hand is how a check stops matching the claim
# it was written for.
"""The declared requirements, as checks.

Each test below is one fact from ``metaobjects/meta.axi-core.yaml``, judged by the
relation its projection kind implies, against the value in ``capture.json`` -- which is
machine-written from the authorities and never edited. The docstring is the requirement
that asked for the check, and what breaking it looks like.

The last test is the one that makes the rest mean anything: it breaks every check in
turn and requires each to fail. A check that has never failed is not yet a check.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from conformance import projections, relations

CAPTURE = json.loads(
    (pathlib.Path(__file__).parent / "capture.json").read_text(encoding="utf-8")
)["facts"]

#: fact -> (relation, requirement paths). Read by the checks and by the vacuity test.
CHECKS = {
<<checks>>}

#: fact -> the subject, in the form its relation consumes: a value for `equal`, the
#: covered subset for `covers`, and the callable itself for `wire` and `differential`.
SUBJECTS = {
<<subjects>>}


def _judge(fact, subject=None, captured=None):
    relation = CHECKS[fact][0]
    if captured is None:
        captured = CAPTURE[fact]
    if subject is None:
        subject = SUBJECTS[fact](captured)
    problem = relations.RELATIONS[relation](subject, captured)
    if problem is not None:
        pytest.fail(f"{fact} ({relation}): {problem}", pytrace=False)


'''

_TEST = '''\
def test_<<function>>():
    """<<statement>>

    Requirement: <<path>> (<<sub_type>>, <<status>>).
    Breaking it looks like: <<counterexample>>
    """
    _judge("<<fact>>")


'''

_FOOTER = '''\
@pytest.mark.parametrize("fact", sorted(CHECKS))
def test_no_check_is_vacuous(fact):
    """Every check above fails when the thing it names is broken.

    The mutations come from the relation, not from this file: each relation knows what
    a violation of itself looks like, so a new fact gets a vacuity proof without anyone
    writing one. A relation that produced no mutation would let a check through
    unproven, so that is a failure too.
    """
    relation = CHECKS[fact][0]
    captured = CAPTURE[fact]
    subject = SUBJECTS[fact](captured)
    broken = list(relations.mutations(relation, subject, captured))
    assert broken, f"{fact} ({relation}): the relation offers no way to break it"
    for description, mutated_subject, mutated_capture in broken:
        problem = relations.RELATIONS[relation](mutated_subject, mutated_capture)
        assert problem is not None, (
            f"{fact} ({relation}): the check still passed when {description}. "
            "It is not testing what it claims to."
        )
'''

#: How each relation wants its subject handed over.
_SUBJECT_CALL = {
    "equal": "lambda captured: projections.{fn}()",
    "covers": "lambda captured: projections.{fn}(captured)",
    "wire": "lambda captured: projections.{fn}",
    "differential": "lambda captured: projections.{fn}",
}


def _fill(template: str, **values: str) -> str:
    """Substitute ``<<name>>`` tokens.

    Neither ``%`` nor ``str.format`` can be used on these templates: the emitted body
    is full of braces and percent signs of its own, and escaping them would make the
    template unreadable and the escaping itself a source of bugs.
    """
    for name, value in values.items():
        template = template.replace(f"<<{name}>>", value)
    return template


def render(facts: dict[str, Fact]) -> str:
    """The whole generated module, as text.

    Laid out so that the output is stable under formatting: one declaration per line,
    every reference on its own line, so a fact added or renamed moves exactly the lines
    it owns and a review diff says what changed.
    """
    ordered = sorted(
        facts.values(),
        key=lambda f: (list(RELATION_BY_OBJECT).index(f.object), f.name),
    )

    checks = []
    for fact in ordered:
        checks.append(f'    "{fact.name}": (\n')
        checks.append(f'        "{fact.relation}",\n')
        checks.append("        (\n")
        for req in _claims(fact):
            checks.append(f'            "{req.path}",\n')
        checks.append("        ),\n")
        checks.append("    ),\n")

    subjects = []
    for fact in ordered:
        call = _SUBJECT_CALL[fact.relation].format(fn=fact.subject_fn)
        subjects.append(f'    "{fact.name}": {call},\n')

    body = _fill(_HEADER, checks="".join(checks), subjects="".join(subjects))
    for fact in ordered:
        claims = _claims(fact)
        primary = claims[0]
        body += _fill(
            _TEST,
            function=snake(fact.name),
            statement=primary.statement,
            path=", ".join(req.path for req in claims),
            sub_type=primary.sub_type,
            status=primary.status,
            counterexample=primary.counterexample,
            fact=fact.name,
        )
    return body + _FOOTER


def _claims(fact: Fact) -> list:
    active = [req for req in fact.requirements if req.status in ACTIVE]
    return active or list(fact.requirements)


def do_generate(facts: dict[str, Fact]) -> int:
    GENERATED_PATH.write_text(render(facts), encoding="utf-8")
    print(f"reqgen generate: {len(facts)} checks -> {_rel(GENERATED_PATH)}")
    return 0


def do_check(facts: dict[str, Fact]) -> int:
    want = render(facts)
    if not GENERATED_PATH.exists():
        print(f"reqgen check: {_rel(GENERATED_PATH)} is missing; run `reqgen generate`")
        return 1
    have = GENERATED_PATH.read_text(encoding="utf-8")
    if have == want:
        print(f"reqgen check: {_rel(GENERATED_PATH)} is current ({len(facts)} checks)")
        return 0
    print(
        f"reqgen check: {_rel(GENERATED_PATH)} is not what the declaration produces.\n"
        "The declaration is the source of truth; run `reqgen generate` and commit the result."
    )
    return 1


def do_list(facts: dict[str, Fact], requirements: list) -> int:
    print(f"{'fact':34} {'relation':13} claimed by")
    for fact in sorted(facts.values(), key=lambda f: (f.object, f.name)):
        claims = ", ".join(req.path.rpartition(".")[2] for req in _claims(fact))
        print(f"{fact.name:34} {fact.relation:13} {claims}")
    counted = dict.fromkeys(("live", "partial", "planned", "abandoned", "superseded"), 0)
    for req in requirements:
        counted[req.status] = counted.get(req.status, 0) + 1
    print()
    print(f"{len(facts)} checks from {len(requirements)} requirements ({counted})")
    return 0


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("capture", "generate", "check", "list"))
    args = parser.parse_args(argv)

    try:
        facts, requirements = load_declaration()
        bind(facts, requirements)
    except DeclarationError as exc:
        print(f"reqgen: the declaration is not usable.\n{exc}", file=sys.stderr)
        return 1

    if args.command == "capture":
        return do_capture(facts)
    if args.command == "generate":
        return do_generate(facts)
    if args.command == "check":
        return do_check(facts)
    return do_list(facts, requirements)


if __name__ == "__main__":
    sys.exit(main())
