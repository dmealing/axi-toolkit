"""The shared generators reproduce a consumer's committed output, byte for byte.

``project/`` is a small, synthetic consumer: a model under ``metaobjects/``, the config that
names ``axi_toolkit.metagen`` generators, a committed capture, and the files a regeneration
wrote, with the manifest that tells a hand edit from generated output. Running the toolchain
over a copy of its sources must give back exactly what is committed.

This needs the ``metagen`` extra, which needs Python 3.11, so on any other interpreter the
whole module skips. A skip must not read as a pass: ``scripts/ci-local.sh --only metagen``
runs it under an interpreter that has the toolchain and fails when it cannot.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("metaobjects", reason="the metagen extra (Python 3.11+) is not installed")

ROOT = Path(__file__).resolve().parents[2]
PROJECT = Path(__file__).resolve().parent / "project"
#: The package has no ``__main__``; this is what its console script runs.
_ENTRY = "import sys; from metaobjects.cli import main; sys.exit(main())"
SOURCES = ("metaobjects.config.yaml", "metaobjects", "fixtures")


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-c", _ENTRY, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _copy(into: Path, *names: str) -> Path:
    for name in names:
        source = PROJECT / name
        if source.is_dir():
            shutil.copytree(source, into / name)
        else:
            shutil.copy2(source, into / name)
    return into


def _tree(base: Path) -> dict:
    return {
        str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_regenerating_from_the_sources_reproduces_the_committed_files(tmp_path):
    _copy(tmp_path, *SOURCES)
    result = _run(tmp_path, "gen")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree(tmp_path / "generated") == _tree(PROJECT / "generated")


def test_the_committed_files_verify_clean(tmp_path):
    _copy(tmp_path, *SOURCES, "generated", ".metaobjects")
    result = _run(tmp_path, "verify", "--codegen")
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_hand_edit_to_a_generated_file_fails_verification(tmp_path):
    _copy(tmp_path, *SOURCES, "generated", ".metaobjects")
    target = tmp_path / "generated" / "package" / "rows.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert _run(tmp_path, "verify", "--codegen").returncode != 0


def test_no_project_name_is_stored_in_what_is_emitted():
    """Everything the output says about the model came from the model."""
    emitted = "\n".join(
        text.decode("utf-8") for text in _tree(PROJECT / "generated").values()
    ).lower()
    for name in ("plex", "hass", "home assistant"):
        assert name not in emitted


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (("reads: [name, colour]", "reads: [name, nowhere]"), "nowhere"),
        (('extends: "example::service::Lamp.id"', 'extends: "example::service::Lamp.nope"'), None),
        (
            (
                '{ name: name, extends: "example::rows::LampRow.name" }',
                '{ name: name, extends: "example::service::Lamp.name" }',
            ),
            "no default projection",
        ),
    ],
)
def test_a_model_that_does_not_hold_together_is_refused_before_anything_is_written(
    tmp_path, edit, message
):
    _copy(tmp_path, *SOURCES)
    path = tmp_path / "metaobjects" / "meta.rows.yaml"
    text = path.read_text(encoding="utf-8")
    old, new = edit
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    result = _run(tmp_path, "gen")
    assert result.returncode != 0
    if message:
        assert message in result.stdout + result.stderr
    assert not (tmp_path / "generated").exists()
