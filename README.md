# axi-toolkit

Shared toolkit for Agent eXperience Interface (AXI) command-line tools: errors that carry
recovery as **data**, the renderers that turn that data into a shell line or a sentence, a
strict TOON encoder, a redaction boundary, and environment-only credentials.

One contract, implemented once per language and judged by the same shared fixtures.

| directory | what it is | status |
| --- | --- | --- |
| [`python/`](python/) | the Python package, published to PyPI as `axi-toolkit`; the reference implementation | released, with its own [changelog](python/CHANGELOG.md) |
| [`ts/`](ts/) | the TypeScript port | not yet published |
| [`rust/`](rust/) | the Rust crate; reads `conformance/` and the Python package's TOON fixtures in place (plus an older v4.1.1 fixture set of its own) | not published (`publish = false`; outside release automation) |
| [`conformance/`](conformance/) | the language-neutral JSON pack every implementation judges itself against; written by the Python package, read in place by the others | shared |

`scripts/`, `vendor/`, `.githooks/` and `.github/` at the root serve the whole repository:
the leak scan, the commit-message guard, the local CI runner and the commit hooks.

## Using it

Install the Python package from PyPI:

```sh
pip install axi-toolkit
```

The package's README, API tables and development instructions are in
[`python/README.md`](python/README.md); the TypeScript port's are in [`ts/README.md`](ts/README.md); the Rust crate's are in [`rust/README.md`](rust/README.md).

## Developing

```sh
scripts/install-hooks.sh     # the pre-commit and commit-msg guards
scripts/ci-local.sh          # every check, Python, TypeScript and Rust (see --help for the sections)
```

Each package is versioned and released on its own. Only `python/` is a release-please
package today, so commits that touch only `ts/`, `rust/` or `conformance/` do not bump the Python
version, and the Python changelog lives in `python/CHANGELOG.md`.

This repository is public and must stay generic: no host addresses, credentials, real data
or local paths in any file, fixture, test or commit message. `scripts/leakcheck.py` enforces
it; `AGENTS.md` explains why.

## Licence

MIT. See [`LICENSE`](LICENSE); each package carries a copy.
