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

import json
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

MODULES = (
    "axi_core",
    "axi_core.errors",
    "axi_core.redact",
    "axi_core.envconfig",
    "axi_core.toon",
    "axi_core.toon_spec",
    "axi_core.render.cli",
    "axi_core.render.prose",
)


def _imported_after(module: str) -> set[str]:
    """Every module name loaded by a fresh interpreter that imported ``module``."""
    program = textwrap.dedent(
        f"""
        import sys, json
        before = set(sys.modules)
        import {module}   # noqa: F401
        print(json.dumps(sorted(set(sys.modules) - before)))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("module", MODULES)
def test_importing_a_module_loads_no_http_library(module):
    loaded = _imported_after(module)
    offenders = sorted(
        name for name in loaded if name.split(".")[0] in FORBIDDEN or name in FORBIDDEN
    )
    assert offenders == [], f"{module} pulled in {offenders}"


def test_the_whole_package_imports_with_nothing_installed():
    """No third-party name may appear at all, however harmless it looks."""
    loaded = _imported_after("axi_core.render.cli")
    third_party = sorted(
        name
        for name in loaded
        if name and not name.startswith(("axi_core", "_")) and name.split(".")[0] in FORBIDDEN
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
