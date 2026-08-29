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

  **Its output is to be read, not pasted.** `parse` matches the first backticked span,
  so a line that merely *cites* something in backticks parses as a `retry` whose
  `purpose` is the rest of the sentence — ``Pass the number after the last slash, which
  is what `rating_key:` reports`` becomes "retry with `rating_key:`". That renders back
  through `cli.line` byte for byte, which is why it passes, and `render/prose.py` then
  writes "…, then run it again with plex-axi." Those lines are authored as notes. The
  rule: a backticked span that is a citation rather than a thing to type is prose.

  **`mentions_tool` is the wrong gate on a hand-authored intent.** It answers "will
  rendering this name a tool", and for an intent `parse` produced that is sound — `parse`
  has already put any tool name into `{tool}`. For an intent somebody wrote, a note
  holding the literal string `plex-axi` returns false and sails through. The check that
  matters is unconditional: render for *another* tool name and require that the first
  tool's name is absent. That hole was live in `_plex_subject_recovery` until a mutation
  found it.
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
  docstring was byte-for-byte the code the tool ran, and a drift gate proved that rather
  than asserting it until the tool deleted its copy and imported this module instead —
  see **Retired gates** below, and do not re-add that gate. Pure and stdlib-only
  (`difflib`): the caller fetches the model and decides whether the read is worth paying
  for, which is why the `ha` extra is still empty and the distribution still declares no
  runtime dependency.
- **`plex/ids.py` + `plex/filters.py`** — the second domain module and the first move
  that was *not* verbatim. `ids.py` came whole; `filters.py` is the pure half of the
  tool's `music.py`, and the half is the judgement: anything taking a `server`, a
  `section` or a page of `items` stayed, the `plexapi` exception classification stayed,
  and **the `--fields` row vocabulary stayed** — `ROW_FIELDS`, the three row builders,
  `rows_for`, `with_track_artist`, `tag_titles`, `number`, `date_only`, `_seconds`. A
  two-arm adjudication put those on the surface-specific side, and whether to move them
  anyway is a question held for the maintainer. Do not move them and do not re-propose
  it. `SEARCH_METHODS` and `GROUP_BY_TITLE` stayed too, and they are the ones that will
  look like an oversight: both are plain literals with no import behind them, so "pure"
  in the mechanical sense. They name `MusicSection` methods and a parameter only the
  probing layer sends, and they have exactly one caller each, which stayed. They travel
  with `section.py`. The one rename: `_assert_server_side` is `assert_server_side`, because its caller
  is now a module that stayed behind and a leading underscore on a name another module
  must import says the opposite of what it means.

  **Every recovery line in both modules became intent**, which is what makes this move
  non-mechanical. `validate_rating_key` used to take `invocation="plex-axi track"` and
  now takes `command=("track",)` — the words *after* the name. It refuses a bare string
  outright, and that refusal is load-bearing: `run()` calls `tuple()` on its argument, so
  a string would become one argument per character and render as a line that reads
  plausibly and is wrong.

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
- **A module extracted but not yet adopted is gated against its origin, and the gate is
  deleted the day it is adopted.** Both halves of that rule are load-bearing and the
  second one has now been exercised once; **Retired gates** below is the worked example.
  A live gate's reach is the reach every capture-backed check has and no more: drift
  introduced **here** goes red on the next `pytest`, drift introduced **there** goes red
  at the next `reqgen capture`. The three live instances are the Plex ones, because
  `plex-axi` still carries its own copies.
- **A gate states what the move left invariant, and a rewrite leaves different things
  invariant than a copy does.** A digest of the source text works only for a module that
  moved verbatim; the Plex move deliberately rewrote every recovery line, so a digest
  would have failed by construction and weakening it to pass would have been worse than
  having no gate. What is invariant there is the **surface** and the **rendered
  behaviour**, and those are the two facts:
  - `plexDomainDefinitions` (`CapabilityFacts`, equality) — `ids.<name>` for every public
    top-level name in the tool's `ids.py`, which moved whole, and `filters.<name>` for
    every entry of `_PLEX_FILTER_BOUNDARY` in `projections.py`, which is the declared
    move list and which the capture refuses to record a missing name from. Honest about
    its reach: it catches a moved definition renamed or dropped on either side, and it
    does **not** catch a new pure function appearing in the tool's `music.py`. Deciding
    that mechanically was tried and abandoned — every rule that admits `stars` also
    admits the row vocabulary, which must not move.
  - `plexIdBehaviour` and `plexFilterBehaviour` (`WireFacts`, byte equality per case) —
    91 scenarios, each run against the tool's copy and against this one. A value is
    compared as its value; a refusal as its type, code, message and the recovery
    **rendered for `plex-axi`**. That comparison is the byte-for-byte claim, made over
    the templated lines the literal corpus in `plexRecoveryLines` cannot reach.
- **The capture executes the tool's `music.py` without importing it.** That module
  imports the tool's transport and, through it, `plexapi` — which the capture
  interpreter does not have and must not need. `_source_filters()` filters the module's
  own syntax tree down to its stdlib imports and the boundary's definitions and executes
  that subset against the tool's own error types, so what is measured is the tool's code
  rather than a paraphrase of it.
- **Do not model the TOON encoder's row shapes.** A prior measurement put that at 155
  lines of metadata replacing 50 lines of Python plus a build step and a large
  dependency, for no drift the checksummed fixtures do not already catch.

### Retired gates

**`haServiceModelDefinitions` was here and was deleted. Do not re-add it.** Its absence
is a decision, not an oversight, and this is the record of why — both halves, because
the reasoning generalises to the three Plex gates, which will reach the same day.

**Why it existed.** `axi_toolkit.ha.services` arrived from `ha-axi`'s `servicemodel.py`
as a *move*, and for a while the move produced **two copies of the same code in two
repositories** — which is the exact failure this package was built to end. So the window
was gated rather than trusted to a memo: the fact hashed one row per top-level
definition plus a `<module>` row over the whole file with its docstring elided (that
elision being the one edit the move was allowed), on a `CapabilityFacts` member, so the
relation was equality and it read both ways — a definition here the tool lacked was an
invention, one the tool had and this lacked was a gap.

**Why it went.** `ha-axi` deleted its copy and now imports `axi_toolkit.ha.services`
(`dmealing/ha-axi` PR #24). There is one copy of that code and it lives here, so the
gate had nothing left to compare against. A cross-repo gate is a **substitute for having
one copy**; once you have one copy, the substitute is not merely unnecessary, it is
actively wrong, because it keeps passing offline against a committed capture while
describing a file that no longer exists. `tests/test_ha_services.py` is the instrument
that states that module's behaviour now, and an ordinary test suite is the right one.

**Why removal rather than repointing.** The obvious alternative — repoint the fact at
"the tool no longer carries a copy" — was considered and rejected. That is a new and
much weaker claim wearing the old one's name: it would go green on a tool that had
deleted the file *and* broken its import, and it would read in `reqgen list` exactly as
the strong claim did. So would any subject-only projection over this package's own
source: with the authority gone, the "capture" would be a snapshot of self, which is a
change-detector and not a check. The requirement `theHomeAssistantServiceModelIsHere`
went with the fact for the same reason, and because the metamodel rules on it directly —
`requirement.status`'s own description says a requirement is *prescriptive* and never a
journal of what happened, so a capability that no longer applies is **deleted**, not
annotated as retired, and the record of it belongs to version control and to notes like
this one. There is no `retired` or `superseded` status to reach for; the enum is
`planned` / `live` / `partial` and nothing else. (`reqgen.DANGLING_OK` still names
`abandoned` and `superseded`. Those are stale against metaobjects 0.24.0's vocabulary
and unreachable: writing either gets `ERR_BAD_ATTR_VALUE` out of the loader, before
`bind` ever sees it. Verified, not assumed.)

**What the failure actually looked like, because the Plex gates will hit it.** Not a red
test. `pytest` stayed green — it reads the committed capture and never touches a source
checkout, which is the whole point of the design. What broke was `reqgen capture`, and
it broke *badly*: a bare `FileNotFoundError` traceback out of `pathlib`, aborting the
**entire** capture (`do_capture` builds every fact before it writes, so nothing at all
is recorded) and printing an absolute local path — the one thing that must never reach a
commit message or a pull request body on a public repository. Whoever runs `reqgen
capture` next after `plex-axi` adopts will get that, most likely while debugging
something unrelated. Recognise it: it means a gate outlived its window, and the fix is
to retire the gate, not to repoint it.

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
  stated directly here.
- **The Plex half predicted that ratio and came in under it.** `tests/test_plex_ids.py`
  ported six of the ten test functions in the tool's 149-line `test_ids.py`; the other
  four drive `search`, `track`, `rate` and `playlist` against a Plex double.
  `tests/test_plex_filters.py` ported **nothing**, because there was nothing to port:
  the tool has *no* direct test of any function in the pure half of `music.py`. Every
  one of them is reached only through a command. So a rating scale, an operator that
  had already been wrong once on every real server, and a date grammar all arrived with
  no direct coverage; both files above are what they have now. Assume the same for the
  probing layer when it moves, and budget for writing the suite rather than moving it.

## Release

release-please on `main`, same shape as the sibling projects. The PyPI publish job is
written and gated behind `release_created`, and it has now fired: **`axi-toolkit` 0.2.0
is on PyPI**, wheel and sdist with attestations, and the trusted publisher and the `pypi`
environment are configured. The one-time account actions are done; a release cut from
`main` publishes without further setup.

### Why `bump-minor-pre-major` is on

`release-please-config.json` sets `"bump-minor-pre-major": true`. That is deliberate, not
an oversight to be tidied away. This package is pre-1.0 **on purpose**: the extraction is
not finished. Step 2 has landed — `servicemodel.py` is here as `axi_toolkit.ha.services`
— and so has step 3's first half, the Plex id and filter language as `axi_toolkit.plex`.
`ha-axi` has adopted its half and deleted its copy; `plex-axi` has not adopted anything
yet, and step 3's second half, the probing layer that reads a section's advertised
fields plus the `plexapi` exception classification, has not moved. That remainder
changes the public surface substantially, and adoption is what will show whether the
surface here is the right one — one adopter is one data point, not a verdict. It stays
in 0.x until both have landed.

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
