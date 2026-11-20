"""Argument-handling smoke tests for scripts/dev-setup.sh.

Tests only the cheap exit paths (those that exit before building a virtualenv or
installing anything). The suite must keep its property of running with no credentials,
no source checkouts and no network.
"""

import subprocess


def test_help_exits_0_and_prints_usage():
    result = subprocess.run(
        ["scripts/dev-setup.sh", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--reqgen" in result.stdout


def test_unrecognized_argument_exits_2():
    result = subprocess.run(
        ["scripts/dev-setup.sh", "--not-a-real-flag"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "unknown argument" in result.stderr


def test_python_with_no_value_exits_2():
    result = subprocess.run(
        ["scripts/dev-setup.sh", "--python"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--python needs an interpreter" in result.stderr


def test_python_naming_nonexistent_interpreter_exits_1():
    result = subprocess.run(
        ["scripts/dev-setup.sh", "--python", "python-does-not-exist-99"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "no such interpreter" in result.stderr
