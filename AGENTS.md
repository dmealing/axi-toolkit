# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build,
test, release, architecture, and sharp-edge notes that should travel with the code.

## The hard constraint: this repository is public and must stay generic

`axi-toolkit` is built by reading two AXI command-line tools and the installations they
were developed against. The failure that matters is not a bug — it is a commit that
describes, or grants access to, somebody's home automation instance, media server or
workstation. Before writing **anything** into this repo, including tests, fixtures,
docs, examples and commit messages:

- **No host addresses.** No RFC1918 addresses, no install-specific hostnames or ports.
- **No credentials.** Build credential shapes at run time; never write an `eyJ...`
  literal, a bearer value or a token into a file. `tests/test_redact.py` shows the
  pattern (`synthetic_jwt()`, values assembled from pieces), and it is the pattern
  because the condensed scan joins the whole file before re-scanning.
- **No real data.** Invent obviously-synthetic names: `light.example_lamp`,
  `host.example.com`, area `Example Room`.
- **No local paths or personal identifiers.** The two source checkouts are named by
  `AXI_TOOLKIT_SOURCE_HA` / `AXI_TOOLKIT_SOURCE_PLEX` at capture time and must never
  reach a committed file or a pull request body.

`scripts/leakcheck.py` enforces this — do not rely on remembering it:

```sh
scripts/leakcheck.py                     # every tracked file
scripts/leakcheck.py --staged            # what a commit would record (pre-commit hook)
scripts/leakcheck.py --commit-msg PATH   # the message itself (commit-msg hook)
scripts/leakcheck.py --pull-request N    # a pull request's title and body (hygiene.yml)
scripts/leakcheck.py --rules             # the live rule list and the path allowances
scripts/leakcheck.py --demo              # self-test: proves every rule still fires
scripts/install-hooks.sh                 # sets core.hooksPath to .githooks
```

Its rule set is the **union** of both source tools' scanners, not a subset: a shared
repository sees fixtures from both domains, and a scanner that catches more in a public
repository is strictly better than one tuned to today's contents. CI runs `--demo`
before the real scan, so a scanner that stopped detecting anything fails the build
rather than passing silently. If it flags a line that legitimately needs the shape, add
`leakcheck: allow=<rule>` on that line — scoped to that one rule, never blanket. Do not
weaken a rule to make a commit pass, and do not bypass the hooks.

**There are three surfaces and the third is not a file.** A pull request title and body
are published the moment they are written, are in no checkout, pass under no hook, and
can be edited after every other check has run. The pipeline's own document step writes
into the body, pasting captured pytest output that carries absolute paths on two lines:
the header's `rootdir:` line, and the warnings summary, which prints the site-packages
path of the interpreter that raised the warning — a path no choice of capture directory
moves, so running an evidence capture from a scratch directory neutralises the first
line and leaves the second fully intact. The first line published a home directory
three times across two sibling repositories with every check green each time; the
second did it in this repository's own body, and the guard caught it. `edited` in
`hygiene.yml`'s trigger list is the whole mechanism — without it the check scans the
empty original body and passes. If the guard fires on a pull request body, **edit the
body**; never weaken the guard.

**A file that cannot carry a marker** — JSON has no comment syntax, and vendored
third-party data must stay byte-for-byte — is exempted in `PATH_ALLOWANCES`, per path
*and* per rule. There is one entry: the vendored TOON fixture whose backslash-escaping
case is a synthetic Windows drive path.

## Architecture

- **`toon.py` + `toon_spec/`** — a strict TOON encoder (spec v4.1) and the
  specification's own encode fixtures, vendored **inside the package** rather than under
  `tests/`. That placement is load-bearing, not tidiness: one copy of the encoder only
  ends the divergence if there is one copy of the rig that judges it, so
  `toon_spec.run(encode)` takes the encoder as an argument and a downstream tool asserts
  its own score without re-vendoring. `PROVENANCE.md` carries the commit, the licence,
  the refresh recipe and what is deliberately not vendored.
- **`errors.py`** — the closed recovery vocabulary. **Recovery is data; the tool's name
  is supplied at render time and never stored.** `note` is the only kind that may name a
  tool, as `{tool}`. There is deliberately no `help_lines` attribute: a slot left there
  for convenience would be taken, and the first caller to take it bakes a name back in.
- **`render/cli.py`** has `parse` as well as `line`. It is the migration aid for the two
  CLIs *and* the thing that lets the byte-for-byte claim cover the whole corpus rather
  than a chosen sample. A line it cannot express structurally becomes a note — which is
  a reported gap, not a silent skip.
- **`redact.py`** — order is literals → bearer → registered shapes → JWT. For the five
  shapes the two tools carry the order is **not** observable (each rule leaves a
  placeholder the next cannot match), which is why neither tool wrote it down. It is
  written down and pinned here so the first shape where it matters is not the thing that
  discovers it.
- **`envconfig.py`** — every per-tool difference (variable names, scheme default, port
  default, path-suffix stripping) is on a `CredentialSpec` the tool declares. None of
  them can be decided here; they are properties of the system behind the tool.
- **`ha/services.py`** — the first module of the domain tier, and the first that is a
  *move* rather than a reconciliation of two copies: it reads the service model an
  installation publishes at `GET /api/services`, and it arrived from one tool with one
  edit, its docstring's citation of a file that would dangle here. Everything below that
  docstring is byte-for-byte the code the tool still runs, and the drift gate below
  proves it rather than asserting it. Pure and stdlib-only (`difflib`): the caller
  fetches the model and decides whether the read is worth paying for, which is why the
  `ha` extra is still empty and the distribution still declares no runtime dependency.

## The requirements layer

`metaobjects/meta.axi-toolkit.yaml` is the source of truth. `scripts/reqgen.py` is the
only thing that *generates* from it, and `.metaobjects/config.json` is what lets a second
reader find it without being told where it is.

**`.metaobjects/config.json` is what makes this directory a project.** It is the only
marker the `meta` CLI recognises: without it the toolchain falls back to a bare
`metaobjects/` guess and the project root is wherever the walk-up happens to stop. It
declares the metadata **directory**, not the one file in it, because `reqgen` loads the
directory — naming the file would let a second declaration land beside it and be read by
one of the two readers only, which is the drift class this whole layer exists to remove.

**The positional argument is the PROJECT ROOT, not the metadata directory** — the
opposite of the Python and C# ports' `docs` positionals, and filed upstream as
metaobjects issue #344. `meta docs metaobjects` fails; run it bare from the root:

```sh
meta docs --out <dir>       # requirements.md and requirements.toon come out with it
```

The `meta` CLI is the Node package and is a separate install from the Python
`metaobjects` loader `reqgen` imports, whose floor is 3.11 — so `python3 -m metaobjects`
against a 3.10 system interpreter reports "no module named" while the CLI works fine.
That is two toolchains, not a broken one; never reconcile them with
`pip install --break-system-packages`.

**The modelling rule, because it was got wrong before.** `@implementedBy` is legal at
**L4 (an object) and L5 (a member) only**, and it resolves to nodes in the model. So a
fact about a live system is modelled *as a member* — a field on an `object.value` — and
the requirement **tags the member**. There is no "oracle" attribute and no need for one;
an earlier attempt invented one, got `ERR_UNKNOWN_ATTR`, and concluded the model could
not express requirements. The refusal was right and the modelling was wrong.

Consequences worth keeping straight:

- **The projection object decides the relation.** `CapabilityFacts` → equality,
  `PopulationFacts` → coverage, `WireFacts` → byte equality per case,
  `DifferentialFacts` → the two sources agree and this package matches. There is no
  attribute spelling it, and adding one would be an `ERR_UNKNOWN_ATTR`.
- **A fact's name is the whole reference.** `haRecoveryLines` resolves to
  `capture_ha_recovery_lines` and `subject_ha_recovery_lines` in
  `tests/conformance/projections.py`. A fact with only one half fails generation.
- **The Python loader does not check the binding rules.** It validates the vocabulary
  and stops. The L4/L5 floor, nesting that never returns to a level already used,
  references that resolve, a live leaf that names no fact, and a fact no requirement
  claims are all enforced in `reqgen.bind` and tested in `tests/test_reqgen.py`.
- **`tests/conformance/capture.json` is machine-written and never hand-edited.** It
  holds every expected value in the repository. Re-read it with `reqgen capture`, which
  needs both source checkouts; nothing else does.
- **A module extracted but not yet adopted is gated against its origin.** While
  `ha/services.py` also exists in the tool it came from, `haServiceModelDefinitions`
  compares the two: one row per top-level definition, plus a `<module>` row hashing the
  whole file with its docstring elided — that elision being the one edit the move was
  allowed. It is a `CapabilityFacts` member, so the relation is equality and it reads
  both ways: a definition here the tool does not have is an invention, one the tool has
  and this does not is a gap. Its reach is the reach every capture-backed check has and
  no more: drift introduced **here** goes red on the next `pytest`, drift introduced
  **there** goes red at the next `reqgen capture`. It is meant to be deleted when the
  tool imports this module instead of carrying its own copy.
- **Do not model the TOON encoder's row shapes.** A prior measurement put that at 155
  lines of metadata replacing 50 lines of Python plus a build step and a large
  dependency, for no drift the checksummed fixtures do not already catch.

Regenerate and gate:

```sh
python3.11 scripts/reqgen.py list | check | generate
AXI_TOOLKIT_SOURCE_HA=<checkout> AXI_TOOLKIT_SOURCE_PLEX=<checkout> python3.11 scripts/reqgen.py capture
```

The `requirements` CI job runs `list` and `check`. It is separate from `test` because
the metadata toolchain needs Python 3.11 while the test matrix goes down to 3.9 — the
generator needs it, the generated checks never do, and that split is what keeps the
package's own floor at 3.9.

## Testing

`pytest` runs the whole suite with **no credentials, no source checkouts and no
network**. That property is the design, not a convenience: the conformance layer reads
the committed capture.

- `tests/conformance/test_requirements_generated.py` is generated. **Do not edit it** —
  change the declaration and regenerate; CI fails on a stale copy.
- Its last test breaks every check in turn and requires each to fail. A check that has
  never failed is not yet a check.
- `tests/test_toon_conformance.py` holds `CASE_COUNT`, the one deliberate literal in the
  repository. It is a ratchet on a fixture refresh, not an expectation — every value a
  check compares against comes from the capture.
- Both TOON suites are kept and are not interchangeable: one states the encoder's
  behaviour in this project's words, the other runs the specification's opinion.
- `tests/test_ha_services.py` is mostly **new**, and the reason is worth knowing before
  the next module moves: the tool's own file for this module is 648 lines of which
  forty-five address the module. The rest drive its commands end to end against a REST
  double and cannot follow the module out, because what they test is the command path.
  Four cases came across unchanged; the other eleven functions arrived uncovered and are
  stated directly here. Expect that ratio again on the Plex half.

## Release

release-please on `main`, same shape as the sibling projects. The PyPI publish job is
written and gated behind `release_created`, and it has now fired: **`axi-toolkit` 0.2.0
is on PyPI**, wheel and sdist with attestations, and the trusted publisher and the `pypi`
environment are configured. The one-time account actions are done; a release cut from
`main` publishes without further setup.

### Why `bump-minor-pre-major` is on

`release-please-config.json` sets `"bump-minor-pre-major": true`. That is deliberate, not
an oversight to be tidied away. This package is pre-1.0 **on purpose**: the extraction is
not finished. Step 2's first half has landed — `servicemodel.py` is here as
`axi_toolkit.ha.services` — but the tool has not yet adopted it, and step 3's Plex
id/filter language has not moved at all. Both remaining halves change the public surface
substantially. It stays in 0.x until they have landed.

Without the flag, release-please applies strict semver, and the rename commit's `feat!:`
marker alone would have made the very first artifact ever to appear on PyPI a 1.0.0 — a
public statement that the API is stable, published as a side effect of a commit prefix
rather than as a decision. With it on, a breaking change bumps the **minor** while the
version is below 1.0.0, so `feat!:` gives 0.2.0.

`bump-patch-for-minor-pre-major` is left unset (it defaults to false) so an ordinary
`feat:` bumps the minor too, which is the conventional 0.x behaviour.

1.0.0 is reached by **removing** this flag once the extraction has landed and the surface
is one somebody is willing to keep — a deliberate act, which is the whole point.

### Why the distribution is called `axi-toolkit`

It was `axi-core` first, and PyPI **rejected** that name. `axl-core` -- with an L -- is
already registered there at 0.7.0, and PyPI does not compare the name you submit against
the names that exist. It compares *normalised* forms, and its confusability check folds
`i`, `l` and `1` together, folds `o` and `0` together, and strips the separators `-`,
`_` and `.` entirely. `axi-core` and `axl-core` normalise to the same string, so the
upload was refused after the name looked free in every way anyone had thought to check.

An exact-name lookup does not answer the question. Before proposing any distribution
name for this project or a sibling, expand it over the whole confusable class and check
every member: substitute each `i`/`l`/`1` for the others, each `o`/`0` for the other, and
test the separator-stripped spelling as well. `axi-toolkit` was cleared that way -- all
216 variants of it were free -- and that is the only reason to believe it will upload.

Two consequences worth keeping straight:

- **The distribution name and the repository name are independent.** They happen to
  agree today, but a trusted publisher is configured per repository and per project, and
  it is content with a distribution whose name differs from the repository's. A future
  rename of one does not compel the other.
- **The import package follows the distribution, with no alias left behind.** There is
  no `axi_core` shim: a compatibility alias would let a downstream consumer keep the old
  spelling, and the old spelling is the one PyPI will not accept.
