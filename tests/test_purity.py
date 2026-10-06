"""The pure modules import no HTTP library, and the distribution declares no dependency.

Verified, not assumed. One source tool installs with exactly one runtime dependency and
the other with exactly one; a transport pulled in here would land in both of them
without either asking for it, and the person who noticed would be a user whose install
grew.

The import check runs in a subprocess with a clean interpreter, because a check inside
the test session would find every module pytest, the conformance projections and the
other tests have already imported.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Anything that speaks a network protocol, and the two clients the source tools use.
#: ``urllib.parse`` is deliberately absent: splitting a URL is string handling, and it
#: opens no socket.
FORBIDDEN = (
    "http.client",
    "urllib.request",
    "urllib3",
    "socket",
    "ssl",
    "asyncio",
    "httpx",
    "requests",
    "aiohttp",
    "websockets",
    "websocket",
    "plexapi",
    "pydantic",
    "yaml",
    "metaobjects",
)

#: Every importable module in the package, packages included. Hand-written because each
#: name is a subprocess and the list is short -- and checked against the tree below,
#: because a module that arrives without being added here is one this suite silently
#: stops making its promise about, which is how the promise would first be broken.
MODULES = (
    "axi_toolkit",
    "axi_toolkit.errors",
    "axi_toolkit.redact",
    "axi_toolkit.envconfig",
    "axi_toolkit.toon",
    "axi_toolkit.toon_spec",
    "axi_toolkit.render",
    "axi_toolkit.render.cli",
    "axi_toolkit.render.prose",
    "axi_toolkit.ha",
    "axi_toolkit.ha.services",
    "axi_toolkit.plex",
    "axi_toolkit.plex.ids",
    "axi_toolkit.plex.filters",
)

#: The development subpackage: generators that run inside the MetaObjects toolchain, which
#: needs Python 3.11 and a third-party loader. None of the modules above may import it, and
#: importing any of them must not load it. Named separately so that the check below still
#: says "every module in the package is one of these" while saying where these two sit.
METAGEN_MODULES = (
    "axi_toolkit.metagen",
    "axi_toolkit.metagen.emit",
    "axi_toolkit.metagen.model",
)


#: The dynamic loader's own variables: read by the operating system before an
#: interpreter exists, and carried into the child when the parent has them. That is
#: not a hole in the scrub below -- a loader path cannot put a module on ``sys.path``,
#: and the two variables that can are still the only ones set deliberately.
#:
#: Dropping them is what made this suite red. ``actions/setup-python`` installs
#: interpreters built ``--enable-shared`` whose RUNPATH names the *GitHub-hosted*
#: tool-cache location, so anywhere else -- a self-hosted runner, a pyenv build -- the
#: child resolves ``libpython3.X.so.1.0`` only through ``LD_LIBRARY_PATH``, and without
#: it exits 127 having run no Python at all.
#:
#: The legs that failed were the safe half. Where the host happened to ship a
#: same-minor ``libpython``, the child started on *that* one instead and reported
#: success: a 3.11.16 job was checking 3.11.0rc1's standard library, and a 3.10.21 job
#: was checking 3.10.12's. ``_imported_after`` asserts the child's version to stop that
#: substitution from ever being quiet again.
_LOADER_VARS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH")


def _child_environment() -> dict[str, str]:
    """The child's whole environment: two deliberate entries, plus the loader's."""
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}
    env.update({name: os.environ[name] for name in _LOADER_VARS if name in os.environ})
    return env


def _imported_after(module: str) -> set[str]:
    """Every module name loaded by a fresh interpreter that imported ``module``."""
    program = textwrap.dedent(
        f"""
        import sys, json
        before = set(sys.modules)
        import {module}   # noqa: F401
        print(json.dumps({{
            "version": list(sys.version_info[:3]),
            "modules": sorted(set(sys.modules) - before),
        }}))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=_child_environment(),
        check=False,
    )
    # Four days of red were spent decoding a bare `CalledProcessError: exit 127` out of
    # a hundred-kilobyte log. The reason is always on the child's stderr; say it.
    assert result.returncode == 0, (
        f"the child interpreter failed to import {module} "
        f"(exit {result.returncode}): {result.stderr.strip() or '<no stderr>'}"
    )
    reply = json.loads(result.stdout.strip().splitlines()[-1])
    assert tuple(reply["version"]) == sys.version_info[:3], (
        "the child ran a different interpreter than the one under test: "
        f"{'.'.join(str(part) for part in reply['version'])} "
        f"rather than {'.'.join(str(part) for part in sys.version_info[:3])}"
    )
    return set(reply["modules"])


@pytest.mark.parametrize("module", MODULES)
def test_importing_a_module_loads_no_http_library(module):
    loaded = _imported_after(module)
    offenders = sorted(
        name for name in loaded if name.split(".")[0] in FORBIDDEN or name in FORBIDDEN
    )
    assert offenders == [], f"{module} pulled in {offenders}"


def test_every_module_in_the_package_is_one_of_the_modules_checked():
    """The list above is only a promise about the package while it names all of it."""
    package = ROOT / "src" / "axi_toolkit"
    found = set()
    for path in package.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(package.parent).with_suffix("").parts
        found.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
    expected = set(MODULES) | set(METAGEN_MODULES)
    assert found == expected, (
        "modules not checked for purity: "
        f"{sorted(found - expected)}; named but absent: {sorted(expected - found)}"
    )


def test_the_whole_package_imports_with_nothing_installed():
    """No third-party name may appear at all, however harmless it looks."""
    loaded = _imported_after("axi_toolkit.render.cli")
    third_party = sorted(
        name
        for name in loaded
        if name and not name.startswith(("axi_toolkit", "_")) and name.split(".")[0] in FORBIDDEN
    )
    assert third_party == []


def test_the_distribution_declares_no_runtime_dependency():
    """`dependencies = []` is the promise; this is the thing that keeps it."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    body = text.split("dependencies = ", 1)[1]
    assert body.startswith("[]"), "the runtime dependency list is no longer empty"


def test_the_optional_extras_are_the_ones_the_layout_specifies():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    declared = {line.split("=")[0].strip() for line in section.splitlines() if " = " in line}
    assert {"ha", "plex", "cli"} <= declared
    assert "ha = []" in section, "the Home Assistant transport is stdlib and must stay empty"
    assert "cli = []" in section, "argspec and help live in each tool, not here"


@pytest.mark.parametrize("module", MODULES)
def test_importing_a_library_module_never_loads_the_generators(module):
    loaded = _imported_after(module)
    assert sorted(name for name in loaded if name.startswith("axi_toolkit.metagen")) == []


def test_no_library_source_names_the_generators():
    """Importing is the behaviour; this is the line that would start it."""
    package = ROOT / "src" / "axi_toolkit"
    offenders = []
    for path in package.rglob("*.py"):
        if "metagen" in path.relative_to(package).parts[:1] or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            if any("metagen" in name.split(".") for name in names):
                offenders.append(str(path.relative_to(package)))
    assert offenders == []


def test_the_generators_import_only_the_standard_library_and_the_toolchain():
    """Their one third-party import is the loader's generator interface."""
    package = ROOT / "src" / "axi_toolkit" / "metagen"
    found = set()
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                found.add((node.module or "").split(".")[0])
    assert found - {"__future__", "json", "dataclasses"} == {"metaobjects"}


def test_the_generators_ride_in_a_development_extra_that_declares_the_toolchain():
    """The pin is what makes an install on Python 3.9 fail instead of installing nothing."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    extra = section.split("\nmetagen = [", 1)[1].split("]", 1)[0]
    assert [line.strip() for line in extra.splitlines() if line.strip()] == [
        '"metaobjects==1.0.13",'
    ]
    comment = section.split("\nmetagen = [", 1)[0].rsplit("\n\n", 1)[-1]
    assert "3.11" in comment, "the extra must say what Python it needs"


def test_the_package_floor_is_unmoved_by_the_extra():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.9"' in text
