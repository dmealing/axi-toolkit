#!/usr/bin/env bash
# Local CI — every check `.github/workflows/ci.yml` runs, runnable without GitHub.
#
# GitHub Actions is disabled on this repository, so the workflow's jobs run
# nowhere unless something local runs them. This script is that something: the
# no-mistakes gate calls it (see `.no-mistakes.yaml`), a developer can run it
# before pushing, and `ci.yml` calls it one section per job, so the checks are
# the same whether or not Actions ever comes back.
#
# Sections, in the order a bare run executes them:
#
#   leakcheck     scripts/leakcheck.py --demo, then the scan of every tracked file
#   commits       scripts/commitcheck.py --demo, then --since-release with
#                 --pull-requests require, or auto with no GitHub token (see below)
#   lint          ruff check . && ruff format --check .
#   test          pytest, once, on the interpreter that built .venv
#   requirements  scripts/reqgen.py list, then scripts/reqgen.py check
#   metagen       tests/metagen under the MetaObjects toolchain (see below)
#   drift         fetch both source tools at their main, then scripts/reqgen.py
#                 check and scripts/reqgen.py drift against them (see below)
#
# Usage:
#   scripts/ci-local.sh                        # every section
#   scripts/ci-local.sh --only lint            # one section; repeat --only for more
#   scripts/ci-local.sh --matrix               # also run pytest on every MATRIX_PYTHONS
#   scripts/ci-local.sh --help
#
# THE TEST MATRIX DECISION. `test` runs the suite once, on the interpreter that
# built .venv. That is what the gate runs, because it is the cost every change
# pays. The supported range (3.9 through 3.12; `requires-python = ">=3.9"` in
# pyproject.toml) is checked on demand with `--matrix`, which builds a throwaway
# `uv` venv per version and runs pytest in each. `--matrix` needs `uv` on PATH
# and fails if it is missing, because a matrix that silently ran nothing reads
# like one that passed. Override the versions with MATRIX_PYTHONS="3.9 3.12".
#
# THE TOKEN. `commits` reads pull request bodies from GitHub, because a body can
# replace a commit message outright. The token comes from GITHUB_TOKEN, then
# GH_TOKEN, then `gh auth token`. When none can be obtained the --since-release
# audit still runs, over every git-side message, under --pull-requests auto:
# only the pull-request-body half is skipped, the SKIP line says so, and
# commitcheck prints its own not-consulted note beside the verdict.
#
# METAGEN. `axi_toolkit.metagen` holds the generators a tool's own MetaObjects config
# names, and they need the toolchain, which needs Python 3.11 -- more than this
# package's floor, and more than a bare `pytest` run can count on. tests/metagen skips
# where the toolchain is absent, and a skip is not a pass, so this section is the one
# that runs it: under `uvx --python 3.12` with the pinned toolchain, never touching
# .venv. Like `--matrix` it fails without `uv` on PATH rather than passing unrun.
#
# DRIFT. Every other section reads only this repository, which is the design:
# the suite needs no source checkout and no network. The price is that it judges
# this package against a capture, and the capture is only as current as the last
# time somebody ran one. `drift` is the section that goes and looks. It makes a
# shallow clone of each tool's main in a throwaway directory of this run's own,
# under AXI_TOOLKIT_DRIFT_CACHE (default
# ${XDG_CACHE_HOME:-~/.cache}/axi-toolkit/drift) and removed when the run ends,
# then re-reads every fact from them, and fails when the committed capture is
# not what they say now or a tool is not running on this package's encoder alone:
# it carries a toon.py of its own, does not import axi_toolkit.toon, or accepts
# an axi-toolkit older than the release that fixed the encoder. A renamed
# package or command, a new redaction shape and a changed recovery line all land
# there. Nothing is shared between runs, because runs
# overlap on one machine: one cached tree, rewritten in place by whichever run
# fetched last, is a tree another run is importing modules out of, and the race
# fails them both. Reading a tool imports its modules, so this section runs the
# tools' own code from main, exactly as `reqgen capture` does.
#
# Set AXI_TOOLKIT_SOURCE_HA or AXI_TOOLKIT_SOURCE_PLEX to judge an existing
# checkout instead of fetching that tool: a branch of the tool, before it lands.
#
# With no network the section cannot answer, and it says so rather than passing:
# it prints a SKIPPED line and FAILS. AXI_TOOLKIT_ALLOW_OFFLINE=1 is the explicit
# override; the SKIPPED line is still printed, the section is reported as
# SKIPPED and never as PASS, and the run's last line names it. The override does
# not skip a fetch that would have worked.
#
# NOT COVERED. hygiene.yml's pull request title and body leak scan
# (`leakcheck.py --pull-request N`) has no local home: the text it scans exists
# only on GitHub, after the pull request is opened.
#
# The environment is .venv, built by `scripts/dev-setup.sh --reqgen` when it is
# missing or lacks what a section imports (so that build needs Python 3.11+),
# and every tool is called as .venv/bin/<tool> — never off PATH, for the reason
# AGENTS.md gives under "The development environment".
#
# To reuse this shape elsewhere: each section is one function named `sec_<name>`
# and one entry in SECTIONS. Nothing else needs to change.
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root" || exit 1

SECTIONS=(leakcheck commits lint test requirements metagen drift)
METAOBJECTS=${METAOBJECTS:-"metaobjects==1.0.13"}
MATRIX_PYTHONS=${MATRIX_PYTHONS:-"3.9 3.10 3.11 3.12"}

usage() { sed -n '2,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'; }

only=()
matrix=0
while [ $# -gt 0 ]; do
  case $1 in
    --only)
      [ $# -ge 2 ] || { echo "ci-local: --only needs a section: ${SECTIONS[*]}" >&2; exit 2; }
      case " ${SECTIONS[*]} " in
        *" $2 "*) only+=("$2") ;;
        *) echo "ci-local: unknown section '$2'; sections: ${SECTIONS[*]}" >&2; exit 2 ;;
      esac
      shift 2 ;;
    --matrix) matrix=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) echo "ci-local: unknown argument '$1'; see --help" >&2; exit 2 ;;
  esac
done
[ ${#only[@]} -gt 0 ] || only=("${SECTIONS[@]}")

# Build .venv when it lacks what a section imports. `test` and `lint` need only
# .[dev], which keeps a 3.9 venv usable; `requirements` needs .[dev,reqgen].
ensure_venv() {
  if ! .venv/bin/python -c "import $1" >/dev/null 2>&1; then
    scripts/dev-setup.sh --reqgen
  fi
}

sec_leakcheck() {
  python3 scripts/leakcheck.py --demo
  python3 scripts/leakcheck.py
}

sec_commits() {
  python3 scripts/commitcheck.py --demo
  # Ask commitcheck's own resolver whether a token exists, so the order it
  # tries them in is written once.
  if python3 -c 'import sys; sys.path.insert(0, "scripts"); import commitcheck; sys.exit(not commitcheck.github_token())'; then
    python3 scripts/commitcheck.py --since-release --pull-requests require
  else
    echo "SKIP: pull request bodies not consulted: no GitHub token (GITHUB_TOKEN, GH_TOKEN, gh auth token)"
    python3 scripts/commitcheck.py --since-release --pull-requests auto
  fi
}

sec_lint() {
  ensure_venv ruff
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
}

sec_test() {
  ensure_venv pytest
  .venv/bin/pytest
  [ "$matrix" -eq 1 ] || return 0
  command -v uv >/dev/null 2>&1 || { echo "ci-local: --matrix needs uv on PATH" >&2; return 1; }
  local v
  # Not local: the EXIT trap fires after this function has returned.
  matrix_tmp=$(mktemp -d)
  trap 'rm -rf "$matrix_tmp"' EXIT
  for v in $MATRIX_PYTHONS; do
    echo "--- pytest on Python $v"
    uv venv --quiet --python "$v" "$matrix_tmp/py$v"
    uv pip install --quiet --python "$matrix_tmp/py$v/bin/python" -e ".[dev]"
    "$matrix_tmp/py$v/bin/pytest"
  done
}

sec_requirements() {
  ensure_venv metaobjects
  .venv/bin/python scripts/reqgen.py list
  .venv/bin/python scripts/reqgen.py check
}

sec_metagen() {
  command -v uvx >/dev/null 2>&1 || { echo "ci-local: metagen needs uv on PATH" >&2; return 1; }
  # -rs prints why anything skipped, and the count line is checked: nothing may skip here.
  PYTHONPATH=src uvx --quiet --python 3.12 --from "$METAOBJECTS" --with pytest \
    pytest -p no:cacheprovider -rs tests/metagen | tee /dev/stderr | { ! grep -q 'skipped'; }
}

# One line per tool: the variable that names its checkout, the variable that
# overrides where it is fetched from, the default for that, and the cache name.
DRIFT_TOOLS=(
  "AXI_TOOLKIT_SOURCE_HA AXI_TOOLKIT_DRIFT_HA_URL https://github.com/dmealing/hass-axi.git hass-axi"
  "AXI_TOOLKIT_SOURCE_PLEX AXI_TOOLKIT_DRIFT_PLEX_URL https://github.com/dmealing/plex-axi.git plex-axi"
)
# A section returns this to say it could not run and was allowed not to.
SKIPPED_RC=77

# A shallow clone of one tool's main at $1, from $2. The destination belongs to
# this run alone, so the clone is the whole fetch: no shared tree is updated in
# place, and no run can rewrite a tree another run is reading.
fetch_main() {
  git clone --quiet --depth 1 --branch main "$2" "$1"
}

sec_drift() {
  local cache=${AXI_TOOLKIT_DRIFT_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/axi-toolkit/drift}
  local line source_var url_var default_url name url
  mkdir -p "$cache"
  # Not local, for the reason the comment under sec_test gives: the EXIT trap
  # fires after this function has returned, when the section's subshell ends
  # and nothing is reading the checkouts any more.
  work=$(mktemp -d "$cache/run.XXXXXX")
  trap 'rm -rf "$work"' EXIT
  for line in "${DRIFT_TOOLS[@]}"; do
    read -r source_var url_var default_url name <<<"$line"
    if [ -n "${!source_var:-}" ]; then
      echo "drift: $name is the checkout $source_var names; not fetched"
      continue
    fi
    url=${!url_var:-$default_url}
    if fetch_main "$work/$name" "$url"; then
      echo "drift: $name main is $(git -C "$work/$name" rev-parse --short HEAD)"
      export "$source_var=$work/$name"
      continue
    fi
    echo "SKIPPED: drift: $name could not be fetched, so nothing compared this package to the tools" >&2
    if [ "${AXI_TOOLKIT_ALLOW_OFFLINE:-}" = 1 ]; then
      echo "SKIPPED: drift: allowed by AXI_TOOLKIT_ALLOW_OFFLINE=1; run it again with a network before relying on this run" >&2
      return "$SKIPPED_RC"
    fi
    echo "drift: an unanswered drift check fails; AXI_TOOLKIT_ALLOW_OFFLINE=1 allows the skip" >&2
    return 1
  done
  ensure_venv metaobjects
  .venv/bin/python scripts/reqgen.py check
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/reqgen.py drift
}

# Each section runs in its own subshell under `set -e`, so its first failing
# command ends that section and not the run. The subshell must not sit in an
# `if` condition: bash ignores `set -e` there, and a section would run on past
# its own failure and report the last command's status. The same holds for the
# left side of `||`, which is why the status is read on the next line.
failed=()
passed=()
skipped=()
for s in "${only[@]}"; do
  printf '\n========== %s ==========\n' "$s"
  (set -e; "sec_$s")
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "PASS: $s"
    passed+=("$s")
  elif [ "$rc" -eq "$SKIPPED_RC" ]; then
    echo "SKIPPED: $s"
    skipped+=("$s")
  else
    echo "FAIL: $s" >&2
    failed+=("$s")
  fi
done

echo
if [ ${#failed[@]} -gt 0 ]; then
  echo "ci-local: FAILED: ${failed[*]}" >&2
  exit 1
fi
if [ ${#skipped[@]} -gt 0 ]; then
  echo "ci-local: passed: ${passed[*]:-nothing}; SKIPPED, not passed: ${skipped[*]}"
else
  echo "ci-local: passed: ${passed[*]}"
fi
