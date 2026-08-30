"""The three guarantees `vendor/conventional-commits-parser/PROVENANCE.md` claims.

Until this file existed they were claimed by prose and by nothing else. `PROVENANCE.md`
and `scripts/commitcheck.py` both named this module as the thing that asserted them, and
the refresh procedure printed a `pytest` invocation that collected zero tests -- an exit
status easy to read as a pass. The three:

1. **The two engines agree.** ``--engine node`` runs the vendored copy of the parser
   release-please actually runs; ``--engine python`` runs the transcription in
   ``commitcheck.py``. Every message below goes through both, and they must return the
   same verdict and, where they reject, the same line, column, offending token, valid
   tokens and message text. That agreement is the whole warrant for the transcription
   standing in on a machine with no ``node``.
2. **The vendored files are upstream's.** Every file `checksums.txt` records still hashes
   to its recorded SHA-256, and `checksums.txt` covers every vendored file -- a
   defence worth nothing if a file can be added beside it without an entry.
3. **``THROW_SITES`` is a measurement, not a memory.** The count in ``commitcheck.py``,
   the line numbers ``PROVENANCE.md`` prints, and the ``# lib/parser.js:NN`` markers on
   the transcription's four ``raise`` statements all have to match the ``throw``
   statements actually in the vendored ``lib/parser.js``.

**Two of the four throw sites are unreachable, and that is stated rather than hidden.**
``message()`` reaches ``lib/parser.js:17`` (no ``<summary>``) and, through every
production that reads a scope, ``lib/parser.js:177`` (a scope that never closes). It
cannot reach lines 30 or 48: both demand that ``newline()`` fail somewhere ``text()``
has just run, and ``text()`` consumes to a newline or to EOF, so the scanner is always
on one or at the other. A 300,000-message random search found nothing that reached
them either. The corpus therefore reaches two sites and says so; a refresh that made a
third reachable is a grammar change and fails here.

Node is not present everywhere -- that portability is the entire reason the
transcription exists -- so the parity cases skip when ``node`` is off ``PATH``. A skip
is not a pass, and a whole guarantee going unverified in CI must not be silent, so
``test_the_node_engine_is_available_under_ci`` fails rather than skips when ``CI`` is
set.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMMITCHECK = ROOT / "scripts" / "commitcheck.py"
VENDOR = ROOT / "vendor" / "conventional-commits-parser"
CHECKSUMS = VENDOR / "checksums.txt"
PROVENANCE = VENDOR / "PROVENANCE.md"
PARSER_JS = VENDOR / "lib" / "parser.js"

#: What lives in the vendored directory but is this repository's, not upstream's.
NOT_VENDORED = frozenset({PROVENANCE.name, CHECKSUMS.name})


def _load_commitcheck():
    """Import the script by path; it is a tool, not an installed module."""
    spec = importlib.util.spec_from_file_location("commitcheck", COMMITCHECK)
    module = importlib.util.module_from_spec(spec)
    sys.modules["commitcheck"] = module
    spec.loader.exec_module(module)
    return module


commitcheck = _load_commitcheck()

NODE_AVAILABLE = commitcheck.node_available()
requires_node = pytest.mark.skipif(
    not NODE_AVAILABLE,
    reason="node is off PATH, so the vendored parser cannot be run to compare against",
)


# ---------------------------------------------------------------------------
# Guarantee 2: the vendored files are still upstream's.
# ---------------------------------------------------------------------------


def _recorded_checksums():
    """``checksums.txt`` as ``sha256sum`` writes it: ``<digest>  <path>``."""
    recorded = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, separator, name = line.partition("  ")
        assert separator, f"not a sha256sum line: {line!r}"
        recorded[name.strip()] = digest.strip()
    return recorded


RECORDED = _recorded_checksums()


def _vendored_files():
    """Every file in the vendored directory that came from upstream."""
    return sorted(
        str(path.relative_to(VENDOR))
        for path in VENDOR.rglob("*")
        if path.is_file() and path.name not in NOT_VENDORED
    )


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_a_vendored_file_still_hashes_to_its_recorded_digest(name):
    path = VENDOR / name
    assert path.is_file(), f"{name} is recorded in checksums.txt but is not there"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == RECORDED[name], (
        f"{name} is no longer the file checksums.txt records. A vendored file edited to "
        "make the transcription look correct is no longer upstream's opinion; refresh the "
        "copy and the checksums together, in a commit that says so."
    )


def test_checksums_cover_every_vendored_file():
    """A file that arrives beside the recorded ones is unguarded until it is listed."""
    assert sorted(RECORDED) == _vendored_files()


def test_the_recorded_digests_are_sha256():
    for name, digest in RECORDED.items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{name}: {digest!r} is not a SHA-256"


# ---------------------------------------------------------------------------
# Guarantee 3: THROW_SITES is a measurement.
# ---------------------------------------------------------------------------

_THROW = re.compile(r"^\s*throw\b")
#: The transcription's markers: ``raise ...  # lib/parser.js:NN``.
_MARKER = re.compile(r"#\s*lib/parser\.js:(\d+)\s*$")

COMMITCHECK_SOURCE = COMMITCHECK.read_text(encoding="utf-8").splitlines()


def _throw_lines():
    """The 1-indexed lines of ``lib/parser.js`` holding a ``throw`` statement."""
    lines = PARSER_JS.read_text(encoding="utf-8").splitlines()
    return [number for number, line in enumerate(lines, 1) if _THROW.match(line)]


def _documented_throw_lines():
    """The line numbers ``PROVENANCE.md`` prints, read out of the prose itself."""
    prose = " ".join(PROVENANCE.read_text(encoding="utf-8").split())
    match = re.search(r"lines ((?:\d+, )+\d+ and \d+) of the vendored copy", prose)
    assert match, "PROVENANCE.md no longer names the throw lines in the shape read here"
    return [int(number) for number in re.findall(r"\d+", match.group(1))]


def _transcription_markers():
    """Every ``raise`` in the transcription that cites a line of the vendored parser."""
    markers = []
    for line in COMMITCHECK_SOURCE:
        match = _MARKER.search(line)
        if match and line.lstrip().startswith("raise "):
            markers.append(int(match.group(1)))
    return markers


def test_throw_sites_matches_the_vendored_parser():
    assert len(_throw_lines()) == commitcheck.THROW_SITES


def test_provenance_names_the_lines_that_actually_throw():
    assert _documented_throw_lines() == _throw_lines()


def test_the_transcription_cites_every_throw_site_exactly_once():
    """The port claims to raise where upstream throws. Hold it to the line numbers."""
    markers = _transcription_markers()
    assert len(markers) == commitcheck.THROW_SITES
    assert sorted(markers) == _throw_lines()


# ---------------------------------------------------------------------------
# Guarantee 1: the corpus, and the two engines over it.
# ---------------------------------------------------------------------------

#: Shapes that separate a faithful port from a plausible one. None of them is in
#: the demo corpus, and every one of them is a place a transcription drifts: what
#: JavaScript trims, how it counts a column, what it calls one token. Written as
#: escapes rather than literals so this file stays ASCII and the two engines are
#: handed exactly the bytes named here.
ZWNBSP = "\ufeff"
NBSP = "\u00a0"

TRANSCRIPTION_PROBES = {
    "an unclosed scope in the summary": "fix(scope: subject\n",
    "a scope that runs to the end of the message": "fix(scope",
    "an empty message": "",
    "whitespace and newlines only": "   \n\n  ",
    "a message that is one ZWNBSP": ZWNBSP,
    "a leading ZWNBSP, which JavaScript trims and str.strip does not": (
        ZWNBSP + "fix: a subject\n\na(b\n"
    ),
    "a leading NBSP": NBSP + "fix: a subject\n",
    "a leading U+2028 line separator": "\u2028fix: a subject\n\na(b\n",
    "a leading ideographic space": "\u3000fix: a subject\n\na(b\n",
    "CRLF line endings throughout": "fix: a subject\r\n\r\na(b\r\n",
    "lone CR line endings": "fix: a subject\r\ra(b\r",
    "CR, LF and CRLF mixed in one message": "fix: a subject\r\n\ra(b\n",
    "an NBSP where the separator belongs": "fix" + NBSP + ": a subject\n",
    "a form feed inside the summary's whitespace": "fix:\u000ca subject\n",
    "a vertical tab inside the summary's whitespace": "fix:\u000ba subject\n",
    "an empty scope in the summary": "fix(): subject\n",
    "a closing parenthesis before any opening one": "fix): subject\n",
    "a bang with no colon": "fix! subject\n",
    "a colon at the very start": ":subject\n",
    "a body line closing its parenthesis only after another opens": "fix: s\n\na(b(c)\n",
    "a nested commit block whose inner commit is unparseable": (
        "fix: outer\n\nbody\n\nBEGIN_NESTED_COMMIT\nfix: inner\n\na(b\nEND_NESTED_COMMIT\n"
    ),
    "a BREAKING CHANGE footer followed by an unclosed parenthesis": (
        "feat: s\n\nbody\n\nBREAKING CHANGE: the flag moved\na(b\n"
    ),
    "trailing whitespace after the offending line": "fix: a subject\n\na(b\n\n\n   ",
    "a tab-indented continuation line": "fix: s\n\nbody\n\nRefs: #10\n\ta(b\n",
    "a footer using the ' #' separator": "fix: s\n\nbody\n\nRefs #10\n",
    "an unclosed parenthesis on a CRLF body line": "fix: s\r\n\r\nrows_for(id\r\nis needed\r\n",
    "a combining mark before the parenthesis": "fix: s\n\n\u00e9a(b\n",
    # An astral character is two UTF-16 code units to JavaScript and one code
    # point to Python, so every column after it on the line -- and the token the
    # parser names when it stops on one -- depends on the transcription counting
    # the way upstream counts. These are the cases that proved it did not.
    "an emoji before the offending parenthesis": "fix: s\n\n\U0001f600a(b\n",
    "an emoji in the summary before an unclosed scope": "fix\U0001f600(scope: s\n",
    "an emoji inside the scope itself": "fix(\U0001f600: s\n",
    "an emoji as the offending token": "b!\U0001f600b#\n",
    "the lowest astral code point": "fix: s\n\n\U00010000a(b\n",
}

#: The alphabet the sweep below draws from: every character class the grammar
#: branches on, plus the ones the two languages disagree about.
SWEEP_ALPHABET = (
    "a",
    "b",
    "(",
    ")",
    ":",
    "!",
    " ",
    "\t",
    "\n",
    "\r",
    "\r\n",
    "#",
    "-",
    ZWNBSP,
    NBSP,
    "\u2028",
    "\u3000",
    "\u000b",
    "\u000c",
    "\u00e9",
    "\U0001f600",
    "\U00010000",
    "BREAKING CHANGE",
    "BREAKING-CHANGE",
    "fix",
    "feat",
)

#: Deterministic, so a failure reproduces. Small, because every case costs one
#: `node` process; it is the generative half of the corpus, not a fuzzer.
SWEEP_SEED = 20260830
SWEEP_SIZE = 120


def _sweep():
    generator = random.Random(SWEEP_SEED)
    for index in range(SWEEP_SIZE):
        length = generator.randint(1, 10)
        yield (
            f"sweep {index:03d}",
            "".join(generator.choice(SWEEP_ALPHABET) for _ in range(length)),
        )


def _pull_request_artefacts():
    """The two texts a pull request hands release-please; neither is the message."""
    for source in (
        commitcheck.DEMO_PULL_REQUESTS_REJECTED,
        commitcheck.DEMO_PULL_REQUESTS_ACCEPTED,
    ):
        for label, (title, number, body) in source.items():
            block = commitcheck.override_block(body)
            if block is not None:
                yield f"override block: {label}", block
            yield f"title subject: {label}", f"{title} (#{number})"


def _corpus():
    """Every message this repository writes down, plus the shapes a port drifts on."""
    for label, message in commitcheck.DEMO_REJECTED.items():
        yield f"rejected: {label}", message
    for label, message in commitcheck.DEMO_ACCEPTED.items():
        yield f"accepted: {label}", message
    yield from _pull_request_artefacts()
    for label, message in TRANSCRIPTION_PROBES.items():
        yield f"probe: {label}", message
    yield from _sweep()


CORPUS = list(_corpus())

#: release-please parses `splitMessages(...)` and each part fails on its own, so
#: the part is the unit both engines are compared over.
CORPUS_PARTS = [
    (f"{label} [{index}]", part)
    for label, message in CORPUS
    for index, part in enumerate(commitcheck.split_messages(message))
]


def _fields(error):
    """Everything upstream reports, so the two are compared field by field."""
    if error is None:
        return None
    return (error.line, error.column, error.found, tuple(error.valid), str(error))


@pytest.mark.parametrize(
    "part", [part for _, part in CORPUS_PARTS], ids=[label for label, _ in CORPUS_PARTS]
)
@requires_node
def test_both_engines_agree_on_this_part(part):
    """The claim that lets the transcription stand in for the vendored parser."""
    transcription = _fields(commitcheck.parse_part(part, engine="python"))
    vendored = _fields(commitcheck.parse_part(part, engine="node"))
    assert transcription == vendored, (
        "the transcription and the vendored parser disagree about "
        f"{part!r}: python={transcription!r} node={vendored!r}"
    )


def test_the_corpus_is_not_quietly_empty():
    """A parity sweep over nothing passes. Pin the corpus against that."""
    assert len(CORPUS) >= len(TRANSCRIPTION_PROBES) + SWEEP_SIZE
    assert len(CORPUS_PARTS) >= len(CORPUS)
    assert any(commitcheck.parse_part(part, engine="python") is None for _, part in CORPUS_PARTS)
    assert any(
        commitcheck.parse_part(part, engine="python") is not None for _, part in CORPUS_PARTS
    )


def _throw_site(error):
    """Which ``throw`` of the vendored parser this rejection corresponds to."""
    lineno = None
    traceback = error.__traceback__
    while traceback is not None:
        if Path(traceback.tb_frame.f_code.co_filename) == COMMITCHECK:
            lineno = traceback.tb_lineno
        traceback = traceback.tb_next
    assert lineno is not None, f"no commitcheck frame in the traceback for {error}"
    match = _MARKER.search(COMMITCHECK_SOURCE[lineno - 1])
    assert match, (
        f"commitcheck.py:{lineno} raises without naming the throw site it transcribes: "
        f"{COMMITCHECK_SOURCE[lineno - 1].strip()!r}"
    )
    return int(match.group(1))


def test_the_corpus_reaches_every_throw_site_the_grammar_can_reach():
    """Two of the four are unreachable through ``message()``; see the module docstring."""
    reached = set()
    for _, part in CORPUS_PARTS:
        error = commitcheck.parse_part(part, engine="python")
        if error is not None:
            reached.add(_throw_site(error))
    assert reached == {17, 177}, (
        "the corpus reaches a different set of throw sites than it did. Lines 30 and 48 "
        "cannot be reached because text() always leaves the scanner on a newline or at "
        "EOF; if one of them is reachable now, the grammar changed and the transcription "
        "has to be re-read."
    )


@requires_node
def test_the_vendored_parser_rejects_and_accepts_the_demo_corpus():
    """``--demo`` under the authority: what the corpus's own labels claim is true of it."""
    stream = io.StringIO()
    assert commitcheck.run_demo("node", stream=stream) == 0, stream.getvalue()


def test_the_transcription_alone_rejects_and_accepts_the_demo_corpus():
    """The half that has to hold up on a machine with no ``node``, where nothing skips."""
    stream = io.StringIO()
    assert commitcheck.run_demo("python", stream=stream) == 0, stream.getvalue()


def test_a_report_survives_a_token_no_stream_can_encode():
    """Upstream names an astral character by its leading surrogate, which is unencodable.

    Both engines now report that token, so both would have replaced the report with a
    ``UnicodeEncodeError`` traceback. The message is still refused either way -- it
    fails closed -- but the person who has to fix it learns nothing from a traceback.
    """
    message = "b!\U0001f600b#\n"
    for engine in ("node", "python") if NODE_AVAILABLE else ("python",):
        problems = commitcheck.check(message, engine=engine)
        assert problems, f"{engine} accepted a message the grammar refuses"
        stream = io.StringIO()
        commitcheck.report(problems, "a message", stream=stream)
        rendered = stream.getvalue()
        rendered.encode("utf-8")  # raises if an unpaired surrogate reached the report
        assert "\\ud83d" in rendered, f"{engine} did not name the leading surrogate"


# ---------------------------------------------------------------------------
# A guarantee nobody can verify must not look verified.
# ---------------------------------------------------------------------------


def test_the_node_engine_is_available_under_ci():
    """A skipped agreement check reads exactly like a passing one.

    Locally, ``node`` may legitimately be absent -- standing in for it is what the
    transcription is for -- and the parity cases skip. In CI the guarantee has to be
    actually verified, so its absence is a failure rather than a quiet ``s``.
    """
    if not os.environ.get("CI"):
        pytest.skip("not CI; the parity cases skip on their own when node is off PATH")
    assert NODE_AVAILABLE, (
        "node is off PATH, so nothing here compared the transcription against the "
        "vendored parser. Install node in this job (actions/setup-node) rather than "
        "letting the whole guarantee pass as a skip."
    )
