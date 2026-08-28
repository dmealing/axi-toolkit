# Vendored TOON conformance fixtures

`encode/` is a byte-for-byte copy of the official, language-agnostic TOON test fixtures.

| | |
| --- | --- |
| Upstream | <https://github.com/toon-format/spec> |
| Upstream path | `tests/fixtures/encode/` inside the upstream clone — the vendored copy is `src/axi_toolkit/toon_spec/encode/` |
| Spec version | 4.1.1 (SPEC.md v4.1, released 2026-08-05) |
| Commit | `62f16b369408180f1faf1cba7da1b46d1f336f12` |
| Licence | MIT — the copy in this repository is `src/axi_toolkit/toon_spec/LICENSE`, from the same commit |

## Why these live inside the package and not under `tests/`

Two sibling AXI CLIs each carried their own copy of the encoder **and** their own copy
of these fixtures. One copy took a fix for two `MUST` rules; the other did not. Both
suites stayed green, because each was judging its own copy, and the divergence only
surfaced when somebody ran both encoders against one set of files: 179/179 against
177/179.

One copy of the encoder only fixes that if there is also one copy of the rig that
judges it. `axi_toolkit.toon_spec.run(encode)` takes the encoder as an argument, so a tool
that installs this package asserts its own score against these files instead of
re-vendoring 179 cases and hoping they stayed in step — and the same call is what
measures a *different* encoder, which is how the divergence was found.

`checksums.txt` records the SHA-256 of each vendored file, and
`axi_toolkit.toon_spec.digest_mismatches()` is asserted by the suite: a fixture edited to
make a failing encoder pass is no longer the specification's opinion, and the edit has
to be visible rather than silent.

## What is not vendored, and why

- **`decode/`** — `axi_toolkit.toon` is an encoder only. Vendoring decode fixtures would
  add 14 files that nothing can run.
- **§3 host-type normalisation** (NaN, ±Infinity, host `Date`/`Set`/`Map`/`BigInt`) —
  upstream states this is deliberately outside the JSON fixtures, because the fixture
  format cannot express a non-JSON encode input. `tests/test_toon.py` covers it in
  Python instead.

## One naming difference, in the option, not the output

The fixtures spell the indentation option `indentSize`; this encoder's keyword argument
is `indent`. `axi_toolkit.toon_spec.encoder_kwargs` maps one to the other in a single
documented place, and raises on an option it does not apply rather than running the
case with default settings and reporting a pass. That is a difference in the encoder's
API surface (spec §13), not in a single byte it emits.

## Refreshing

```sh
git clone --depth 1 https://github.com/toon-format/spec.git       # into a scratch directory
cp <clone>/tests/fixtures/encode/*.json src/axi_toolkit/toon_spec/encode/
cp <clone>/LICENSE src/axi_toolkit/toon_spec/LICENSE
(cd src/axi_toolkit/toon_spec/encode && sha256sum *.json) > src/axi_toolkit/toon_spec/checksums.txt
python scripts/reqgen.py capture          # the published case count is a captured fact
pytest tests/test_toon_conformance.py
```

Then update the table above with the new commit and version, and update `CASE_COUNT` in
`tests/test_toon_conformance.py` if upstream added cases. A refresh that changes an
expected output is a specification change and belongs in its own commit, separate from
any encoder change made to satisfy it.

Re-vendoring rewrites `checksums.txt` in the same commit, so no automated gate compares
the new content against the old: re-read what the `PATH_ALLOWANCES` entry in
`scripts/leakcheck.py` now covers before committing. The suite pins the shapes an entry
exempts, but only a person can confirm a new shape still names nobody and reaches
nothing.
