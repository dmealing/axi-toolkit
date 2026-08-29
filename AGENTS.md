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

## The development environment: `.venv`, always

**`scripts/dev-setup.sh` is the only setup command. Never run `pip install` — editable
or otherwise — outside `.venv`, and never document one.** The script creates `.venv` at
the repository root and installs `.[dev]` into it (`--reqgen` for `.[dev,reqgen]`, which
raises the interpreter floor to 3.11); everything afterwards is called by path out of
it — `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/python scripts/reqgen.py`.

**The reason is damage outside the checkout, and it is not hypothetical.** The tools this
package serves are normally installed as isolated user-level tools: one environment per
tool, with a launcher on `PATH` pointing into it. An editable install into whatever
interpreter is ambient overwrites that launcher with one bound to the ambient
interpreter and leaves an editable pointer at the checkout — a `.pth` and a `.dist-info`
whose `direct_url.json` records the path. Nothing reports this. When the checkout goes,
which is the normal end of a throwaway clone, the reader's own command dies with
`ModuleNotFoundError`, and a sibling tool can be left silently pinned to a version
several releases behind its published one. A contributor's clone must not be able to
break the installation of the tool they are contributing to.

**This is one pattern, not two.** `.github/workflows/ci.yml` already builds `.venv` and
calls the tools by path out of it — its own comment says why: on a self-hosted runner
`~/.local/bin` is ahead on `PATH` and the user site is on the interpreter's path, so a
bare `pytest` or `ruff` is whatever the machine happens to have. The script exists so
the documented path is the path CI proves, and so that a reader who does not know any of
the above still ends up isolated. The floor split the script encodes — 3.9 for the
package, 3.11 for the requirements toolchain — is the same one that keeps `test` and
`requirements` separate jobs.

A future reader will be tempted to "simplify" this back to a single bare editable-install
line. That is the defect, not the simplification.

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

  **`plex-axi` has adopted both modules** (its PR #20): `ids.py` is deleted there and
  `music.py` keeps only the half that needs a live section. The three drift gates that
  watched the window are retired — see **Retired gates** below, and do not re-add them.

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
  needs both source checkouts; nothing else does. **Retiring the drift gates did not
  change that**, and it is worth saying because it looks as though it should have: with
  both tools now importing this package, the obvious guess is that the capture has
  nothing left to read out of a checkout. Measured rather than guessed — **18 of the 24
  capture halves still refuse to run without one**, because the toolkit-tier facts
  (`errorExitCodes`, `haRecoveryLines`, `plexNormalizedUrls`, every `DifferentialFacts`
  row, …) read the tools' *own* modules, which they still have. Only the six TOON facts
  read the vendored fixtures instead. Both variables stay required.
- **A module extracted but not yet adopted is gated against its origin, and the gate is
  deleted the day it is adopted.** Both halves of that rule are load-bearing and both
  have now been exercised to the end: **four gates were raised and all four are
  retired**, and none is left standing. **Retired gates** below is the whole record —
  why each existed, why each went, and the two techniques worth reusing. A live gate's
  reach is the reach every capture-backed check has and no more: drift introduced
  **here** goes red on the next `pytest`, drift introduced **there** goes red at the
  next `reqgen capture`. **There are no live instances today**, which is why
  `anExtractedModuleIsGatedAgainstItsOriginUntilTheToolTakesIt` is the ledger's only
  `planned` entry and names no fact: no module lives in two places, so there is nothing
  to gate. The next extraction — the Plex probing layer — reopens the window and puts it
  back to `live` with its new gate named there.
- **A gate states what the move left invariant, and a rewrite leaves different things
  invariant than a copy does.** A digest of the source text works only for a module that
  moved verbatim; the Plex move deliberately rewrote every recovery line, so a digest
  would have failed by construction and weakening it to pass would have been worse than
  having no gate. What was invariant there was the **surface** and the **rendered
  behaviour**. Both shapes are written out under **Retired gates** with what each did
  and did not reach, because the next move has to choose between them before it can
  write anything, and choosing wrong is how a gate ends up reading as one without being
  one.
- **Do not model the TOON encoder's row shapes.** A prior measurement put that at 155
  lines of metadata replacing 50 lines of Python plus a build step and a large
  dependency, for no drift the checksummed fixtures do not already catch.

### Retired gates

**All four drift gates that ever stood here have been deleted. Do not re-add any of
them.** Their absence is a decision, not an oversight, and this is the record of it —
one completed pattern rather than four separate deletions, because the pattern is what
the next extraction needs and the individual gates are gone.

| gate | shape | judged | retired when |
| --- | --- | --- | --- |
| `haServiceModelDefinitions` | `CapabilityFacts`, equality | the source text of `servicemodel.py`, definition by definition | `dmealing/ha-axi` PR #24 |
| `plexDomainDefinitions` | `CapabilityFacts`, equality | the moved surface: `ids.<name>` and `filters.<name>` | `dmealing/plex-axi` PR #20 |
| `plexIdBehaviour` | `WireFacts`, byte equality per case | 31 scenarios against both copies of `ids.py` | `dmealing/plex-axi` PR #20 |
| `plexFilterBehaviour` | `WireFacts`, byte equality per case | 60 scenarios against both copies of the pure half of `music.py` | `dmealing/plex-axi` PR #20 |

**Why they existed.** Each module — `axi_toolkit.ha.services` first, then
`axi_toolkit.plex.ids` and `axi_toolkit.plex.filters` — arrived from a tool as a *move*,
and for a while each move produced **two copies of the same code in two repositories**,
which is the exact failure this package was built to end. So each window was gated
rather than trusted to a memo.

**Why the four are not one gate repeated.** A gate states what *its* move left
invariant, and the two moves left different things invariant. `servicemodel.py` moved
verbatim, so the strongest available claim was a digest: one row per top-level
definition plus a `<module>` row over the whole file with its docstring elided — that
elision being the one edit the move was allowed — so any other difference between the
two copies was drift and the row went red on it. The Plex move deliberately rewrote
every recovery line into intent, so a digest would have failed by construction; what
stayed invariant was the **surface** and the **rendered behaviour**, and it took two
kinds of fact to say so:

- `plexDomainDefinitions` was the surface. Equality over `ids.<name>` for every public
  top-level name in the tool's `ids.py`, which moved whole, and `filters.<name>` for
  every entry of a declared boundary map, which the capture refused to record a missing
  name from. Honest about its reach: it caught a moved definition renamed or dropped on
  either side, and it did **not** catch a new pure function appearing in the tool's
  `music.py`. Deciding that mechanically was tried and abandoned — every rule that
  admits `stars` also admits the row vocabulary, which must not move.
- `plexIdBehaviour` and `plexFilterBehaviour` were the rendered behaviour. 91 scenarios,
  each run against the tool's copy and against this one; a value compared as its value,
  a refusal as its type, code, message and the recovery **rendered for `plex-axi`**.
  That was the byte-for-byte claim, made over the templated lines the literal corpus in
  `plexRecoveryLines` cannot reach.

**Two techniques worth reusing, because the next gate will want them.** The first left
the tree with the gates and has to come back from `git log`; the second survives, in the
two dedicated Plex suites:

- **Execute the tool's module without importing it.** `music.py` imports the tool's
  transport and, through it, `plexapi`; a capture that needed a client library installed
  would be a capture nobody could reproduce. `_source_filters()` filtered that module's
  own syntax tree down to its standard-library imports and the boundary's definitions
  and `exec`'d that subset against the tool's own error types — so what was measured was
  the tool's code rather than a paraphrase of it.
- **Render the recovery a second time under another tool name.** A recovery that
  reproduces the tool's bytes because it *stores* the tool's name has been copied rather
  than extracted, and the rendered line alone cannot tell the two apart. The subject half
  rendered every intent for `other-tool` and reported any that still said `plex-axi`,
  and the word doing the work is **unconditionally**: gating it on `mentions_tool` is
  exactly the hole a mutation found in `_plex_subject_recovery`, and the note under
  **Architecture** says why that gate is sound for a parsed intent and wrong for a
  hand-authored one. `tests/test_plex_ids.py` and `tests/test_plex_filters.py` carry the
  assertion now, over every refusal each module raises.

**Why they went.** Each tool deleted its copy and now imports this package: `ha-axi` in
its PR #24, `plex-axi` in its PR #20, which removed `ids.py` outright and reduced
`music.py` to the half that needs a live section. There is one copy of each module and
it lives here, so each gate had nothing left to compare against. A cross-repository gate
is a **substitute for having one copy**; once you have one copy, the substitute is not
merely unnecessary, it is actively wrong, because it keeps passing offline against a
committed capture while describing a file that no longer exists.

**Why removal rather than repointing.** The obvious alternative — repoint each fact at
"the tool no longer carries a copy" — was considered and rejected, once per tool and on
the same grounds. That is a new and much weaker claim wearing the old one's name: it
would go green on a tool that had deleted the file *and* broken its import, and it would
read in `reqgen list` exactly as the strong claim did. So would any subject-only
projection over this package's own source: with the authority gone, the "capture" would
be a snapshot of self, which is a change-detector and not a check. That argument does
not soften for a `WireFacts` gate just because 91 recorded scenarios look valuable on
their own — a golden file of this package's own answers is precisely the change-detector
in question, and it would sit in the ledger under a name that says *differential*.
The requirements went with the facts, for the same reason and because the metamodel
rules on it directly — `requirement.status`'s own description says a requirement is
*prescriptive* and never a journal of what happened, so a capability that no longer
applies is **deleted**, not annotated as retired, and the record of it belongs to
version control and to notes like this one. There is no `retired` or `superseded` status
to reach for; the enum is `planned` / `live` / `partial` and nothing else.
(`reqgen.DANGLING_OK` still names `abandoned` and `superseded`. Those are stale against
metaobjects 0.24.0's vocabulary and unreachable: writing either gets `ERR_BAD_ATTR_VALUE`
out of the loader, before `bind` ever sees it. Verified, not assumed.)

**Three requirements went; one stayed, at `planned`.** `theHomeAssistantServiceModelIsHere`
and `thePlexIdAndFilterLanguageFollows` each claimed a module was here as its tool had
it, which is a claim only that tool's copy could judge — deleted with their facts.
`theDomainTierFollows` held those two leaves and went with them: both halves it named
have moved and been adopted, and the sequencing it prescribed — a domain half never
overtaking the toolkit it depends on — can no longer be violated, because the toolkit is
here and both tools already run on it. What stayed is
`anExtractedModuleIsGatedAgainstItsOriginUntilTheToolTakesIt`, moved from `live` to
`planned` with its `implementedBy` removed. That is the one prescription of the four
that is **not discharged**: it is a conditional whose antecedent is currently false, and
it becomes true again the day the Plex probing layer moves. `planned` is the honest slot
for it — `reqgen.bind` refuses a `live` leaf that names no fact, and it is right to,
because such a requirement reads as coverage that does not exist. It generates no check,
so it cannot go falsely green.

**What states those modules' behaviour now.** `tests/test_ha_services.py`,
`tests/test_plex_ids.py` and `tests/test_plex_filters.py` — ordinary suites, which are
the right instrument once there is one copy. Measured before the gates came out: those
two Plex files alone reach **100% statement and branch coverage of `axi_toolkit.plex`**,
and they already carry, over every refusal each module raises, the "no recovery stores a
tool name" assertion the gates' subject halves made. Past them is the stronger
instrument the gates were only ever standing in for: **each tool's own suite now runs
against this code**, so a behaviour change here fails there, on the tool's next CI run
rather than at somebody's next hand-diff of two checkouts.

**What the failure actually looked like, all four times.** Not a red test. `pytest`
stayed green throughout — it reads the committed capture and never touches a source
checkout, which is the whole point of the design — so for a while the suite was
describing files that were gone. What broke was `reqgen capture`, and it broke *badly*,
because `do_capture` builds every fact before it writes anything and one exception
aborts the lot:

- `haServiceModelDefinitions` and `plexDomainDefinitions` — a bare `FileNotFoundError`
  traceback out of `pathlib`, **printing an absolute local path**, which is the one
  thing that must never reach a commit message or a pull request body on a public
  repository.
- `plexIdBehaviour` — `ModuleNotFoundError: No module named 'plex_axi.ids'`.
- `plexFilterBehaviour` — the only one that failed legibly, because its boundary map
  guards itself: `RuntimeError: the boundary names [...], which the tool's music.py no
  longer defines`. Worth noticing and worth not over-reading — a diagnostic at capture
  time is still not a check, and it fired in the same place as the other three, which is
  where nobody was looking.

Recognise any of those: they mean a gate has outlived its window, and the fix is to
retire it, not to repoint it.

Regenerate and gate:

```sh
scripts/dev-setup.sh --reqgen   # a .venv on 3.11+, with the toolchain in it
.venv/bin/python scripts/reqgen.py list | check | generate
AXI_TOOLKIT_SOURCE_HA=<checkout> AXI_TOOLKIT_SOURCE_PLEX=<checkout> .venv/bin/python scripts/reqgen.py capture
```

The `requirements` CI job runs `list` and `check`. It is separate from `test` because
the metadata toolchain needs Python 3.11 while the test matrix goes down to 3.9 — the
generator needs it, the generated checks never do, and that split is what keeps the
package's own floor at 3.9.

## Testing

`.venv/bin/pytest` runs the whole suite with **no credentials, no source checkouts and
no network**. That property is the design, not a convenience: the conformance layer
reads the committed capture. (By path, out of the virtualenv `scripts/dev-setup.sh`
built — see **The development environment** above; a bare `pytest` is whatever the
machine happens to have, run against whatever interpreter it was installed for.)

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
- **Those two files are now the whole of what this repository says about
  `axi_toolkit.plex`**, because the three drift gates that also exercised it are retired.
  That was measured before they came out rather than hoped for: the two files alone reach
  **100% statement and branch coverage** of the package, and they already carry, over
  every refusal each module raises, the "no recovery stores a tool name" assertion the
  gates' subject halves made. `tests/test_ha_services.py` is the same instrument for the
  Home Assistant half. Past both is `plex-axi`'s and `ha-axi`'s own suites, which now run
  against this code rather than beside it.

## Release

release-please on `main`, same shape as the sibling projects. The PyPI publish job is
written and gated behind `release_created`, and it has now fired: **`axi-toolkit` 0.2.0
is on PyPI**, wheel and sdist with attestations, and the trusted publisher and the `pypi`
environment are configured. The one-time account actions are done; a release cut from
`main` publishes without further setup.

### Forcing a release when every landed commit is hidden

`main` can sit ahead of the published package with every check green, and it did: 0.4.0
was tagged, three commits landed after it -- two `refactor(conformance):` and one
`build:` -- and no release followed. That is not a fault. All three types are hidden in
the changelog table, so release-please renders a section that is a header line and
nothing else, `changelogEmpty` in `strategies/base.js` (`entry.split('\n').length <= 1`)
is true, `buildReleasePullRequest` returns `undefined`, and the run exits 0 having
decided correctly that nothing user-facing landed. Nothing reports the drift; it is
visible only by comparing the tag against `main`.

Bringing the two back into line is **one commit whose last footer is
`Release-As: <version>`**. Three things about it are easy to get wrong, and two of them
were got wrong before this note existed.

- **Touch no version string and no changelog.** `pyproject.toml`,
  `src/axi_toolkit/__init__.py` (it is in `extra-files`) and
  `.release-please-manifest.json` are release-please's to write, in its own release PR,
  and the `CHANGELOG.md` section is generated from the commits. A hand-bump does not seed
  that PR, it collides with it. The forcing commit carries prose and the footer, nothing
  else.
- **The section table this repository uses is not the one the preset documents.**
  `"release-type": "python"` selects `strategies/python.js`, which injects its own
  `CHANGELOG_SECTIONS` before `DefaultChangelogNotes` is reached, and that table differs
  from `conventional-changelog-conventionalcommits`' default on exactly one row: `docs`
  is **visible** here and hidden there. `refactor`, `build`, `chore`, `test`, `ci` and
  `style` are hidden in both. So "does a `docs:` commit produce an entry" is a question
  whose answer depends on the release type, and reading it off the preset gives the
  wrong one.
- **A commit carrying `Release-As:` is exempt from `hidden` anyway.** The preset's own
  `transform` sets `discard = false` when the footer or the body matches its
  `release-as:` pattern, before it consults the type at all. Measured across the
  plausible types, with the footer and without:

  | type | in the table | with the footer | without it |
  | --- | --- | --- | --- |
  | `docs` | visible | `### Documentation` | `### Documentation` |
  | `feat` | visible | `### Features` | `### Features` |
  | `build` | hidden | `### Build System` | nothing; no release PR |
  | `refactor` | hidden | `### Code Refactoring` | nothing; no release PR |
  | `chore` | hidden | `### Miscellaneous Chores` | nothing; no release PR |

  **The type does not decide whether the release happens. It decides the heading the one
  entry lands under.** So choose it to describe the commit -- `docs:` for a prose change
  -- rather than to escape a flag it does not have to escape. `docs:` has the smaller
  blast radius as well: it is the only honest choice here that renders on its own account
  rather than on the exemption, so it still works if that exemption ever goes.

**The version is a judgement about the commits being released, not about the forcing
one.** Read the landed commits: if nothing a consumer imports behaves differently, it is
a patch, whatever `bump-minor-pre-major` would have done with the types involved.
`Release-As:` overrides the computed bump entirely -- `buildNewVersion` takes the note's
text ahead of the versioning strategy -- so the number is asserted and has to be argued
for in the commit message.

**The footer has to be the last thing in the message that reaches `main`, and a squash
can move it.** release-please finds it in the parsed syntax tree: a `<footer>` whose token
is `release-as` becomes a note titled `RELEASE AS`, and `buildNewVersion` takes it. What
loses the version is that footer ceasing to be a `<footer>` -- reflowed into the tail of
the preceding paragraph, or dropped, it is body text, the tree has no footer node at all,
and release-please computes a bump instead of taking the number. Insisting it be *last*
is what makes that visible: a message ending in anything else has had something done to
it. None of it is caught by `scripts/commitcheck.py`, which exits 0 on the dropped
message, on the reflowed one and on a message with a trailer appended after the footer,
all three measured -- it answers "would release-please read this commit at all", which is
a different question and not this one. Verify the footer itself by driving
`vendor/conventional-commits-parser/` over the message and counting `footer` nodes:
exactly one, its token `release-as`, and it the last. Put the footer last in the pull
request body too. The squash message is drawn from the commit message or from the body
depending on a repository setting nobody checks at merge time, and a footer in both is in
whichever one is used.

### Why `bump-minor-pre-major` is on

`release-please-config.json` sets `"bump-minor-pre-major": true`. That is deliberate, not
an oversight to be tidied away. This package is pre-1.0 **on purpose**: the extraction is
not finished. Step 2 has landed — `servicemodel.py` is here as `axi_toolkit.ha.services`
— and so has step 3's first half, the Plex id and filter language as `axi_toolkit.plex`.
**Both tools have now adopted and deleted their copies**, so the two-adopter data point
the surface was waiting for exists and every drift gate is retired. What has *not*
happened is step 3's second half: the probing layer that reads a section's advertised
fields, plus the `plexapi` exception classification. That remainder changes the public
surface substantially, so the flag stays on and the version stays in 0.x until it has
landed and been adopted in its turn.

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
