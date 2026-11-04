"""The language-neutral conformance pack in ``conformance/``, held to the implementation.

The pack is what a second implementation (a package in another language, in this
repository or elsewhere) judges itself against, so it has two obligations. It must
not drift from Python: the first test regenerates every file and requires the committed
bytes. And it must not merely agree with Python: wherever the committed capture holds
the same fact -- captured from the two source tools, not computed here -- the pack is
compared with the capture directly.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from axi_toolkit import redact
from axi_toolkit.errors import Recovery
from axi_toolkit.render import cli
from conformance import pack, projections, specs

PACK = pack.PACK_DIR


def _load(name: str):
    return json.loads((PACK / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built():
    return pack.build()


@pytest.fixture(autouse=True)
def _clean_redactor():
    redact.reset()
    yield
    redact.reset()


# ---------------------------------------------------------------- no drift


def test_the_committed_pack_is_what_the_implementation_produces(built):
    """Regenerate and compare, byte for byte. `scripts/conformance_pack.py` fixes a red one."""
    for name, text in built.items():
        committed = (PACK / name).read_text(encoding="utf-8")
        assert committed == text, f"conformance/{name} is stale: run scripts/conformance_pack.py"


def test_no_file_in_the_pack_is_unaccounted_for(built):
    on_disk = {p.name for p in PACK.iterdir() if p.is_file()}
    assert on_disk == set(built) | {"README.md"}


def test_the_checksums_match_the_files():
    lines = (PACK / "checksums.txt").read_text(encoding="utf-8").splitlines()
    assert lines, "checksums.txt is empty"
    listed = set()
    for entry in lines:
        digest, _, name = entry.partition("  ")
        listed.add(name)
        assert hashlib.sha256((PACK / name).read_bytes()).hexdigest() == digest, name
    assert listed == {p.name for p in PACK.glob("*.json")}


def test_the_pack_is_deterministic(built):
    assert pack.build() == built


# ------------------------------------------------- agreement with the capture


def test_the_recovery_corpus_is_the_capture_corpus():
    facts = json.loads(pack.CAPTURE.read_text(encoding="utf-8"))["facts"]
    entries = _load("recovery.json")["entries"]
    for key, tool in (("haRecoveryLines", "hass-axi"), ("plexRecoveryLines", "plex-axi")):
        assert [e["line"] for e in entries if e["tool"] == tool] == [
            row["case"] for row in facts[key]
        ]


def test_every_corpus_entry_round_trips_and_names_no_tool_it_was_not_handed():
    corpus = _load("recovery.json")
    assert len(corpus["entries"]) > 300
    for entry in corpus["entries"]:
        intent = Recovery.from_dict(entry["intent"])
        assert intent.as_dict() == entry["intent"]
        assert cli.line(intent, entry["tool"]) == entry["line"]
        assert entry["tool"] not in entry["other"]["line"]
        assert entry["tool"] not in entry["other"]["sentence"]


def test_the_credential_pack_matches_the_captured_messages():
    facts = json.loads(pack.CAPTURE.read_text(encoding="utf-8"))["facts"]
    credentials = _load("credentials.json")["tools"]
    for key, tool in (("haCredentialMessages", "hass-axi"), ("plexCredentialMessages", "plex-axi")):
        captured = {row["case"]: row["expected"] for row in facts[key]}
        scenarios = {case["name"]: case["expected"] for case in credentials[tool]["failures"]}
        assert set(scenarios) == set(captured)
        for name, expected in scenarios.items():
            rendered = "\n".join(
                [expected["message"], *(f"  {item}" for item in expected["lines"])]
            )
            assert rendered == captured[name], (tool, name)


def test_the_credential_pack_matches_the_captured_urls():
    facts = json.loads(pack.CAPTURE.read_text(encoding="utf-8"))["facts"]
    credentials = _load("credentials.json")["tools"]
    for key, tool in (("haNormalizedUrls", "hass-axi"), ("plexNormalizedUrls", "plex-axi")):
        assert [(c["raw"], c["expected"]) for c in credentials[tool]["normalized_urls"]] == [
            (row["case"], row["expected"]) for row in facts[key]
        ]


def test_the_redaction_pack_matches_the_captured_samples():
    facts = json.loads(pack.CAPTURE.read_text(encoding="utf-8"))["facts"]
    captured = {row["case"]: row["expected"] for row in facts["redactionSamples"]}
    tools = _load("redaction.json")["tools"]
    seen = set()
    for key, tool in (("ha", "hass-axi"), ("plex", "plex-axi")):
        for case in tools[tool]["cases"]:
            seen.add(f"{key}|{case['name']}")
            assert case["expected"] == captured[f"{key}|{case['name']}"]
            # The segments rebuild exactly the text the capture was taken over.
            assert pack.render_segments(case["input"]) == projections._sample_text(case["name"])
    assert seen == set(captured)


def test_the_redaction_pack_names_the_patterns_the_tools_run():
    facts = json.loads(pack.CAPTURE.read_text(encoding="utf-8"))["facts"]
    rules = [row.split("|", 2) for row in facts["redactionRules"]]
    tools = _load("redaction.json")["tools"]
    for key, tool in (("ha", "hass-axi"), ("plex", "plex-axi")):
        sources = [src for t, _, src in rules if t == key]
        # The capture lists the bearer rule first and the token rule last.
        assert sources[1:-1] == list(specs.PATTERNS[key])
        assert [p["source"] for p in tools[tool]["patterns"]] == [
            pack.es_pattern(src)["source"] for src in sources[1:-1]
        ]


# ----------------------------------------- the pack is readable by another engine


def test_no_pack_file_carries_a_credential_shape_or_a_python_regex_flag():
    """Inputs are recipes; patterns are ECMAScript. Both are properties of the files."""
    for path in PACK.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        # The token *pattern* legitimately contains `eyJ`; a token never does.
        assert not re.search(r"eyJ[A-Za-z0-9_-]{4,}\.", text.replace("\\.", ".")), path.name
        assert "(?i)" not in text, path.name


def test_each_ecmascript_pattern_behaves_like_the_python_one_it_came_from():
    """The translation may only drop `(?i)` and an escaped quote; prove it changed nothing."""
    probes = [
        "Authorization: Bearer " + "abcdef" + "123456" + "ghijkl",
        "http://host.example.com/x?token=abcdef1234&authsig=abcdef1234",
        "http://host.example.com:32400/art?X-Plex-Token=plex0123456789abcdef",
        "X-Plex-Token: plex0123456789abcdef",
        'X-Plex-Token="plex0123456789abcdef"',
        "https://host.example.com/s?access_token=ab\"cd'ef<gh>&v=2",
        "nothing here",
    ]
    for source in [*specs.HA_PATTERNS, *specs.PLEX_PATTERNS, redact.BEARER.pattern]:
        translated = pack.es_pattern(source)
        assert translated["flags"] in ("u", "iu"), source
        flags = re.IGNORECASE if "i" in translated["flags"] else 0
        rebuilt = re.compile(translated["source"], flags)
        original = re.compile(source)
        for probe in probes:
            assert rebuilt.sub("#", probe) == original.sub("#", probe), (source, probe)


def test_es_pattern_refuses_a_construct_it_cannot_translate():
    with pytest.raises(ValueError):
        pack.es_pattern("(?P<name>x)")
    with pytest.raises(ValueError):
        pack.es_pattern("(?s)x")


def test_a_hand_written_run_without_a_lead_renders_without_a_leading_space():
    for case in _load("render-rules.json")["hand_written"]:
        for rendered in case["renders"].values():
            assert not rendered["line"].startswith(" "), case["name"]
            assert not rendered["sentence"].startswith(" "), case["name"]


def test_the_toon_pointer_resolves_to_the_vendored_fixtures():
    pointer = _load("toon-spec.json")
    for key in ("fixtures", "checksums", "license", "provenance"):
        assert (PACK / pointer[key]).exists(), key
    fixtures = sorted((PACK / pointer["fixtures"]).glob("*.json"))
    assert len(fixtures) == 9
    listed = {
        line.partition("  ")[2]
        for line in (PACK / pointer["checksums"]).read_text(encoding="utf-8").splitlines()
    }
    assert listed == {p.name for p in fixtures}


def test_the_exit_codes_and_classes_in_the_pack_are_the_modules():
    data = _load("errors.json")
    assert data["classes"] == [
        "usage", "config", "transport", "auth",
        "permission", "not_found", "refused", "internal",
    ]  # fmt: skip
    assert data["exit_codes"] == {"EXIT_OK": 0, "EXIT_ERROR": 1, "EXIT_USAGE": 2}
    assert {e["name"] for e in data["exceptions"]} == {
        "AxiError", "UsageError", "ConfigError", "ConnectionFailed",
        "AuthFailed", "Forbidden", "NotFound", "ApiError",
    }  # fmt: skip
