# Conformance pack

Language-neutral JSON that any implementation of the toolkit's contract judges itself
against. The Python package in `src/axi_toolkit` is the reference: it writes this
directory, and a test regenerates it on every run and requires the committed bytes, so
the pack cannot drift from Python. A second implementation in this repository reads these
files in place; there is no vendored copy and nothing to sync.

| file | what it holds |
| --- | --- |
| `recovery.json` | every recovery line the two source tools print, as `{tool, line, intent, sentence, other}`: parse `line` under `tool` to `intent` (the wire form), render it back to `line`, as prose to `sentence`, and for the tool named in `sibling` to `other` |
| `render-rules.json` | one recovery per rendering rule with its shell line and prose sentence for two tools; hand-written wire forms (an absent `lead` on a `run` or `retry` takes the factory default) with the form they normalise to; wire forms that must be refused; shell lines to parse |
| `errors.json` | exit codes, fault classes, fail-closed classification, the exception names and exit codes, and the JSON wire form of an error |
| `credentials.json` | each tool's credential declaration as data, URL normalisation, the failure messages and recovery of every misconfiguration scenario, successful loads, and `describe_environment` / `missing_vars` |
| `redaction.json` | the order of application, the built-in and per-tool patterns in ECMAScript syntax (`{source, flags}`), the registered literals, and redaction cases |
| `toon-spec.json` | where the TOON encode fixtures are (below) |
| `checksums.txt` | `sha256sum` lines over the JSON files above |

Wire form, as written by `Recovery.as_dict()`: `kind` first, then the kind's fields in
sorted order, a note's text under `text`, and a field omitted when it holds its unset
value (`""`, an empty list, a `" "` separator), except the `lead` of a `run` or `retry`,
which is always written, an empty one included, because an absent lead means the factory
default.

A redaction input is never a credential-shaped string. It is a list of literal strings and
`{"ref": name}` markers, and `fragments` holds the recipe for each name (parts to join, or a
header, payload and signature to base64url-encode without padding into a token). The reader
assembles the text at run time, which is also how `tests/test_redact.py` builds its samples.

## The TOON fixtures

They stay where they are, inside the Python package, because the wheel ships them so a
downstream tool can run the rig against its own encoder. `toon-spec.json` gives the paths
relative to this directory (`../src/axi_toolkit/toon_spec/encode/`, its `checksums.txt`,
`LICENSE` and `PROVENANCE.md`). A package that must carry them in its own tarball copies
them at build time from that path rather than keeping a second source of truth.

## Regenerating

```sh
.venv/bin/python scripts/conformance_pack.py
```

The pack is built from the committed `tests/conformance/capture.json` and the package
itself (`tests/conformance/pack.py`), so no source checkout or network is needed. Never
edit these files by hand.
