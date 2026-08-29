# axi-toolkit

Shared toolkit for Agent eXperience Interface (AXI) command-line tools: a strict TOON
encoder shipped with the specification's own conformance fixtures, errors that carry
recovery as **data**, a redaction boundary, and environment-only credentials.

Nothing here imports an HTTP or WebSocket client, and the distribution declares no
runtime dependency. That is checked, not claimed.

## Why it exists

Two AXI CLIs — one for Home Assistant, one for Plex — measured **1 378 identical lines**
of toolkit between them. The duplication had already cost: a TOON specification
violation was fixed in one copy of `toon.py` and not in the other, both suites stayed
green because each judged its own copy, and the divergence only surfaced when somebody
ran both encoders against one set of files. **179/179 against 177/179.**

One copy of the encoder fixes that class of failure permanently — but only if there is
also one copy of the thing that judges it. So the fixtures live *inside the package*,
beside the encoder, and `axi_toolkit.toon_spec.run(encode)` takes the encoder as an
argument. A tool that installs this package asserts its own score against the same
files instead of re-vendoring 179 cases and hoping they stayed in step.

## What is in it

| Module | What it is |
| --- | --- |
| `axi_toolkit.toon` | A strict TOON encoder (spec v4.1). Encoding happens at the output boundary only. |
| `axi_toolkit.toon_spec` | The specification's own encode fixtures, vendored and checksummed, plus the rig that runs them against *any* encoder. |
| `axi_toolkit.errors` | `AxiError`, a code, the fault classes, and the closed recovery vocabulary. |
| `axi_toolkit.render.cli` | Recovery intent → the line a shell user reads. Also `parse`, its inverse. |
| `axi_toolkit.render.prose` | The same intent → a sentence naming the caller's own tool. |
| `axi_toolkit.redact` | `register_secret`, `register_pattern`, and one filter with a documented ordering. |
| `axi_toolkit.envconfig` | Environment-only credentials, control-character rejection, userinfo splitting. |
| `axi_toolkit.ha.services` | Home Assistant's published service model, read: fields and their selectors, the response mode, the capability a target must have. |
| `axi_toolkit.plex.ids` | The six `plex://` forms in circulation, and which one is safe to hand a media player. Two of the others break a consumer and one raises inside it. |
| `axi_toolkit.plex.filters` | The music filter language: stars, field scoping, the one inequality real Plex offers for an integer, relative dates and sort directions. |

What deliberately does **not** exist: an `agent/` package, framework adapters, an MCP
server, a dual sync/async API, and any client class wrapping an HTTP library. The agent
surface of a pure function is its own signature — every framework derives a JSON Schema
from annotations — so there is no adapter worth writing.

## Recovery is data, never a rendered line

This is the first part of the extraction that was not mechanical, and it is the reason a
single module can serve a CLI and a caller that will never run one.

Today a tool raises `help_lines=["Run \`ha-axi area list\` to see the areas that exist"]`.
The tool's own name is baked in at the point the error is raised, so the sentence belongs
to that tool forever. Here the same fact is structured intent, and the name arrives when
somebody renders it:

```python
from axi_toolkit.errors import NotFound, run
from axi_toolkit.render import cli, prose

error = NotFound(
    "no area named 'nowhere'",
    code="NO_SUCH_AREA",
    recovery=[run(("area", "list"), purpose="to see the areas that exist")],
)

cli.lines(error.recovery, "ha-axi")
# ['Run `ha-axi area list` to see the areas that exist']

prose.sentences(error.recovery, "some-other-tool")
# ["To see the areas that exist, use some-other-tool's `area list` command."]

error.as_dict()
# {'message': "no area named 'nowhere'", 'code': 'NO_SUCH_AREA',
#  'recovery': [{'kind': 'run', 'args': ['area', 'list'], 'lead': 'Run',
#                'purpose': 'to see the areas that exist'}]}
```

The vocabulary is closed — `run`, `retry`, `set_env`, `choose`, `note` — and `note` is
the one kind that may name a tool at all, as the placeholder `{tool}` and never as the
name. Every literal recovery line both source tools emit today (222 of them) round-trips
through `parse` and `line` **byte for byte**; that is a generated check, not a claim.

`axi_toolkit.plex` is where that stopped being a round trip and became a rewrite. Its
two modules came out of a tool whose refusals named it — ``Run `plex-axi search --track
'<title>'` to get this server's rating key`` — and every one of them is now intent. So a
digest could not gate the move: the source text was *meant* to change. What was gated
instead was the behaviour — ninety-one scenarios run against the tool's own copy and
against this one, the refusals compared as the lines they render for `plex-axi`, then
rendered a second time under another name, because a line that reproduces the tool's
bytes by *storing* its name has been copied rather than extracted and the rendered
output alone cannot tell those two apart.

**That gate is retired, along with the three others this repository ever raised.** A
cross-repository gate is a substitute for having one copy of a module; both tools have
now deleted their copies and import this package, so the substitute has nothing left to
compare and is deleted rather than left to describe files that are gone. The behaviour
is stated by `tests/test_plex_ids.py`, `tests/test_plex_filters.py` and
`tests/test_ha_services.py` — and, past them, by each tool's own suite, which now runs
against this code. `AGENTS.md`, "Retired gates", is the record.

## The requirements layer

This repository declares what it claims, in MetaObjects, and generates its conformance
checks from that declaration. `metaobjects/meta.axi-toolkit.yaml` is the source of truth.

The shape is: four `object.value` nodes name the four projection kinds
(**capability**, **population**, **wire**, **differential**); each field on one of them
is a **fact**; and a requirement tags the facts that witness it with `@implementedBy`,
which the metamodel permits at L4 (an object) and L5 (a member) only. The relation a
check uses is decided by *which projection object the fact lives on* — there is no
attribute for it, and no attribute anywhere for an expected value. The registry is
sealed, so inventing one is a load error rather than a code-review question.

Every expected value lives in `tests/conformance/capture.json`, machine-written from two
authorities that need no credentials: the vendored specification fixtures, and the two
source CLIs read from a local checkout at capture time. All four projection kinds
therefore run offline, in ordinary CI, with no secrets.

```sh
scripts/dev-setup.sh --reqgen                 # .venv, with the 3.11 toolchain in it
.venv/bin/python scripts/reqgen.py list       # the declaration as a table
.venv/bin/python scripts/reqgen.py check      # fail if the generated checks are stale
AXI_TOOLKIT_SOURCE_HA=<checkout> AXI_TOOLKIT_SOURCE_PLEX=<checkout> \
  .venv/bin/python scripts/reqgen.py capture  # re-read the authorities
```

The generator is only worth its lines because of four things a hand-written suite does
not get, and if any of them is ever lost the right move is to delete it and write plain
pytest: **there is nowhere to type an expected value**; **a live requirement with no
check fails generation**; **the capture and the checks come from one declaration and so
cannot drift apart**; and **the vacuity self-test comes free**, because each relation
knows what breaking it looks like. That last one runs in the suite: every check is
broken in turn and required to fail.

`metaobjects` is a build-time extra (`.[reqgen]`), pure Python, and needs 3.11. The
checks it generates are committed and run under plain pytest on 3.9 upwards.

## Development

```sh
scripts/dev-setup.sh      # creates .venv and installs .[dev] into it
.venv/bin/pytest          # the whole suite; no credentials, no network
.venv/bin/ruff check . && .venv/bin/ruff format --check .
scripts/install-hooks.sh  # the pre-commit and commit-msg guards
scripts/leakcheck.py      # what those hooks run
```

**Install into `.venv`, never into the ambient interpreter.** The tools that consume this
package are normally installed as isolated user-level tools, and a bare editable install
outside a virtualenv overwrites the launcher for one of them with a copy bound to
whatever interpreter was ambient — so deleting the checkout later breaks a command the
reader depends on and never installed from here. `scripts/dev-setup.sh` is the whole
setup for that reason: it puts the same `.venv` in place that `.github/workflows/ci.yml`
builds, and nothing outside `.venv/` is touched.

This repository is public. `scripts/leakcheck.py` blocks installation-specific data —
addresses, credentials, home paths, hardware identifiers — from files, commit messages
**and pull request titles and bodies**, which is the surface no hook can reach and the
one a pipeline writes into after every other check has run. Its coverage is bounded: it
narrows how a leak can happen and misses generic public hostnames, secrets that are
neither JWT-shaped nor bearer-prefixed, and anything inside a binary.

## Licence

MIT. The vendored TOON fixtures are MIT from `toon-format/spec`; see
`src/axi_toolkit/toon_spec/PROVENANCE.md`.
