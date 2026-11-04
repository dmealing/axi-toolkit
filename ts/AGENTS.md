# The TypeScript package (`ts/`)

`axi-toolkit` on npm: the TypeScript counterpart of the Python package in `src/`, in the
same repository and versioned on its own. It is not a release-please package yet: the root
package's `exclude-paths: ["ts"]` keeps commits here from bumping the Python version, and
how `ts` is released is still to be decided. The root `AGENTS.md` still governs everything here,
above all the **public-repository constraint**: no host addresses, credentials, real
data, local paths or personal identifiers in any file, fixture, test or commit message.
`scripts/leakcheck.py` and `scripts/commitcheck.py` at the repository root already scan
`ts/` and every commit; there is no copy of either in this directory.

## Layout

- `src/errors.ts` — the recovery vocabulary (readonly discriminated union), factories,
  `recoveryToJSON` / `recoveryFromJSON`, `AxiError` and its subclasses, `faultClass`.
  Recovery is data; the tool's name is supplied at render time and never stored.
- `src/render/cli.ts`, `src/render/prose.ts` — `line` / `parse` and `sentence`.
- `src/toon.ts` — a thin wrapper over `@toon-format/toon` (`~4.4.0`, the **only** runtime
  dependency). Nothing from that library is re-exported, and this is the only file that
  imports it (`test/purity.test.ts` holds both).
- `src/toon-spec/` — the fixture rig. It reads `../conformance/toon-spec.json` and the
  fixtures it points at **in place**; there is no vendored copy. It therefore needs a
  checkout of the repository, and is not yet in the npm tarball.
- `src/redact.ts`, `src/envconfig.ts` — the redaction boundary (literals, bearer, registered
  shapes, JWT, in that order) and environment-only credentials. `test/redact.test.ts` and
  `test/envconfig.test.ts` judge them against `conformance/redaction.json` and
  `credentials.json`, read in place.
- `src/internal/pystr.ts` — where a JS string built-in differs from the Python one the
  contract was written against (whitespace set, strip, `repr`, `urlsplit`, code-point length
  and capitalisation). Not exported.
- `test/` — vitest. `render.test.ts` and `errors.test.ts` judge the implementation against
  `conformance/recovery.json`, `render-rules.json` and `errors.json`, read in place.

## Cross-port rules that are easy to get wrong

- Wire strings stay identical to Python's (`set_env`, a note's `text`), the API is camelCase.
- `Recovery` kinds own their fields: `recoveryFromJSON` refuses a field another kind owns.
  An absent `lead` on a `run` or `retry` takes the kind's default, never `""`.
- `parse` uses Python's whitespace set, not JS `\s`, and `[^\n]` where Python's `.` stops
  only at `\n`. Never add the `m` flag to an anchored pattern.
- Look a fault code up with `Object.hasOwn`, never by plain indexing.
- Every conformance expectation comes from the pack. The deliberate literals are ratchets
  on a pack or fixture refresh, not expectations: `CASE_COUNT` and `FIXTURE_FILE_COUNT` in
  `test/toon.test.ts`, and the corpus population `307` in `test/render.test.ts`.

## Commands

Install from the lockfile into `ts/node_modules` only (`npm ci`), then:

```sh
scripts/ci-local.sh --only tslint --only tstest   # what the gate runs: biome, tsc, vitest, build
npm --prefix ts run test                          # just vitest
```

Out of scope until later phases: the drift checks against the
Python `main`, `publint` / `attw` / `npm pack`, and any `npm publish`.
