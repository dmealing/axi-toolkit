"""One projection per declared fact, run twice: over the authority, and over this package.

That the *same projection* runs twice is the whole design, and it is the correction a
prior measurement made to the obvious idea. Running the same assertions twice does not
generalise -- an authority's content differs from run to run, some claims involve no
authority at all, and a public repository's CI holds no credentials. Running the same
projection twice does: ``capture_x`` reads the authority once, on a machine that can
reach it, and the answer is committed; ``subject_x`` reads this package, on every CI
run, with nothing to reach.

There are two authorities here and neither of them needs a credential:

* the **vendored TOON specification fixtures**, which are the specification's own
  opinion and travel with the package; and
* the **two source CLIs**, read and executed from a checkout whose location is given by
  ``AXI_TOOLKIT_SOURCE_HA`` and ``AXI_TOOLKIT_SOURCE_PLEX`` at capture time and never
  recorded. Nothing about where they live reaches the capture -- only what their code
  says and does.

So all four projection kinds run offline. The prior measurement could only promise that
for three of them, because its fourth compared a tool against a live server; here the
differential compares the two tools against *each other*, which is the comparison that
found the divergence this package exists to end, and it needs no network at all.

Every ``capture_*`` is paired with a ``subject_*`` by name, and ``scripts/reqgen.py``
resolves the pair from the fact's declared name. A fact with only one half of the pair
fails generation rather than generating a check that cannot run.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

from axi_toolkit import errors, redact, toon, toon_spec
from axi_toolkit.render import cli

from . import specs

TOOLS = ("ha", "plex")

#: Where each tool's checkout is, at capture time only. Never read by a subject
#: projection, never recorded in the capture, never needed in CI.
_SOURCE_ENV = {"ha": "AXI_TOOLKIT_SOURCE_HA", "plex": "AXI_TOOLKIT_SOURCE_PLEX"}
_PACKAGE = {"ha": "ha_axi", "plex": "plex_axi"}
_TOOL_NAME = {"ha": "ha-axi", "plex": "plex-axi"}


# ============================================================ reading the sources


def source_root(tool: str) -> Path:
    """The ``src/<package>`` directory of one source tool's checkout."""
    variable = _SOURCE_ENV[tool]
    raw = os.environ.get(variable)
    if not raw:
        raise RuntimeError(
            f"{variable} is not set. Capture reads the two source tools from a local "
            "checkout; their locations are an input to `reqgen capture` and never "
            "reach a committed file."
        )
    root = Path(raw).expanduser().resolve() / "src" / _PACKAGE[tool]
    if not root.is_dir():
        raise RuntimeError(f"{variable} does not name a checkout containing src/{_PACKAGE[tool]}")
    return root


def source_module(tool: str, name: str):
    """Import one module out of a source tool's checkout."""
    root = source_root(tool).parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module(f"{_PACKAGE[tool]}.{name}")


def _tree(tool: str, name: str) -> ast.Module:
    return ast.parse((source_root(tool) / f"{name}.py").read_text(encoding="utf-8"))


def _module_literals(tree: ast.Module, predicate) -> dict[str, object]:
    """Module-level ``NAME = <literal>`` assignments whose name satisfies ``predicate``."""
    out: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and predicate(target.id):
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    continue
    return out


def _regex_sources(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = re.compile("...")`` assignments, by name."""
    out: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "compile"):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and node.value.args:
                try:
                    out[target.id] = ast.literal_eval(node.value.args[0])
                except ValueError:
                    continue
    return out


def _class_names(tree: ast.Module) -> list[str]:
    return [node.name for node in tree.body if isinstance(node, ast.ClassDef)]


def _code_literals(tree: ast.Module) -> list[str]:
    """Every ``code="LITERAL"`` keyword in the module.

    A computed code -- ``f"HTTP_{status}"`` -- is deliberately not collected: it is
    vocabulary minted from whatever a server said, which no caller can switch on, and
    a projection that quietly accepted one would hide exactly that.
    """
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if (
                    keyword.arg == "code"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    found.append(keyword.value.value)
    return sorted(set(found))


def literal_recovery_lines(tool: str) -> list[str]:
    """Every recovery line one tool emits that is bytes rather than a template.

    An f-string is a template: it has no bytes until something interpolates it, so it
    cannot be a wire case. What is left is every line the tool prints verbatim, which
    is the corpus this package has to reproduce exactly.
    """
    root = source_root(tool)
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            for holder in _recovery_holders(node):
                items = holder.elts if isinstance(holder, (ast.List, ast.Tuple)) else [holder]
                for item in items:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        found.add(item.value)
    return sorted(found)


def _recovery_holders(node: ast.AST) -> list[ast.AST]:
    """Expressions that end up as help lines: the argument shapes the tools use."""
    holders: list[ast.AST] = []
    if isinstance(node, ast.Call):
        holders.extend(kw.value for kw in node.keywords if kw.arg == "help_lines")
        if isinstance(node.func, ast.Name) and node.func.id == "HelpBlock":
            holders.extend(node.args)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in ("help_lines", "lines"):
                holders.extend(node.args)
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in ("help_lines", "_SETUP_HELP", "lines"):
                holders.append(node.value)
    return holders


# ================================================== capability: TOON, read twice


def _raw_fixture_docs() -> list[dict]:
    """The vendored fixture files, read as plain JSON.

    Deliberately not through :mod:`axi_toolkit.toon_spec`: the authority is the files, and
    a projection that read them through the same loader the subject uses would be
    comparing that loader with itself.
    """
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((toon_spec.ENCODE_ROOT).glob("*.json"))
    ]


def capture_toon_encode_case_count() -> int:
    return sum(len(doc["tests"]) for doc in _raw_fixture_docs())


def subject_toon_encode_case_count() -> int:
    """How many cases the conformance runner will actually iterate."""
    return len(toon_spec.cases())


def capture_toon_fixture_digests() -> list[str]:
    """What each file hashed to when it was vendored, as recorded upstream-side."""
    return [f"{name} {digest}" for name, digest in sorted(toon_spec.recorded_digests().items())]


def subject_toon_fixture_digests() -> list[str]:
    """What each file hashes to now."""
    return [f"{name} {digest}" for name, digest in sorted(toon_spec.actual_digests().items())]


def capture_toon_fixture_categories() -> list[str]:
    return sorted({str(doc.get("category", "")) for doc in _raw_fixture_docs()})


def subject_toon_fixture_categories() -> list[str]:
    """The categories this rig is prepared to run.

    Equality rather than containment: a decode fixture arriving in the directory must
    fail rather than be collected and silently not run, and a category the rig claims
    to run with no fixture exercising it is a claim nothing supports.
    """
    return sorted(toon_spec.RUNNABLE_CATEGORIES)


def capture_toon_case_option_names() -> list[str]:
    names: set[str] = set()
    for doc in _raw_fixture_docs():
        for case in doc["tests"]:
            names.update(case.get("options") or {})
    return sorted(names)


def subject_toon_case_option_names() -> list[str]:
    return sorted(toon_spec.KNOWN_OPTIONS)


def capture_toon_exercised_delimiters() -> list[str]:
    # The default is exercised by every case that names no delimiter at all.
    found = {","}
    for doc in _raw_fixture_docs():
        for case in doc["tests"]:
            options = case.get("options") or {}
            if "delimiter" in options:
                found.add(str(options["delimiter"]))
    return sorted(found)


def subject_toon_exercised_delimiters() -> list[str]:
    return sorted(toon.TOON_DELIMITERS)


# ============================================ capability: the error vocabulary


def capture_error_exit_codes() -> list[str]:
    found: set[str] = set()
    for tool in TOOLS:
        literals = _module_literals(_tree(tool, "errors"), lambda name: name.startswith("EXIT_"))
        found.update(f"{name}={value}" for name, value in literals.items())
    return sorted(found)


def subject_error_exit_codes() -> list[str]:
    return sorted(
        f"{name}={getattr(errors, name)}" for name in dir(errors) if name.startswith("EXIT_")
    )


def capture_error_fault_classes() -> list[str]:
    found: set[str] = set()
    for tool in TOOLS:
        literals = _module_literals(_tree(tool, "errors"), lambda name: name.startswith("CLASS_"))
        found.update(str(value) for value in literals.values())
    return sorted(found)


def subject_error_fault_classes() -> list[str]:
    return sorted({*errors.CLASSES, errors.CLASS_UNCLASSIFIED})


def capture_error_type_names() -> list[str]:
    """Every exception type either tool declares.

    A union, not an intersection: one tool separates a refused-but-authenticated
    caller into its own type and the other has not needed to yet, and a shared module
    that dropped the type would take the distinction away from the tool that has it.
    """
    found: set[str] = set()
    for tool in TOOLS:
        found.update(_class_names(_tree(tool, "errors")))
    return sorted(found)


def subject_error_type_names() -> list[str]:
    return sorted(
        name
        for name, value in vars(errors).items()
        if isinstance(value, type) and issubclass(value, Exception)
    )


def capture_env_config_error_codes() -> list[str]:
    found: set[str] = set()
    for tool in TOOLS:
        found.update(_code_literals(_tree(tool, "config")))
    return sorted(found)


def subject_env_config_error_codes() -> list[str]:
    """The same extractor, pointed at this package's own module.

    Literally the same projection run twice: if this module ever computed a code
    instead of writing one, the extractor would not collect it and the check would go
    red on the absence.
    """
    from axi_toolkit import envconfig

    tree = ast.parse(Path(envconfig.__file__).read_text(encoding="utf-8"))
    return _code_literals(tree)


# ================================== capability: the extracted domain tier, read twice
#
# Until a tool takes the module back from here, two copies of it exist in two
# repositories -- which is the failure this package was built to end, so it is gated
# rather than trusted to a memo. The gate is temporary by construction: it compares
# this package against a source checkout, so it stops having anything to say the day
# the tool imports this module instead of carrying its own.


#: The module in the source tool that ``axi_toolkit.ha.services`` was moved from.
_HA_SERVICE_MODEL = "servicemodel"


def _definition_digests(source: str) -> list[str]:
    """Every top-level definition as ``<name> <digest>``, plus one row for the module.

    The ``<module>`` row hashes the whole file with its docstring elided, and that
    elision is the entire allowance the move was granted: the tool's docstring cites a
    file in its own repository, and the citation would dangle here. Everything else --
    each definition, the comments between them, the import list, the blank lines -- is
    inside that digest, so any other difference between the two copies is drift and the
    row goes red on it.

    The per-definition rows are therefore redundant for detection and are not redundant
    for reading: a bare digest mismatch says only that something moved, and a set
    difference over named rows says which function it was.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    rows: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        segment = "".join(lines[node.lineno - 1 : node.end_lineno])
        rows.extend(f"{name} {_sha256(segment)}" for name in names)

    body = list(lines)
    first = tree.body[0] if tree.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        del body[first.lineno - 1 : first.end_lineno]
    rows.append(f"<module> {_sha256(''.join(body))}")
    return sorted(rows)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture_ha_service_model_definitions() -> list[str]:
    """The copy the tool still runs, read out of its checkout."""
    path = source_root("ha") / f"{_HA_SERVICE_MODEL}.py"
    return _definition_digests(path.read_text(encoding="utf-8"))


def subject_ha_service_model_definitions() -> list[str]:
    """The copy this package ships, read the same way.

    Off ``__file__`` rather than off a path this file knows, so the check judges the
    module that was imported -- an installed wheel in CI, ``src/`` in a checkout.
    """
    from axi_toolkit.ha import services

    return _definition_digests(Path(services.__file__).read_text(encoding="utf-8"))


# --- the Plex domain tier -----------------------------------------------------
#
# The Home Assistant half above could be gated by hashing, because it moved
# verbatim. This half could not: the move deliberately rewrote every recovery
# line into intent, so a digest would fail by construction and weakening it to
# pass would be worse than having no gate. What is invariant here is the surface
# and the rendered behaviour, and those are what the two facts below state.
#
# This one is the surface. `ids.py` moved whole, so equality over its public
# definitions reads both ways with nothing declared: a definition the tool grew
# and this package did not is a gap, the other way round is an invention. The
# pure half of `music.py` has no such natural boundary -- most of that module
# stayed behind -- so the boundary is declared, once, in the map below, and the
# capture refuses to record a name the tool no longer has.

#: What this package took out of the tool's ``music.py``, as
#: ``name there -> name here``. Every entry is an identity but one: a helper the
#: tool could keep private, because its only caller was the next function down
#: the same module, is public here -- its caller stayed behind, and a leading
#: underscore on a name another module must import says the opposite of what it
#: means.
#:
#: The map is the declared boundary and is honest about its reach: it catches a
#: moved definition that changed name or vanished on either side, and it does
#: not catch a *new* pure function appearing in the tool's ``music.py``. Deciding
#: that mechanically was tried and abandoned -- every rule that admits `stars`
#: also admits the row vocabulary, which is surface-specific and stays in the CLI.
_PLEX_FILTER_BOUNDARY = {
    "ABSOLUTE_DATE": "ABSOLUTE_DATE",
    "BARE_OPERATOR": "BARE_OPERATOR",
    "FIELD_MAP": "FIELD_MAP",
    "LIBTYPES": "LIBTYPES",
    "POINTS_PER_STAR": "POINTS_PER_STAR",
    "RATED_MIN_ZERO_NOTE": "RATED_MIN_ZERO_NOTE",
    "RATING_OPERATOR": "RATING_OPERATOR",
    "RELATIVE_DATE": "RELATIVE_DATE",
    "SORT_DIRECTIONS": "SORT_DIRECTIONS",
    "_assert_server_side": "assert_server_side",
    "build_filters": "build_filters",
    "describe_filter": "describe_filter",
    "parse_relative_date": "parse_relative_date",
    "parse_sort": "parse_sort",
    "parse_stars": "parse_stars",
    "rating_predicate": "rating_predicate",
    "stars": "stars",
}


def _bound_names(node: ast.AST) -> set:
    """Every name one module-level statement binds: a definition or an assignment."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def _top_level_names(tree: ast.Module) -> set:
    """Every name bound at module level by a definition or an assignment."""
    names: set = set()
    for node in tree.body:
        names |= _bound_names(node)
    return names


def _public_names(tree: ast.Module) -> list:
    return sorted(name for name in _top_level_names(tree) if not name.startswith("_"))


def capture_plex_domain_definitions() -> list:
    """The surface the tool still carries, read out of its checkout."""
    rows = [f"ids.{name}" for name in _public_names(_tree("plex", "ids"))]
    music = _top_level_names(_tree("plex", "music"))
    for there, here in sorted(_PLEX_FILTER_BOUNDARY.items()):
        if there not in music:
            raise RuntimeError(
                f"the boundary names {there!r}, which the tool's music.py no longer defines. "
                "A boundary that records a name nobody has is not a boundary."
            )
        rows.append(f"filters.{here}")
    return sorted(rows)


def subject_plex_domain_definitions() -> list:
    """The surface this package ships, read the same way.

    Off ``__file__`` rather than off a path this file knows, so the check judges
    the modules that were imported -- an installed wheel in CI, ``src/`` in a
    checkout.
    """
    from axi_toolkit.plex import filters, ids

    rows = []
    for prefix, module in (("ids", ids), ("filters", filters)):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        rows.extend(f"{prefix}.{name}" for name in _public_names(tree))
    return sorted(rows)


# ================================================================== population


_SET_ENV_LINE = re.compile(r"^Set [A-Z][A-Z0-9_]* to ")
_BACKTICKED = re.compile(r"`([^`]*)`")


def classify_recovery_line(tool_name: str, text: str) -> str:
    """Which shape of recovery a raw line is, decided without this package.

    A partition derived from reality rather than from the code, which is the point: it
    can name a shape the code has no branch for, and a shape with no branch is exactly
    what full branch coverage is compatible with.
    """
    spans = _BACKTICKED.findall(text)
    outside = _BACKTICKED.sub("", text)
    if _SET_ENV_LINE.match(text):
        kind = "set_env"
    elif any(span == tool_name or span.startswith(tool_name + " ") for span in spans):
        kind = "run" if tool_name not in outside else "note"
    elif spans:
        kind = "retry" if tool_name not in text else "note"
    else:
        kind = "note"
    if kind in ("run", "retry"):
        first = _BACKTICKED.search(text)
        lead = text[: first.start()].rstrip()
        default = "Run" if kind == "run" else "Run the command again with"
        tail = text[first.end() :]
        shape = "default" if lead == default else "custom"
        if not tail:
            trailing = "none"
        elif tail.startswith(" "):
            trailing = "space"
        else:
            trailing = "other"
        return f"{kind}|lead={shape}|tail={trailing}"
    if kind == "note":
        return f"note|names_tool={int(tool_name in text)}"
    return kind


def capture_recovery_shape_cells() -> list[str]:
    cells: set[str] = set()
    for tool in TOOLS:
        name = _TOOL_NAME[tool]
        for text in literal_recovery_lines(tool):
            cells.add(classify_recovery_line(name, text))
    return sorted(cells)


#: One synthetic line per shape, built from the vocabulary. If a cell cannot be built,
#: this package cannot express that shape and the coverage relation says so.
def _probe_recovery(cell: str):
    if cell == "set_env":
        return errors.set_env("PROBE_URL", "a probe value")
    if cell.startswith(("run|", "retry|")):
        kind, lead_part, tail_part = cell.split("|")
        custom = lead_part.endswith("custom")
        trailing = tail_part.split("=", 1)[1]
        purpose = "" if trailing == "none" else "for a probe"
        separator = ": " if trailing == "other" else " "
        if kind == "run":
            lead = "Reach for" if custom else "Run"
            return errors.run(("probe",), purpose=purpose, lead=lead, separator=separator)
        lead = "Retry it with" if custom else "Run the command again with"
        return errors.retry("--probe", purpose=purpose, lead=lead, separator=separator)
    if cell.startswith("note|"):
        names_tool = cell.endswith("=1")
        text = "A probe note about {tool}." if names_tool else "A probe note."
        return errors.note(text)
    if cell == "choose":
        return errors.choose("did you mean", ("a", "b"))
    return None


def subject_recovery_shape_cells(cells) -> list[str]:
    """The shapes this package can express, proved by building one of each.

    A cell counts as covered only when a recovery built for it renders to a line the
    same reality-derived classifier puts back in the same cell. Claiming the shape is
    not enough; the bytes have to come out the right way round.
    """
    covered = []
    for cell in cells:
        probe = _probe_recovery(cell)
        if probe is None:
            continue
        rendered = cli.line(probe, "probe-tool")
        if classify_recovery_line("probe-tool", rendered) == cell:
            covered.append(cell)
    return covered


def _pattern_cell(source: str) -> str:
    """Which shape of credential pattern a regex is, decided from the regex itself.

    Three things are observable and all three change what registration has to support:
    whether it keeps a prefix (a capturing group) so the reader can still see which
    credential was suppressed, whether it is case-insensitive, and whether it opens on
    that group or on ordinary pattern text.
    """
    compiled = re.compile(source)
    body = source[len("(?i)") :] if source.startswith("(?i)") else source
    opens = "group" if body.startswith("(") else "literal"
    keeps = min(compiled.groups, 1)
    insensitive = int(bool(compiled.flags & re.IGNORECASE))
    return f"groups={keeps}|ignorecase={insensitive}|opens={opens}"


#: One probe pattern per shape. A cell with no probe is a shape registration cannot
#: express; a probe that does not redact the way its cell says is the same thing.
_PATTERN_PROBES = {
    "groups=0|ignorecase=0|opens=literal": r"\bprobe-[A-Za-z0-9]{4,}",
    "groups=0|ignorecase=1|opens=literal": r"(?i)\bprobe-[A-Za-z0-9]{4,}",
    "groups=1|ignorecase=1|opens=literal": r"(?i)\b(probe )[A-Za-z0-9]{4,}",
    "groups=1|ignorecase=0|opens=literal": r"\b(probe )[A-Za-z0-9]{4,}",
    "groups=1|ignorecase=1|opens=group": r"(?i)(probe=)[A-Za-z0-9]{4,}",
    "groups=1|ignorecase=0|opens=group": r"(probe=)[A-Za-z0-9]{4,}",
}

_PROBE_SUBJECT = "probe-abcd1234 probe abcd1234 probe=abcd1234"


def capture_redaction_shape_cells() -> list[str]:
    cells: set[str] = set()
    for tool in TOOLS:
        for source in _regex_sources(_tree(tool, "output")).values():
            cells.add(_pattern_cell(source))
    return sorted(cells)


def subject_redaction_shape_cells(cells) -> list[str]:
    """The pattern shapes registration can express, proved by registering one of each.

    A cell counts as covered only when its probe redacts the probe subject, keeps the
    prefix exactly when the cell says it does, and classifies back into the same cell.
    """
    covered = []
    for cell in cells:
        source = _PATTERN_PROBES.get(cell)
        if source is None or _pattern_cell(source) != cell:
            continue
        boundary = redact.Redactor()
        boundary.register_pattern(source)
        cleaned = boundary.redact(_PROBE_SUBJECT)
        if redact.REDACTED not in cleaned:
            continue
        keeps_prefix = cell.startswith("groups=1")
        prefix = "probe=" if cell.endswith("opens=group") else "probe "
        if keeps_prefix and f"{prefix}{redact.REDACTED}" not in cleaned:
            continue
        covered.append(cell)
    return covered


def _spec_cell(scheme: str, port, strip: str, aliases: int) -> str:
    return f"scheme={scheme}|port={port or 'none'}|strip={strip or 'none'}|aliases={aliases}"


def capture_credential_spec_cells() -> list[str]:
    """How the two tools differ in reading credentials, read off their own modules.

    Each difference is probed rather than declared: the module is asked to normalise a
    bare host and an ``/api``-suffixed URL, and what comes back says which defaults it
    holds. A tool that changed one of them would move to a cell nothing here expresses.
    """
    cells = []
    for tool in TOOLS:
        module = source_module(tool, "config")
        bare = module.normalize_base_url("host.example.com")
        scheme, _, hostpart = bare.partition("://")
        port = hostpart.partition(":")[2] or None
        stripped = module.normalize_base_url("https://host.example.com/api")
        strip = "" if stripped.endswith("/api") else "/api"
        cells.append(_spec_cell(scheme, port, strip, len(module.URL_VARS) - 1))
    return sorted(set(cells))


def subject_credential_spec_cells(cells) -> list[str]:
    """Each cell rebuilt as a spec, and probed the same way the capture probed a tool."""
    from axi_toolkit import envconfig

    covered = []
    for cell in cells:
        parts = dict(part.split("=", 1) for part in cell.split("|"))
        aliases = int(parts["aliases"])
        spec = envconfig.CredentialSpec(
            url_vars=("PROBE_URL", *(f"PROBE_ALIAS_{n}" for n in range(aliases))),
            token_vars=("PROBE_TOKEN",),
            default_scheme=parts["scheme"],
            default_port=None if parts["port"] == "none" else int(parts["port"]),
            strip_path_suffix="" if parts["strip"] == "none" else parts["strip"],
        )
        bare = envconfig.normalize_base_url("host.example.com", spec)
        scheme, _, hostpart = bare.partition("://")
        port = hostpart.partition(":")[2] or None
        stripped = envconfig.normalize_base_url("https://host.example.com/api", spec)
        strip = "" if stripped.endswith("/api") else "/api"
        if _spec_cell(scheme, port, strip, len(spec.url_vars) - 1) == cell:
            covered.append(cell)
    return covered


# ======================================================================== wire


def capture_toon_encode_cases() -> list[dict]:
    return [
        {"case": toon_spec.case_id(case), "expected": case.expected} for case in toon_spec.cases()
    ]


_CASES_BY_ID = None


def subject_toon_encode_cases(case_id: str) -> str:
    global _CASES_BY_ID
    if _CASES_BY_ID is None:
        _CASES_BY_ID = {toon_spec.case_id(case): case for case in toon_spec.cases()}
    case = _CASES_BY_ID[case_id]
    return toon.encode(case.input, **toon_spec.encoder_kwargs(case))


def _recovery_rows(tool: str) -> list[dict]:
    return [{"case": text, "expected": text} for text in literal_recovery_lines(tool)]


def capture_ha_recovery_lines() -> list[dict]:
    return _recovery_rows("ha")


def capture_plex_recovery_lines() -> list[dict]:
    return _recovery_rows("plex")


def _round_trip(tool_name: str, text: str) -> str:
    """Parse a line into intent and render it back, which must be the identity.

    The intent is inspected on the way through: a structured recovery that still
    carries the tool's own name anywhere but the command it names would render for
    exactly one tool forever, so it is reported here rather than round-tripping
    quietly.
    """
    intent = cli.parse(text, tool_name)
    if errors.mentions_tool(intent):
        neutral = cli.line(intent, "other-tool")
        if tool_name in neutral:
            return f"<the tool's name is baked into the intent: {neutral!r}>"
    return cli.line(intent, tool_name)


def subject_ha_recovery_lines(case: str) -> str:
    return _round_trip("ha-axi", case)


def subject_plex_recovery_lines(case: str) -> str:
    return _round_trip("plex-axi", case)


#: Configuration scenarios, as inputs. Each one is a way the environment can be wrong;
#: what the tool says about it is the captured expectation, never one written here.
_CREDENTIAL_SCENARIOS = (
    "missing:both",
    "missing:url",
    "missing:token",
    "blank:url",
    "bad_token:space",
    "bad_token:newline",
    "bad_token:tab",
    "bad_token:carriage-return",
    "bad_url:empty",
    "bad_url:scheme",
    "bad_url:no-netloc",
)

_PROBE_TOKEN = "probe-" + "0123456789abcdef"
_BAD_TOKEN_CHAR = {
    "space": " ",
    "newline": "\n",
    "tab": "\t",
    "carriage-return": "\r",
}


def _rendered_failure(message: str, lines) -> str:
    """One string carrying the message and its recovery, so one comparison covers both."""
    return "\n".join([message, *(f"  {item}" for item in lines)])


def _capture_credential_message(tool: str, scenario: str) -> str:
    module = source_module(tool, "config")
    url_var, token_var = module.URL_VARS[0], module.TOKEN_VARS[0]
    url = "http://host.example.com:32400" if tool == "plex" else "https://host.example.com"
    try:
        head, _, detail = scenario.partition(":")
        if head == "missing":
            environ = {}
            if detail == "url":
                environ = {token_var: _PROBE_TOKEN}
            elif detail == "token":
                environ = {url_var: url}
            module.load(environ)
        elif head == "blank":
            module.load({url_var: "  ", token_var: _PROBE_TOKEN})
        elif head == "bad_token":
            bad = f"abc{_BAD_TOKEN_CHAR[detail]}def"
            module.load({url_var: url, token_var: bad})
        elif head == "bad_url":
            raw = {"empty": "", "scheme": "ftp://host.example.com", "no-netloc": "://nope"}[detail]
            module.normalize_base_url(raw)
    except Exception as exc:
        return _rendered_failure(exc.message, exc.help_lines)
    raise AssertionError(f"{tool} scenario {scenario!r} did not fail; it is not a scenario")


def _subject_credential_message(tool: str, scenario: str) -> str:
    from axi_toolkit import envconfig

    spec = specs.SPECS[tool]
    url_var, token_var = spec.url_vars[0], spec.token_vars[0]
    url = "http://host.example.com:32400" if tool == "plex" else "https://host.example.com"
    try:
        head, _, detail = scenario.partition(":")
        if head == "missing":
            environ = {}
            if detail == "url":
                environ = {token_var: _PROBE_TOKEN}
            elif detail == "token":
                environ = {url_var: url}
            envconfig.load(spec, environ)
        elif head == "blank":
            envconfig.load(spec, {url_var: "  ", token_var: _PROBE_TOKEN})
        elif head == "bad_token":
            bad = f"abc{_BAD_TOKEN_CHAR[detail]}def"
            envconfig.load(spec, {url_var: url, token_var: bad})
        elif head == "bad_url":
            raw = {"empty": "", "scheme": "ftp://host.example.com", "no-netloc": "://nope"}[detail]
            envconfig.normalize_base_url(raw, spec)
    except errors.AxiError as exc:
        return _rendered_failure(exc.message, cli.lines(exc.recovery, _TOOL_NAME[tool]))
    return "<no failure was raised>"


def capture_ha_credential_messages() -> list[dict]:
    return [
        {"case": s, "expected": _capture_credential_message("ha", s)} for s in _CREDENTIAL_SCENARIOS
    ]


def capture_plex_credential_messages() -> list[dict]:
    return [
        {"case": s, "expected": _capture_credential_message("plex", s)}
        for s in _CREDENTIAL_SCENARIOS
    ]


def subject_ha_credential_messages(case: str) -> str:
    return _subject_credential_message("ha", case)


def subject_plex_credential_messages(case: str) -> str:
    return _subject_credential_message("plex", case)


_URL_CASES = {
    "ha": (
        "host.example.com",
        "host.example.com:8123",
        "http://host.example.com",
        "https://host.example.com/",
        "https://host.example.com/api",
        "https://host.example.com/api/",
        "https://someone:example-secret@host.example.com",
        "https://proxy.example.com/prefix",
        "  https://host.example.com  ",
    ),
    "plex": (
        "host.example.com",
        "host.example.com:8443",
        "http://host.example.com:32400/",
        "https://host.example.com",
        "https://someone:example-secret@host.example.com",
        "http://[2001:db8::1]",
        "http://[2001:db8::1]:32400",
        "  host.example.com  ",
    ),
}


def _capture_urls(tool: str) -> list[dict]:
    module = source_module(tool, "config")
    return [{"case": raw, "expected": module.normalize_base_url(raw)} for raw in _URL_CASES[tool]]


def capture_ha_normalized_urls() -> list[dict]:
    return _capture_urls("ha")


def capture_plex_normalized_urls() -> list[dict]:
    return _capture_urls("plex")


def _subject_url(tool: str, raw: str) -> str:
    from axi_toolkit import envconfig

    return envconfig.normalize_base_url(raw, specs.SPECS[tool])


def subject_ha_normalized_urls(case: str) -> str:
    return _subject_url("ha", case)


def subject_plex_normalized_urls(case: str) -> str:
    return _subject_url("plex", case)


# --- redaction samples -------------------------------------------------------
#
# The sample texts are BUILT, never written down. A committed file holding a literal
# JWT or bearer value would be a credential shape in a public repository, and the
# repository's own leak scanner would be right to refuse it. So each case names a
# template, the template is assembled at run time from pieces, and only the redacted
# result -- which by construction contains no credential -- reaches the capture.


def _synthetic_jwt() -> str:
    def segment(payload: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return raw.rstrip("=")

    return ".".join(
        (segment({"alg": "HS256"}), segment({"sub": "synthetic"}), "c2lnbmF0dXJlLXZhbHVl")
    )


_SYNTHETIC_BEARER = "abcdef" + "123456" + "ghijkl"
_SYNTHETIC_PLEX = "plex" + "0123456789abcdef"
_REGISTERED_LITERAL = "a-registered-literal-value"


def _sample_text(name: str) -> str:
    return {
        "bearer-header": f"Authorization: Bearer {_SYNTHETIC_BEARER}",
        "jwt-in-prose": f"leaked {_synthetic_jwt()} here",
        "token-parameter": f"http://host.example.com:32400/art?X-Plex-Token={_SYNTHETIC_PLEX}",
        "delegation-parameter": f"http://host.example.com:32400/s?token={_SYNTHETIC_PLEX}",
        "token-header": f"X-Plex-Token: {_SYNTHETIC_PLEX}",
        "registered-literal": f"note {_REGISTERED_LITERAL} trailing",
        "userinfo-pair": "pair is someone:example-secret",
        "too-short-to-register": "abc def",
        "nothing-to-redact": "an ordinary sentence about a token",
    }[name]


_SAMPLE_NAMES = (
    "bearer-header",
    "jwt-in-prose",
    "token-parameter",
    "delegation-parameter",
    "token-header",
    "registered-literal",
    "userinfo-pair",
    "too-short-to-register",
    "nothing-to-redact",
)


def capture_redaction_samples() -> list[dict]:
    rows = []
    for tool in TOOLS:
        module = source_module(tool, "output")
        module.reset_secrets()
        module.register_secret(_REGISTERED_LITERAL)
        module.register_secret("someone:example-secret", min_length=4)
        module.register_secret("example-secret", min_length=4)
        module.register_secret("abc")
        for name in _SAMPLE_NAMES:
            rows.append(
                {
                    "case": f"{tool}|{name}",
                    "expected": module.redact(_sample_text(name)),
                }
            )
        module.reset_secrets()
    return rows


_SUBJECT_REDACTORS: dict = {}


def _subject_redactor(tool: str):
    if tool not in _SUBJECT_REDACTORS:
        boundary = redact.Redactor()
        for pattern in specs.PATTERNS[tool]:
            boundary.register_pattern(pattern)
        boundary.register_secret(_REGISTERED_LITERAL)
        boundary.register_secret("someone:example-secret", min_length=4)
        boundary.register_secret("example-secret", min_length=4)
        boundary.register_secret("abc")
        _SUBJECT_REDACTORS[tool] = boundary
    return _SUBJECT_REDACTORS[tool]


def subject_redaction_samples(case: str) -> str:
    tool, _, name = case.partition("|")
    return _subject_redactor(tool).redact(_sample_text(name))


# --- the Plex domain tier, behaviour rather than bytes of source ---------------
#
# The other half of the gate. Every scenario below is run twice: once against the
# copy the tool still carries, once against the copy this package ships, and the
# two must produce the same string. For a value that is the value; for a refusal
# it is the code, the message, and the recovery *rendered for ``plex-axi``* --
# which is where the rewrite is judged. Recovery moved from a list of finished
# lines to structured intent, so the source text cannot be compared and the
# printed line is exactly the thing that must not have changed.
#
# The subject side renders each recovery a second time under a different tool
# name and reports one that still says ``plex-axi``. A line that reproduces the
# tool's bytes by carrying its name is not extracted, it is copied, and the two
# are indistinguishable from the rendered output alone.

#: Stand-ins for the attributes a ``plexapi`` object carries. The two functions
#: that take an item read it with ``getattr`` and never call it, so a plain
#: namespace is the whole of what they need -- which is why they could move while
#: everything taking a section could not.
_PLEX_ITEMS = {
    "catalogue": {"ratingKey": 311, "guid": "plex://track/a1b2c3d4e5f60718293a0100"},
    "locally-matched": {"ratingKey": 311, "guid": "local://311"},
    "no-guid": {"ratingKey": 311, "guid": ""},
    "no-rating-key": {"ratingKey": "", "guid": "plex://track/a1b2c3d4e5f60718293a0100"},
    "guid-shaped-key": {"ratingKey": "a1b2c3d4e5f60718293a0100", "guid": ""},
}

#: A compiled pattern, whose value is its source rather than its repr.
_REGEX_TYPE = type(re.compile(""))

#: Obviously synthetic, and the right shape: a real machineIdentifier is a long
#: hexadecimal string, and a short stand-in would not exercise the same code.
_PLEX_MACHINE_ID = "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f"

#: The words after the tool's name. The tool takes them already joined to it and
#: this package takes them on their own; that difference *is* the extraction, so
#: both spellings of the same invocation are exercised, including a multi-word one
#: whose last word is quoted.
_PLEX_INVOCATIONS = {
    "track": ("track",),
    "playlist": ("playlist", "add", "'Example Playlist'"),
}

_PLEX_RATING_KEYS = {
    "numeric": ("311", "track"),
    "padded": ("  311  ", "track"),
    "catalogue-guid": ("plex://track/a1b2c3d4e5f60718293a0100", "track"),
    "local-guid": ("local://311", "track"),
    "local-guid-in-a-longer-command": ("local://311", "playlist"),
    "media-id": ("plex://0f0f0f0f/311", "track"),
    "legacy-media-id": ("plex://311", "track"),
    "guid-namespaced-key": ("plex://track/311", "track"),
    "not-a-number": ("not-a-key", "track"),
    "trailing-letter": ("12a", "track"),
    "empty": ("", "track"),
}

_PLEX_ID_CASES = (
    *(f"stability_note:{name}" for name in ("catalogue", "locally-matched", "no-guid")),
    "stability_note:omitted",
    "stability_note:padded-local",
    "media_content_id:numeric",
    "media_content_id:integer",
    "media_content_id:padded",
    "media_content_id:catalogue-guid",
    "media_content_id:no-machine-id",
    *(f"media_id_for:{name}" for name in _PLEX_ITEMS),
    "media_id_for:no-machine-id",
    *(f"handoff:{name}" for name in ("catalogue", "locally-matched", "no-guid")),
    "handoff:no-rating-key",
    *(f"validate_rating_key:{name}" for name in _PLEX_RATING_KEYS),
)


def _plex_item(name: str):
    return type("Item", (), dict(_PLEX_ITEMS[name]))()


def _plex_id_call(module, validate, case: str):
    """The zero-argument call one scenario names, against either copy.

    ``validate`` is supplied by the caller because it is the one signature the
    move changed: the tool takes ``invocation="plex-axi track"`` and this package
    takes ``command=("track",)``, and the two spellings meaning the same thing is
    the claim under test.
    """
    head, _, detail = case.partition(":")
    if head == "stability_note":
        if detail == "omitted":
            return module.stability_note
        if detail == "padded-local":
            return lambda: module.stability_note("  local://311  ")
        return lambda: module.stability_note(_PLEX_ITEMS[detail]["guid"])
    if head == "media_content_id":
        key = {
            "numeric": "311",
            "integer": 311,
            "padded": "  311  ",
            "catalogue-guid": "plex://track/a1b2c3d4e5f60718293a0100",
            "no-machine-id": "311",
        }[detail]
        machine = "" if detail == "no-machine-id" else _PLEX_MACHINE_ID
        return lambda: module.media_content_id(machine, key)
    if head == "media_id_for":
        if detail == "no-machine-id":
            return lambda: module.media_id_for("", _plex_item("catalogue"))
        return lambda: module.media_id_for(_PLEX_MACHINE_ID, _plex_item(detail))
    if head == "handoff":
        return lambda: module.handoff(_PLEX_MACHINE_ID, _plex_item(detail))
    if head == "validate_rating_key":
        raw, invocation = _PLEX_RATING_KEYS[detail]
        return lambda: validate(raw, invocation)
    raise AssertionError(f"no such plex id scenario: {case!r}")


_PLEX_STARS = {
    "unrated-none": None,
    "unrated-empty": "",
    "zero": 0,
    "whole": 8,
    "half": 7,
    "string": "10",
}

_PLEX_PARSE_STARS = {
    "whole": ("4", "--rated-min"),
    "half": ("4.5", "--rated-min"),
    "zero": ("0", "--rated-min"),
    "top": ("5", "--stars"),
    "not-a-number": ("high", "--rated-min"),
    "none": (None, "--rated-min"),
    "too-high": ("6", "--stars"),
    "negative": ("-1", "--rated-min"),
}

_PLEX_RATING_PREDICATES = {
    "zero": ("track", 0.0),
    "negative": ("track", -1.0),
    "half-star": ("track", 0.5),
    "one-star": ("track", 1.0),
    "four-stars": ("track", 4.0),
    "between-half-stars": ("track", 4.25),
    "album": ("album", 3.0),
}

_PLEX_BUILD_FILTERS = {
    "nothing-asked-for": ({}, "track"),
    "every-field": (
        {
            "artist": "Example Artist",
            "album": "Example Album",
            "track": "Example Track",
            "genre": "jazz",
            "mood": "calm",
            "style": "bebop",
            "year": "1959",
        },
        "track",
    ),
    "mood-scopes-to-the-libtype": ({"mood": "calm"}, "artist"),
    "genre-scopes-to-the-artist": ({"genre": "jazz"}, "album"),
    "blank-values-are-skipped": ({"artist": "", "album": None, "track": "Example Track"}, "track"),
    "rated-min": ({"rated_min": "4"}, "track"),
    "rated-min-half": ({"rated_min": "0.5"}, "track"),
    "rated-min-zero": ({"rated_min": "0"}, "track"),
    "rated-min-refused": ({"rated_min": "nine"}, "track"),
}

_PLEX_LEFTOVERS = {
    "clean": {},
    "one": {"userRating__gte": 8},
    "several": {"viewCount__gt": 1, "userRating__gte": 8},
}

_PLEX_RELATIVE_DATES = {
    "days": ("30d", "--since"),
    "signed": ("-30d", "--since"),
    "months": ("6mon", "--since"),
    "years": ("2y", "--since"),
    "absolute": ("2024-01-31", "--since"),
    "padded": ("  30d  ", "--since"),
    "prose": ("last week", "--since"),
    "unknown-unit": ("30x", "--since"),
}

_PLEX_SORTS = {
    "omitted": (None, "--sort"),
    "empty": ("", "--sort"),
    "bare-field": ("addedAt", "--sort"),
    "with-direction": ("addedAt:desc", "--sort"),
    "upper-case-direction": ("addedAt:DESC", "--sort"),
    "padded": ("  addedAt:asc  ", "--sort"),
    "comma-joined-field": ("artist.titleSort,album.year:desc", "--sort"),
    "no-field": (":desc", "--sort"),
    "unknown-direction": ("addedAt:sideways", "--sort"),
}

_PLEX_CONSTANTS = (
    "LIBTYPES",
    "POINTS_PER_STAR",
    "BARE_OPERATOR",
    "RATING_OPERATOR",
    "RATED_MIN_ZERO_NOTE",
    "SORT_DIRECTIONS",
    "RELATIVE_DATE",
    "ABSOLUTE_DATE",
)

_PLEX_FILTER_CASES = (
    *(f"constant:{name}" for name in _PLEX_CONSTANTS),
    "field_map:every-flag",
    *(f"stars:{name}" for name in _PLEX_STARS),
    *(f"parse_stars:{name}" for name in _PLEX_PARSE_STARS),
    "describe_filter:three-keys-in-order",
    *(f"rating_predicate:{name}" for name in _PLEX_RATING_PREDICATES),
    *(f"build_filters:{name}" for name in _PLEX_BUILD_FILTERS),
    *(f"assert_server_side:{name}" for name in _PLEX_LEFTOVERS),
    *(f"parse_relative_date:{name}" for name in _PLEX_RELATIVE_DATES),
    *(f"parse_sort:{name}" for name in _PLEX_SORTS),
)


def _plex_filter_call(get, case: str):
    """The zero-argument call one scenario names, resolved by the tool's own names.

    ``get`` maps a name as ``music.py`` spells it to the object under test, so the
    one renamed definition costs a lookup here rather than a second scenario table.
    """
    head, _, detail = case.partition(":")
    if head == "constant":
        value = get(detail)
        return lambda: value
    if head == "field_map":
        field_map = get("FIELD_MAP")
        return lambda: {
            flag: {libtype: build(libtype) for libtype in get("LIBTYPES")}
            for flag, build in sorted(field_map.items())
        }
    if head == "stars":
        return lambda: get("stars")(_PLEX_STARS[detail])
    if head == "parse_stars":
        raw, flag = _PLEX_PARSE_STARS[detail]
        return lambda: get("parse_stars")(raw, flag=flag)
    if head == "describe_filter":
        return lambda: get("describe_filter")("artist.genre", get("BARE_OPERATOR"), "jazz")
    if head == "rating_predicate":
        libtype, value = _PLEX_RATING_PREDICATES[detail]
        return lambda: get("rating_predicate")(libtype, value)
    if head == "build_filters":
        parsed, libtype = _PLEX_BUILD_FILTERS[detail]
        return lambda: get("build_filters")(dict(parsed), libtype)
    if head == "assert_server_side":
        return lambda: get("_assert_server_side")(dict(_PLEX_LEFTOVERS[detail]))
    if head == "parse_relative_date":
        raw, flag = _PLEX_RELATIVE_DATES[detail]
        return lambda: get("parse_relative_date")(raw, flag=flag)
    if head == "parse_sort":
        raw, flag = _PLEX_SORTS[detail]
        return lambda: get("parse_sort")(raw, flag=flag)
    raise AssertionError(f"no such plex filter scenario: {case!r}")


def _plex_outcome(call, recovery_of) -> str:
    """What one scenario answered, value or refusal, as one comparable string."""
    try:
        value = call()
    except Exception as exc:
        lines = recovery_of(exc)
        if lines is None:
            # Not one of the error types either copy raises deliberately. The type
            # and the message are still the answer, and still have to agree.
            return f"raised {type(exc).__name__}: {exc}"
        code = getattr(exc, "code", None) or "-"
        return _rendered_failure(f"raised {type(exc).__name__} {code}: {exc.message}", lines)
    if isinstance(value, _REGEX_TYPE):
        return f"regex {value.pattern!r}"
    return f"{type(value).__name__} {value!r}"


def _plex_capture_recovery(exc):
    """The lines the tool would print, straight off the error it raised."""
    if isinstance(exc, source_module("plex", "errors").AxiError):
        return list(exc.help_lines)
    return None


def _plex_subject_recovery(exc):
    """The same lines, rendered here from intent -- and proved not to carry the name.

    A recovery that reproduces the tool's bytes because it *stores* the tool's name
    has been copied rather than extracted, and the rendered line alone cannot tell
    the two apart. So each one is rendered a second time under another name, and one
    that still says ``plex-axi`` is reported in place of the line it produced.

    Unconditionally, not only where :func:`~axi_toolkit.errors.mentions_tool` says the
    name is expected. That gate is right for an intent :func:`~axi_toolkit.render.cli.parse`
    produced -- it has already put the name in a slot -- and wrong for one written by
    hand, which is what these two modules hold. Gated, this missed a note carrying
    ``plex-axi`` as literal text, which is precisely the defect it exists to catch.
    """
    if not isinstance(exc, errors.AxiError):
        return None
    lines = []
    for item in exc.recovery:
        if "plex-axi" in cli.line(item, "other-tool"):
            lines.append(f"<the tool's name is baked into the intent: {item!r}>")
        else:
            lines.append(cli.line(item, "plex-axi"))
    return lines


#: The pure half of the tool's ``music.py``, executed once out of its own source.
_SOURCE_FILTERS: dict = {}

#: Module-level imports the moved half is allowed to need. Anything else in that
#: file is the probing layer's, and importing the module whole would pull in the
#: tool's transport and, through it, a client library the capture must not need.
_PLEX_PURE_IMPORTS = frozenset({"math", "re"})


def _source_filters() -> dict:
    """The moved definitions, taken out of the tool's ``music.py`` and executed here.

    Not imported. ``music.py`` imports the tool's transport, which imports
    ``plexapi``, and a capture that needed a client library installed would be a
    capture nobody could reproduce. The module's own syntax tree is filtered down
    to its standard-library imports and the definitions the boundary names, and
    that subset runs against the tool's own error types -- so what is measured is
    the tool's code, byte for byte, and not a paraphrase of it.
    """
    if _SOURCE_FILTERS:
        return _SOURCE_FILTERS
    source = (source_root("plex") / "music.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    wanted = set(_PLEX_FILTER_BOUNDARY)
    kept: list = []
    found: set = set()
    for node in tree.body:
        segment = "".join(lines[node.lineno - 1 : node.end_lineno])
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            kept.append(segment)
            continue
        if isinstance(node, ast.Import) and all(a.name in _PLEX_PURE_IMPORTS for a in node.names):
            kept.append(segment)
            continue
        names = _bound_names(node) & wanted
        if names:
            kept.append(segment)
            found |= names
    missing = sorted(wanted - found)
    if missing:
        raise RuntimeError(
            f"the boundary names {missing}, which the tool's music.py no longer defines"
        )
    errors_module = source_module("plex", "errors")
    namespace = {"AxiError": errors_module.AxiError, "UsageError": errors_module.UsageError}
    exec(compile("".join(kept), "<the moved half of music.py>", "exec"), namespace)
    _SOURCE_FILTERS.update(namespace)
    return _SOURCE_FILTERS


def capture_plex_id_behaviour() -> list:
    module = source_module("plex", "ids")

    def validate(raw, invocation):
        return module.validate_rating_key(
            raw, invocation=" ".join(("plex-axi", *_PLEX_INVOCATIONS[invocation]))
        )

    return [
        {
            "case": case,
            "expected": _plex_outcome(
                _plex_id_call(module, validate, case), _plex_capture_recovery
            ),
        }
        for case in _PLEX_ID_CASES
    ]


def subject_plex_id_behaviour(case: str) -> str:
    from axi_toolkit.plex import ids

    def validate(raw, invocation):
        return ids.validate_rating_key(raw, command=_PLEX_INVOCATIONS[invocation])

    return _plex_outcome(_plex_id_call(ids, validate, case), _plex_subject_recovery)


def capture_plex_filter_behaviour() -> list:
    namespace = _source_filters()
    return [
        {
            "case": case,
            "expected": _plex_outcome(
                _plex_filter_call(namespace.__getitem__, case), _plex_capture_recovery
            ),
        }
        for case in _PLEX_FILTER_CASES
    ]


def subject_plex_filter_behaviour(case: str) -> str:
    from axi_toolkit.plex import filters

    def get(name: str):
        return getattr(filters, _PLEX_FILTER_BOUNDARY[name])

    return _plex_outcome(_plex_filter_call(get, case), _plex_subject_recovery)


# ================================================================ differential


def _pair(subject: str, values: dict[str, str]) -> dict:
    return {"subject": subject, "ha": values["ha"], "plex": values["plex"]}


def capture_encoder_digest() -> list[dict]:
    digests = {
        tool: hashlib.sha256((source_root(tool) / "toon.py").read_bytes()).hexdigest()
        for tool in TOOLS
    }
    return [_pair("toon.py", digests)]


def subject_encoder_digest(name: str) -> str:
    return hashlib.sha256(Path(toon.__file__).read_bytes()).hexdigest()


def capture_error_contract() -> list[dict]:
    """Only the rows both tools have.

    The intersection is machine-decided rather than chosen: a type one tool declares
    and the other does not is not a contract they share, and asserting agreement on it
    would report a divergence that is really a difference in scope. The union is a
    separate, capability-kind fact.
    """
    per_tool = {}
    for tool in TOOLS:
        tree = _tree(tool, "errors")
        exits = _module_literals(tree, lambda name: name.startswith("EXIT_"))
        rows = {f"exit:{name}": str(value) for name, value in exits.items()}
        for cls in _class_names(tree):
            rows[f"declares:{cls}"] = "yes"
        per_tool[tool] = rows
    shared = sorted(set(per_tool["ha"]) & set(per_tool["plex"]))
    return [_pair(name, {tool: per_tool[tool][name] for tool in TOOLS}) for name in shared]


def subject_error_contract(name: str) -> str:
    head, _, detail = name.partition(":")
    if head == "exit":
        return str(getattr(errors, detail, "<absent>"))
    return "yes" if isinstance(getattr(errors, detail, None), type) else "no"


_REDACTION_ROWS = ("REDACTED", "MIN_SECRET_LENGTH", "regex:_JWT", "regex:_BEARER")


def capture_redaction_contract() -> list[dict]:
    per_tool = {}
    for tool in TOOLS:
        tree = _tree(tool, "output")
        literals = _module_literals(tree, lambda name: name in ("REDACTED", "MIN_SECRET_LENGTH"))
        regexes = _regex_sources(tree)
        per_tool[tool] = {
            "REDACTED": str(literals.get("REDACTED", "<absent>")),
            "MIN_SECRET_LENGTH": str(literals.get("MIN_SECRET_LENGTH", "<absent>")),
            "regex:_JWT": regexes.get("_JWT", "<absent>"),
            "regex:_BEARER": regexes.get("_BEARER", "<absent>"),
        }
    return [_pair(row, {tool: per_tool[tool][row] for tool in TOOLS}) for row in _REDACTION_ROWS]


def subject_redaction_contract(name: str) -> str:
    if name == "REDACTED":
        return redact.REDACTED
    if name == "MIN_SECRET_LENGTH":
        return str(redact.MIN_SECRET_LENGTH)
    return {"regex:_JWT": redact.JWT, "regex:_BEARER": redact.BEARER}[name].pattern


_CREDENTIAL_ROWS = ("DEFAULT_TIMEOUT", "regex:_ILLEGAL_TOKEN")


def capture_credential_contract() -> list[dict]:
    per_tool = {}
    for tool in TOOLS:
        tree = _tree(tool, "config")
        literals = _module_literals(tree, lambda name: name == "DEFAULT_TIMEOUT")
        regexes = _regex_sources(tree)
        per_tool[tool] = {
            "DEFAULT_TIMEOUT": str(literals.get("DEFAULT_TIMEOUT", "<absent>")),
            "regex:_ILLEGAL_TOKEN": regexes.get("_ILLEGAL_TOKEN", "<absent>"),
        }
    return [_pair(row, {tool: per_tool[tool][row] for tool in TOOLS}) for row in _CREDENTIAL_ROWS]


def subject_credential_contract(name: str) -> str:
    from axi_toolkit import envconfig

    if name == "DEFAULT_TIMEOUT":
        return str(envconfig.DEFAULT_TIMEOUT)
    return envconfig.ILLEGAL_TOKEN.pattern
