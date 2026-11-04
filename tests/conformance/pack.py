"""The language-neutral conformance pack, built from the Python implementation.

``conformance/`` at the repository root is plain JSON that any implementation of the
toolkit's contract can read in place and judge itself against. This module is the only
thing that writes it: :func:`build` returns every file's text, ``scripts/conformance_pack.py``
writes them, and ``tests/test_conformance_pack.py`` regenerates them and requires the
committed bytes to match, so the pack cannot drift from Python.

Where the expectations come from, and why that is not circular. The *inputs* are the
corpus the capture already holds (the recovery lines both source tools print), the two
tools' credential declarations in ``specs.py``, and the scenario tables in
``projections.py``. The *expectations* are what this package computes from them. The
capture pins this package to the tools, so a pack value that disagreed with the tools
would already be a red ``tests/conformance`` check; ``test_conformance_pack.py`` also
compares the pack against the capture directly wherever the capture carries the same
fact, so a pack that merely agreed with the code and not with the tools would fail too.

Nothing here writes a credential-shaped literal. A redaction input is a list of segments,
a string or a reference to a named fragment, and a fragment is a recipe (parts to join,
or JSON texts to base64url-encode into a token) that the reading implementation
assembles at run time -- the same rule ``tests/test_redact.py`` follows, for the same
reason: the leak scanner joins a file before it scans it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from axi_toolkit import envconfig, errors, redact
from axi_toolkit.errors import choose, note, retry, run, set_env
from axi_toolkit.render import cli, prose

from . import projections, specs

__all__ = ["PACK_DIR", "build", "checksums", "es_pattern", "render_segments"]

ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = ROOT / "conformance"
CAPTURE = Path(__file__).resolve().with_name("capture.json")

#: The two source tools' command names, which is what the corpus is parsed and rendered
#: under, and a name no tool in the corpus uses, which is how "the name is not stored"
#: stays checkable in a reader that has never seen a tool.
TOOLS = {"ha": "hass-axi", "plex": "plex-axi"}
SIBLING = "other-tool"
VERSION = 1


# ------------------------------------------------------------------ plumbing


def _dump(document) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _capture_facts() -> dict:
    return json.loads(CAPTURE.read_text(encoding="utf-8"))["facts"]


def _header(topic: str) -> dict:
    return {
        "pack": "axi-toolkit-conformance",
        "version": VERSION,
        "topic": topic,
        "generated_by": "scripts/conformance_pack.py",
    }


def _render_pair(recovery, tool: str) -> dict:
    return {"line": cli.line(recovery, tool), "sentence": prose.sentence(recovery, tool)}


# ------------------------------------------------------------------ recovery


def _recovery_corpus() -> dict:
    """Every literal recovery line either source tool emits, as intent and as text."""
    facts = _capture_facts()
    entries = []
    for key, tool in (("haRecoveryLines", TOOLS["ha"]), ("plexRecoveryLines", TOOLS["plex"])):
        for row in facts[key]:
            line = row["case"]
            intent = cli.parse(line, tool)
            entries.append(
                {
                    "tool": tool,
                    "line": line,
                    "intent": intent.as_dict(),
                    "sentence": prose.sentence(intent, tool),
                    # The same intent rendered for a tool the corpus never saw. A line
                    # that still names `tool` here has stored the name.
                    "other": _render_pair(intent, SIBLING),
                }
            )
    return {
        **_header("recovery"),
        "description": (
            "Each source line, parsed under its tool's name into the wire form of a "
            "recovery. A conforming implementation parses `line` under `tool` and gets "
            "`intent`, renders `intent` back to `line`, renders it as `sentence` for the "
            "same tool, and renders it as `other` for the sibling tool named in `sibling`."
        ),
        "sibling": SIBLING,
        "entries": entries,
    }


# ------------------------------------------------------------- render rules

#: One recovery per rendering rule, so a reader can see the rule it is checking. The
#: list is deliberately the union of the cases the three Python suites state by hand.
_RULE_RECOVERIES = (
    ("run, bare", run(("doctor",))),
    ("run, with a purpose", run(("area", "list"), purpose="to see each area's id")),
    ("run, a flag as the first word", run(("--help",), purpose="for the full reference")),
    ("run, custom lead", run(("--timeout", "60", "<command>"), lead="Raise the limit with")),
    (
        "run, colon separator",
        run(
            ("doctor",),
            purpose="a library that has not finished scanning has no metadata",
            separator=": ",
        ),
    ),
    ("run, separator without a purpose", run(("doctor",), separator=".")),
    (
        "run, purpose naming a variable",
        run(("doctor",), purpose="to check HA_URL reaches Home Assistant"),
    ),
    ("retry, default lead", retry("--limit 50")),
    (
        "retry, custom lead and purpose",
        retry("--debug", purpose="for a diagnostic trace on stderr", lead="Re-run with"),
    ),
    ("retry, custom lead", retry("--path <dir>", lead="Pass a writable repository root with")),
    (
        "set_env, with an example",
        set_env(
            "HA_URL",
            "your Home Assistant base URL",
            example="export HA_URL=https://host.example.com",
        ),
    ),
    (
        "set_env, with a reference",
        set_env(
            "PLEX_TOKEN", "a Plex access token", reference="https://support.example.com/tokens"
        ),
    ),
    ("set_env, bare", set_env("HA_TOKEN", "a long-lived access token")),
    (
        "set_env, example and reference",
        set_env(
            "EXAMPLE_TOKEN",
            "an access token",
            example="export EXAMPLE_TOKEN=value",
            reference="https://docs.example.com/tokens",
        ),
    ),
    ("choose", choose("did you mean", ("light.turn_on", "light.turn_off"))),
    ("choose, one value", choose("one of", ("a",))),
    ("note, plain", note("Retry the command; a dropped connection is often a one-off")),
    ("note, with the tool slot", note("This is a bug in {tool}; the command did not complete")),
    ("note, slot at the start", note("{tool} could not finish")),
    ("note, two slots", note("{tool} and {tool}")),
    ("note, ends with a full stop", note("Nothing was sent to the server.")),
    ("note, ends with a question mark", note("Which of these did you mean?")),
    ("note, ends with a colon", note("Two things are wrong here:")),
)

#: Wire-form inputs written by hand rather than produced by a factory. The first group is
#: the contract hole: an absent `lead` on a run or retry takes the factory default.
_HAND_WRITTEN = (
    ("run, no lead", {"kind": "run", "args": ["x"]}),
    ("run, no lead, with a purpose", {"kind": "run", "args": ["x"], "purpose": "to see y"}),
    ("retry, no lead", {"kind": "retry", "fragment": "--x"}),
    ("retry, no lead, with a purpose", {"kind": "retry", "fragment": "--x", "purpose": "for z"}),
    ("run, lead given", {"kind": "run", "args": ["x"], "lead": "Raise the limit with"}),
    ("note, text key", {"kind": "note", "text": "hello {tool}"}),
    ("set_env, fields in any order", {"variable": "V", "kind": "set_env", "describes": "d"}),
    ("choose, values as an array", {"kind": "choose", "label": "l", "values": ["a", "b"]}),
)

#: Wire-form inputs a reader must refuse, and why. The reason is for the human reading a
#: failure; the contract is only that these are refused.
_REJECTED = (
    ("unknown kind", {"kind": "incantation"}),
    ("no kind", {"args": ["x"]}),
    ("run without arguments", {"kind": "run", "args": []}),
    ("run without the args key", {"kind": "run"}),
    ("retry without a fragment", {"kind": "retry"}),
    ("set_env without a variable", {"kind": "set_env", "describes": "d"}),
    ("set_env without a description", {"kind": "set_env", "variable": "V"}),
    ("choose without values", {"kind": "choose", "label": "l"}),
    ("choose without a label", {"kind": "choose", "values": ["a"]}),
    ("note without text", {"kind": "note"}),
    ("note with a second placeholder", {"kind": "note", "text": "a {count} of things"}),
    ("a note carrying a run field", {"kind": "note", "text": "t", "args": ["x"]}),
    ("a run carrying a set_env field", {"kind": "run", "args": ["x"], "variable": "V"}),
    ("a retry carrying args", {"kind": "retry", "fragment": "--x", "args": ["x"]}),
    ("an unknown field", {"kind": "run", "args": ["x"], "bogus": "y"}),
)

#: Lines handed to the shell parser by hand. `kind` is the kind the intent must have.
_PARSE_CASES = (
    "Run `hass-axi area list` to see each area's id",
    "Raise the limit with `hass-axi --timeout 60 <command>`",
    "Every local client still works without it: run `hass-axi clients`",
    "Run the command again with `--limit 50`",
    "Pass a writable repository root with `--path <dir>`",
    "Set HA_URL to your base URL, e.g. export HA_URL=https://host.example.com",
    "Retry the command; a dropped connection is often a one-off",
    "usage: hass-axi [command] [subcommand] [args] [flags]",
    "Run `hass-axi rate --help` or `hass-axi playlist --help` for the writes on offer",
    "Install it with `pip install 'hass-axi'` or `pip install websockets`",
    "`--flag` at the very start",
    "units: s seconds, m minutes, h hours",
    "Run `hass-axi doctor`.",
)

#: Lines the parser refuses, because an empty suggestion occupies the slot of the fix.
_PARSE_REFUSED = ("", "   ", "\n")


def _render_rules() -> dict:
    cases = []
    for name, recovery in _RULE_RECOVERIES:
        cases.append(
            {
                "name": name,
                "recovery": recovery.as_dict(),
                "mentions_tool": errors.mentions_tool(recovery),
                "renders": {
                    tool: _render_pair(recovery, tool) for tool in (TOOLS["ha"], TOOLS["plex"])
                },
            }
        )

    hand_written = []
    for name, wire in _HAND_WRITTEN:
        recovery = errors.Recovery.from_dict(wire)
        hand_written.append(
            {
                "name": name,
                "input": wire,
                "recovery": recovery.as_dict(),
                "renders": {TOOLS["ha"]: _render_pair(recovery, TOOLS["ha"])},
            }
        )

    rejected = []
    for name, wire in _REJECTED:
        try:
            errors.Recovery.from_dict(wire)
        except (ValueError, TypeError):
            rejected.append({"name": name, "input": wire})
        else:  # pragma: no cover - a case that is not refused is not a case
            raise AssertionError(f"rejected case {name!r} was accepted")

    parse_cases = []
    for text in _PARSE_CASES:
        intent = cli.parse(text, TOOLS["ha"])
        parse_cases.append(
            {
                "tool": TOOLS["ha"],
                "line": text,
                "intent": intent.as_dict(),
                "renders_back": cli.line(intent, TOOLS["ha"]),
            }
        )
    for text in _PARSE_REFUSED:
        try:
            cli.parse(text, TOOLS["ha"])
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"{text!r} was parsed")

    return {
        **_header("render-rules"),
        "description": (
            "`cases`: render `recovery` for each tool in `renders` and compare `line` "
            "(shell) and `sentence` (prose). `hand_written`: a wire form a person wrote; "
            "normalise it (`recovery` is the result) and render it. `rejected`: wire forms "
            "that must be refused. `parse`: shell lines and the intent they parse to; "
            "`parse_refused`: lines that must be refused."
        ),
        "cases": cases,
        "hand_written": hand_written,
        "rejected": rejected,
        "parse": parse_cases,
        "parse_refused": list(_PARSE_REFUSED),
    }


# -------------------------------------------------------------------- errors


def _errors_pack() -> dict:
    table = {
        "UNREACHABLE": errors.CLASS_TRANSPORT,
        "UNAUTHORIZED": errors.CLASS_AUTH,
        "NO_SUCH_AREA": errors.CLASS_NOT_FOUND,
    }
    exceptions = (
        errors.AxiError,
        errors.UsageError,
        errors.ConfigError,
        errors.ConnectionFailed,
        errors.AuthFailed,
        errors.Forbidden,
        errors.NotFound,
        errors.ApiError,
    )
    samples = (
        ("a bare message", errors.AxiError("something went wrong"), None),
        (
            "a code and one recovery",
            errors.NotFound(
                "no area named 'nowhere'",
                code="NO_SUCH_AREA",
                recovery=[run(("area", "list"), purpose="to see the areas that exist")],
            ),
            "NO_SUCH_AREA",
        ),
        (
            "several kinds of recovery, in order",
            errors.ConfigError(
                "HA_URL is not set in the environment",
                code="NOT_CONFIGURED",
                recovery=[
                    set_env("HA_URL", "your base URL"),
                    retry("--limit 50"),
                    choose("did you mean", ("a", "b")),
                    note("then look at the log"),
                ],
            ),
            "NOT_CONFIGURED",
        ),
    )
    return {
        **_header("errors"),
        "description": (
            "The closed vocabulary around the recovery data: exit codes, fault classes, the "
            "exception hierarchy's names and exit codes, fail-closed classification, and the "
            "JSON wire form of an error."
        ),
        "exit_codes": {
            "EXIT_OK": errors.EXIT_OK,
            "EXIT_ERROR": errors.EXIT_ERROR,
            "EXIT_USAGE": errors.EXIT_USAGE,
        },
        "kinds": list(errors.KINDS),
        "tool_slot": errors.TOOL_SLOT,
        "classes": list(errors.CLASSES),
        "unclassified": errors.CLASS_UNCLASSIFIED,
        "exceptions": [{"name": cls.__name__, "exit_code": cls.exit_code} for cls in exceptions],
        "fault_classes": {
            "table": table,
            "cases": [
                {"code": code, "expected": errors.fault_class(code, table)}
                for code in (
                    "UNREACHABLE",
                    "UNAUTHORIZED",
                    "NO_SUCH_AREA",
                    "NEVER_DECLARED",
                    "",
                    None,
                )
            ],
        },
        "error_dicts": [
            {
                "name": name,
                "exception": type(raised).__name__,
                "message": raised.message,
                "code": code,
                "recovery": [item.as_dict() for item in raised.recovery],
                "expected": raised.as_dict(),
            }
            for name, raised, code in samples
        ],
    }


# --------------------------------------------------------------- credentials


def _spec_data(spec: envconfig.CredentialSpec) -> dict:
    return {
        "url_vars": list(spec.url_vars),
        "token_vars": list(spec.token_vars),
        "setup": [item.as_dict() for item in spec.setup],
        "verify": spec.verify.as_dict() if spec.verify else None,
        "token_recovery": [item.as_dict() for item in spec.token_recovery],
        "default_scheme": spec.default_scheme,
        "default_port": spec.default_port,
        "strip_path_suffix": spec.strip_path_suffix,
        "default_timeout": spec.default_timeout,
    }


def _scenario_input(tool: str, scenario: str):
    """The operation and inputs of one failure scenario, as plain data."""
    spec = specs.SPECS[tool]
    url_var, token_var = spec.url_vars[0], spec.token_vars[0]
    url = "http://host.example.com:32400" if tool == "plex" else "https://host.example.com"
    head, _, detail = scenario.partition(":")
    if head == "missing":
        environ = {}
        if detail == "url":
            environ = {token_var: projections._PROBE_TOKEN}
        elif detail == "token":
            environ = {url_var: url}
        return {"operation": "load", "environ": environ}
    if head == "blank":
        return {
            "operation": "load",
            "environ": {url_var: "  ", token_var: projections._PROBE_TOKEN},
        }
    if head == "bad_token":
        bad = f"abc{projections._BAD_TOKEN_CHAR[detail]}def"
        return {"operation": "load", "environ": {url_var: url, token_var: bad}}
    raw = {"empty": "", "scheme": "ftp://host.example.com", "no-netloc": "://nope"}[detail]
    return {"operation": "normalize_base_url", "raw": raw}


def _run_scenario(tool: str, case: dict):
    spec = specs.SPECS[tool]
    if case["operation"] == "load":
        return envconfig.load(spec, dict(case["environ"]))
    return envconfig.normalize_base_url(case["raw"], spec)


def _failure(tool: str, case: dict) -> dict:
    try:
        _run_scenario(tool, case)
    except errors.AxiError as exc:
        return {
            "message": exc.message,
            "code": exc.code,
            "recovery": [item.as_dict() for item in exc.recovery],
            "lines": cli.lines(exc.recovery, TOOLS[tool]),
        }
    raise AssertionError(f"{tool} scenario {case!r} did not fail")  # pragma: no cover


def _load_ok_cases(tool: str) -> list[dict]:
    spec = specs.SPECS[tool]
    first_url, first_token = spec.url_vars[0], spec.token_vars[0]
    last_url, last_token = spec.url_vars[-1], spec.token_vars[-1]
    url = "http://host.example.com:32400" if tool == "plex" else "https://host.example.com"
    probe = projections._PROBE_TOKEN
    inputs = (
        ("the preferred names", {first_url: url, first_token: probe}, None),
        ("the last alias of each", {last_url: url, last_token: probe}, None),
        (
            "a bare host and padded values",
            {first_url: "  host.example.com  ", first_token: f" {probe} "},
            None,
        ),
        ("an explicit timeout", {first_url: url, first_token: probe}, 5.5),
        (
            "a preferred name that is blank falls through to the alias",
            {first_url: "   ", last_url: url, first_token: probe},
            None,
        ),
    )
    cases = []
    for name, environ, timeout in inputs:
        loaded = envconfig.load(spec, dict(environ), timeout=timeout)
        cases.append(
            {
                "name": name,
                "environ": environ,
                "timeout": timeout,
                "expected": {
                    "base_url": loaded.base_url,
                    "token": loaded.token,
                    "timeout": loaded.timeout,
                    "url_var": loaded.url_var,
                    "token_var": loaded.token_var,
                },
            }
        )
    return cases


def _describe_cases(tool: str) -> list[dict]:
    spec = specs.SPECS[tool]
    probe = projections._PROBE_TOKEN
    environs = (
        ("nothing set", {}),
        ("only the token", {spec.token_vars[-1]: probe}),
        ("only the url", {spec.url_vars[-1]: "host.example.com"}),
        ("both", {spec.url_vars[0]: "host.example.com", spec.token_vars[0]: probe}),
        ("a blank value", {spec.url_vars[0]: "  ", spec.token_vars[0]: probe}),
    )
    return [
        {
            "name": name,
            "environ": environ,
            "describe_environment": envconfig.describe_environment(spec, dict(environ)),
            "missing_vars": envconfig.missing_vars(spec, dict(environ)),
        }
        for name, environ in environs
    ]


def es_pattern(source: str) -> dict:
    """A Python regex source as ``{source, flags}`` in ECMAScript syntax.

    Only the constructs the toolkit's patterns use are translated, and anything else
    raises: a pattern this function cannot read is a pattern whose meaning in another
    engine is unknown, which is a reason to stop and not a reason to guess. The leading
    ``(?i)`` becomes the ``i`` flag; ``\\"`` (an escape JavaScript's unicode mode refuses)
    becomes the bare quote.
    """
    flags = ""
    if source.startswith("(?i)"):
        source, flags = source[len("(?i)") :], "i"
    source = source.replace('\\"', '"')
    if re.search(r"\(\?[a-zA-Z]", source) or "(?P" in source:
        raise ValueError(f"not translatable to ECMAScript: {source!r}")
    return {"source": source, "flags": flags}


def _credentials() -> dict:
    tools = {}
    try:
        for tool, name in TOOLS.items():
            spec = specs.SPECS[tool]
            scenarios = []
            for scenario in projections._CREDENTIAL_SCENARIOS:
                case = {"name": scenario, **_scenario_input(tool, scenario)}
                case["expected"] = _failure(tool, case)
                scenarios.append(case)
            tools[name] = {
                "spec": _spec_data(spec),
                "normalized_urls": [
                    {"raw": raw, "expected": envconfig.normalize_base_url(raw, spec)}
                    for raw in projections._URL_CASES[tool]
                ],
                "failures": scenarios,
                "loads": _load_ok_cases(tool),
                "describes": _describe_cases(tool),
            }
    finally:
        # normalize_base_url registers any userinfo it sees on the shared redactor.
        redact.reset_secrets()
    return {
        **_header("credentials"),
        "description": (
            "Each source tool's credential declaration as data (`spec`), and what the "
            "environment functions do under it. `normalized_urls`: `normalize_base_url(raw)`. "
            "`failures`: run `operation` (`load` over `environ`, or `normalize_base_url` over "
            "`raw`) and require a ConfigError with `message`, `code` and `recovery`; `lines` is "
            "that recovery rendered for the tool. `loads`: a successful `load`. `describes`: "
            "`describe_environment` and `missing_vars`."
        ),
        "constants": {
            "default_timeout": envconfig.DEFAULT_TIMEOUT,
            "illegal_token": es_pattern(envconfig.ILLEGAL_TOKEN.pattern),
            "error_codes": ["BAD_TOKEN", "BAD_URL", "NOT_CONFIGURED"],
        },
        "tools": tools,
    }


# ----------------------------------------------------------------- redaction

# Fragments a redaction input may reference. A recipe, never a value: `join` is a list
# of parts to concatenate, `token` is a header JSON text, a payload JSON text and a
# signature, of which the first two are base64url-encoded without padding.
_JWT_HEADER = json.dumps({"alg": "HS256"})
_JWT_PAYLOAD = json.dumps({"sub": "synthetic"})
_JWT_SIGNATURE = "c2lnbmF0dXJlLXZhbHVl"


def _fragments() -> dict:
    return {
        "bearer_value": {"join": ["abcdef", "123456", "ghijkl"]},
        "plex_value": {"join": ["plex", "0123456789", "abcdef"]},
        "token": {"header": _JWT_HEADER, "payload": _JWT_PAYLOAD, "signature": _JWT_SIGNATURE},
    }


def _fragment_value(name: str) -> str:
    recipe = _fragments()[name]
    if "join" in recipe:
        return "".join(recipe["join"])

    def segment(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    return ".".join((segment(recipe["header"]), segment(recipe["payload"]), recipe["signature"]))


def _segments(text: str) -> list:
    """Split a built input into literal strings and ``{"ref": fragment}`` markers."""
    values = {name: _fragment_value(name) for name in _fragments()}
    pieces: list = [text]
    for name in ("token", "bearer_value", "plex_value"):
        value = values[name]
        out: list = []
        for piece in pieces:
            if not isinstance(piece, str):
                out.append(piece)
                continue
            parts = piece.split(value)
            for index, part in enumerate(parts):
                if index:
                    out.append({"ref": name})
                if part:
                    out.append(part)
        pieces = out
    return pieces


def render_segments(segments: list) -> str:
    """Assemble a redaction input from its segments, the way a reader must."""
    return "".join(
        piece if isinstance(piece, str) else _fragment_value(piece["ref"]) for piece in segments
    )


_SECRETS = (
    (projections._REGISTERED_LITERAL, None),
    ("someone:example-secret", 4),
    ("example-secret", 4),
    ("abc", None),
)


def _redaction() -> dict:
    tools = {}
    for tool, name in TOOLS.items():
        boundary = redact.Redactor()
        for pattern in specs.PATTERNS[tool]:
            boundary.register_pattern(pattern)
        for value, minimum in _SECRETS:
            if minimum is None:
                boundary.register_secret(value)
            else:
                boundary.register_secret(value, min_length=minimum)
        cases = []
        for case_name in projections._SAMPLE_NAMES:
            text = projections._sample_text(case_name)
            segments = _segments(text)
            assert render_segments(segments) == text, case_name
            cases.append({"name": case_name, "input": segments, "expected": boundary.redact(text)})
        tools[name] = {
            "patterns": [es_pattern(pattern) for pattern in specs.PATTERNS[tool]],
            "secrets": [
                {
                    "value": value,
                    "min_length": minimum if minimum is not None else redact.MIN_SECRET_LENGTH,
                }
                for value, minimum in _SECRETS
            ],
            "cases": cases,
        }
    return {
        **_header("redaction"),
        "description": (
            "Order of application: registered literals (longest first), the bearer rule, the "
            "tool's registered patterns in order, then the token rule. A pattern with a "
            "capture group keeps group 1 and redacts the rest; one without is replaced whole. "
            "Patterns are ECMAScript. A literal is registered only when it is at least "
            "`min_length` long. An input is a list of strings and `{ref}` markers, resolved "
            "through `fragments`, so no credential-shaped value is written into this file."
        ),
        "redacted": redact.REDACTED,
        "min_secret_length": redact.MIN_SECRET_LENGTH,
        "order": ["literals", "bearer", "registered", "token"],
        "builtin": {
            "bearer": es_pattern(redact.BEARER.pattern),
            "token": es_pattern(redact.JWT.pattern),
        },
        "fragments": _fragments(),
        "tools": tools,
    }


# ------------------------------------------------------------------- toon spec


def _toon_pointer() -> dict:
    """Where the TOON specification fixtures are, relative to this pack.

    They are not copied here: they live inside the Python package so a downstream tool
    can run the rig, and a reader in this repository opens them where they are.
    """
    return {
        **_header("toon-spec"),
        "description": (
            "The TOON encode fixtures are read in place, not copied. Paths are relative to "
            "this directory. `checksums` is in sha256sum format over the fixture files."
        ),
        "fixtures": "../src/axi_toolkit/toon_spec/encode",
        "checksums": "../src/axi_toolkit/toon_spec/checksums.txt",
        "license": "../src/axi_toolkit/toon_spec/LICENSE",
        "provenance": "../src/axi_toolkit/toon_spec/PROVENANCE.md",
    }


# --------------------------------------------------------------------- build


def build() -> dict[str, str]:
    """Every file of the pack, as ``{name: text}``, in the order they are listed."""
    files = {
        "recovery.json": _dump(_recovery_corpus()),
        "render-rules.json": _dump(_render_rules()),
        "errors.json": _dump(_errors_pack()),
        "credentials.json": _dump(_credentials()),
        "redaction.json": _dump(_redaction()),
        "toon-spec.json": _dump(_toon_pointer()),
    }
    files["checksums.txt"] = checksums(files)
    return files


def checksums(files: dict[str, str]) -> str:
    """``sha256sum``-format lines over every file but the checksums themselves."""
    return "".join(
        f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}  {name}\n"
        for name, text in files.items()
        if name != "checksums.txt"
    )
