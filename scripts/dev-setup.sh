#!/usr/bin/env sh
# Build this repository's development environment: a virtualenv at .venv with
# the package installed into it in editable mode. No other Python environment,
# console script or site-packages directory is created, modified or removed.
#
# WHY THIS IS A SCRIPT AND NOT A DOCUMENTED `pip install -e`. The tools that
# consume this package are normally installed as isolated user-level tools —
# one environment per tool, with a launcher on PATH pointing into it. An
# editable install into whatever interpreter happens to be ambient overwrites
# that launcher with one bound to the ambient interpreter and leaves an editable
# pointer at this checkout; when the checkout goes away, so does the reader's
# own working command. A contributor's throwaway clone must not be able to break
# the installation of the very tool they are contributing to. A virtualenv
# cannot do that: it excludes the user site by construction.
#
# The .venv location and the call-by-path invocation match
# .github/workflows/ci.yml, so this repository has one pattern rather than two.
set -e

usage() {
  cat <<'EOF'
Usage: scripts/dev-setup.sh [--reqgen] [--python INTERPRETER] [--recreate]

Creates .venv at the repository root and installs the package into it in
editable mode. No other Python environment, console script or site-packages
directory is created, modified or removed.

  --reqgen              also install the requirements-layer toolchain,
                        i.e. .[dev,reqgen]; needs Python 3.11 or newer
  --python INTERPRETER  build the virtualenv with this interpreter
                        (default: the first of python3, python3.11, python3.12,
                        python3.13 that meets the floor)
  --recreate            discard an existing .venv and build it again
  -h, --help            this text
EOF
}

extras='dev'
python=''
python_was_given=''
recreate=''

while [ "$#" -gt 0 ]; do
  case "$1" in
    --reqgen) extras='dev,reqgen' ;;
    --recreate) recreate='yes' ;;
    --python)
      shift
      [ "$#" -gt 0 ] || { echo "dev-setup: --python needs an interpreter" >&2; exit 2; }
      python="$1"
      python_was_given='yes'
      ;;
    --python=*) python="${1#--python=}"; python_was_given='yes' ;;
    -h|--help) usage; exit 0 ;;
    *) echo "dev-setup: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# The package's own floor is 3.9; the requirements-layer toolchain needs 3.11.
# That split is why the CI matrix and the requirements job differ, and it is the
# only reason this script cares which interpreter it is handed.
floor=9
case "$extras" in *reqgen*) floor=11 ;; esac

version_ok() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, int(sys.argv[1])) else 1)' \
    "$2" >/dev/null 2>&1
}

get_base_prefix() {
  "$1" -c 'import sys; print(sys.base_prefix)' 2>/dev/null
}

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"

# Decide whether a venv needs to be created, and if so select/validate an interpreter.
# Three paths: --recreate was given; .venv is missing/dangling; or .venv is healthy but
# doesn't match the floor or (when --python was given explicitly) the requested interpreter.
if [ -n "$recreate" ] || [ ! -x .venv/bin/python ]; then
  need_create='yes'
elif ! version_ok .venv/bin/python "$floor"; then
  echo "dev-setup: the existing .venv is older than 3.$floor; rebuilding it"
  need_create='yes'
elif [ -n "$python_was_given" ]; then
  # --python was given explicitly: the venv must match that interpreter.
  # Compare via sys.base_prefix, not the raw argument string.
  if [ -n "$python" ]; then
    command -v "$python" >/dev/null 2>&1 ||
      { echo "dev-setup: no such interpreter: $python" >&2; exit 1; }
    version_ok "$python" "$floor" ||
      { echo "dev-setup: $python is older than 3.$floor, which .[$extras] needs" >&2; exit 1; }
    requested_base=$(get_base_prefix "$python")
    venv_base=$(get_base_prefix .venv/bin/python)
    if [ "$requested_base" != "$venv_base" ]; then
      echo "dev-setup: the existing .venv is from a different interpreter; rebuilding it"
      need_create='yes'
    fi
  fi
fi

if [ -n "$need_create" ]; then
  # A venv will be created: select or validate the interpreter.
  if [ -n "$python" ]; then
    command -v "$python" >/dev/null 2>&1 ||
      { echo "dev-setup: no such interpreter: $python" >&2; exit 1; }
    version_ok "$python" "$floor" ||
      { echo "dev-setup: $python is older than 3.$floor, which .[$extras] needs" >&2; exit 1; }
  else
    for candidate in python3 python3.11 python3.12 python3.13; do
      if command -v "$candidate" >/dev/null 2>&1 && version_ok "$candidate" "$floor"; then
        python="$candidate"
        break
      fi
    done
    [ -n "$python" ] ||
      { echo "dev-setup: found no Python 3.$floor or newer; pass --python INTERPRETER" >&2; exit 1; }
  fi
  "$python" -m venv --clear .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e ".[$extras]"

echo
echo "dev-setup: .venv ready — $(.venv/bin/python -V 2>&1), extras: $extras"
echo "  .venv/bin/pytest                                  # the whole suite"
echo "  .venv/bin/ruff check . && .venv/bin/ruff format --check ."
case "$extras" in
  *reqgen*)
    echo "  .venv/bin/python scripts/reqgen.py list | check | generate"
    ;;
esac
echo "  scripts/install-hooks.sh                          # the commit guards"
echo "  scripts/leakcheck.py                              # what those hooks run"
