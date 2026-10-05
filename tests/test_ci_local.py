"""The drift section of scripts/ci-local.sh, on the paths that need no network.

The section's whole job is to reach two other repositories, so what can be tested
here is what it does when it cannot: that is the case a silent pass would hide. Both
tools are pointed at a location that does not exist, which fails the fetch at once and
without a network, and the two outcomes are stated -- a failure by default, and a skip
that is reported as a skip under the explicit override.
"""

from __future__ import annotations

import os
import subprocess

import pytest


@pytest.fixture
def run_drift(tmp_path):
    def run(**overrides):
        env = {
            key: value for key, value in os.environ.items() if not key.startswith("AXI_TOOLKIT_")
        }
        env.update(
            AXI_TOOLKIT_DRIFT_CACHE=str(tmp_path / "cache"),
            AXI_TOOLKIT_DRIFT_HA_URL=str(tmp_path / "no-such-repository"),
            AXI_TOOLKIT_DRIFT_PLEX_URL=str(tmp_path / "no-such-repository"),
            **overrides,
        )
        return subprocess.run(
            ["scripts/ci-local.sh", "--only", "drift"], capture_output=True, text=True, env=env
        )

    return run


def test_a_drift_check_that_cannot_fetch_the_tools_fails(run_drift):
    """Unanswered is not passed: nothing compared this package to the tools."""
    result = run_drift()
    assert result.returncode == 1
    assert "SKIPPED: drift: hass-axi could not be fetched" in result.stderr
    assert "AXI_TOOLKIT_ALLOW_OFFLINE=1" in result.stderr
    assert "FAIL: drift" in result.stderr
    assert "PASS: drift" not in result.stdout


def test_the_offline_override_reports_a_skip_and_never_a_pass(run_drift):
    result = run_drift(AXI_TOOLKIT_ALLOW_OFFLINE="1")
    assert result.returncode == 0
    assert "SKIPPED: drift: hass-axi could not be fetched" in result.stderr
    assert "SKIPPED: drift" in result.stdout
    assert "PASS: drift" not in result.stdout
    assert result.stdout.strip().splitlines()[-1] == (
        "ci-local: passed: nothing; SKIPPED, not passed: drift"
    )


def test_any_other_value_of_the_override_is_not_the_override(run_drift):
    assert run_drift(AXI_TOOLKIT_ALLOW_OFFLINE="yes").returncode == 1


def test_drift_is_a_section_the_script_names():
    result = subprocess.run(
        ["scripts/ci-local.sh", "--only", "no-such-section"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "drift" in result.stderr
