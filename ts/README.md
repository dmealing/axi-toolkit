# axi-toolkit (TypeScript)

Shared toolkit for Agent eXperience Interface (AXI) command-line tools: errors that carry
recovery as **data**, the renderers that turn that data into a shell line or a sentence,
TOON output, a redaction boundary, and environment-only credentials.

This is the TypeScript counterpart of the Python package of the same name in the same
repository. The two are versioned independently and judged by the same shared fixtures.
Version `0.1.0` has not been published to npm.

## Install

```sh
npm install axi-toolkit
```

Requires Node 20.19 or later. The package is ESM-only; a CommonJS consumer on Node 20.19+
or 22.12+ can still `require()` it. Its single runtime dependency is
[`@toon-format/toon`](https://www.npmjs.com/package/@toon-format/toon) (`~4.4.0`), used
only behind `encode` and never re-exported.

From a checkout of the repository:

```sh
npm --prefix ts ci
npm --prefix ts run build
```

## Public surface

Everything except `toon-spec` is importable from the package root; each module is also its own subpath.

| Import | What it gives you |
| --- | --- |
| `axi-toolkit/errors` | The recovery vocabulary (`run`, `retry`, `setEnv`, `choose`, `note`), `recoveryToJSON` / `recoveryFromJSON`, `AxiError` and its subclasses (`UsageError`, `ConfigError`, `ConnectionFailed`, `AuthFailed`, `Forbidden`, `NotFound`, `ApiError`), `faultClass`, the exit codes. |
| `axi-toolkit/render/cli` | `line` / `lines`: a recovery as the line a shell user reads, for a tool name supplied at render time. `parse` / `parseAll`: the inverse. |
| `axi-toolkit/render/prose` | `sentence` / `sentences`: the same recovery as a sentence. |
| `axi-toolkit/toon` | `encode` and `encodeScalar`: TOON on stdout. |
| `axi-toolkit/toon-spec` | The specification's encode fixtures and a rig, `run(encode)`, that scores any encoder against them. Needs a checkout of the repository; see below. |
| `axi-toolkit/redact` | `Redactor`, a default instance behind `redact`, `registerSecret`, `registerPattern`; order is literals, bearer, registered shapes, JWT. |
| `axi-toolkit/envconfig` | `credentialSpec`, `loadCredentials`, `normalizeBaseUrl`, `describeEnvironment`, `missingVars`, `setupRecovery`: credentials come from the environment only. |

```ts
import { ConfigError, line, note, run } from "axi-toolkit";

const recovery = [run(["doctor"], { purpose: "to check the setup" }), note("see {tool} --help")];
const failure = new ConfigError("not configured", { code: "NOT_CONFIGURED", recovery });
for (const item of failure.recovery) console.error(line(item, "example-axi"));
```

The tool's name is never stored in a recovery; it is passed to `line` and `sentence`.
Wire strings are identical to the Python package's (`set_env`, a note's `text`), while the
API is camelCase.

## Relation to the Python package and the `conformance/` pack

The Python package in `src/` is the reference. It writes `conformance/` at the repository
root: language-neutral JSON (recovery lines with their parsed and prose forms, rendering
rules, error classification, credential scenarios, redaction cases) with a `checksums.txt`
over it. This package's tests read those files, and the TOON encode fixtures, **in place**.
There is no vendored copy and nothing to sync. A test (`test/drift.test.ts`) fails when the
bytes on disk stop matching the recorded checksums, and `scripts/ci-local.sh --only tsdrift`
runs it. Because the pack is read where it lives, a separate network drift check against
another repository would compare a file with itself, so there is none.

`axi-toolkit/toon-spec` locates the fixtures relative to the repository, so it works from a
checkout and not from the installed tarball.

## Checks

```sh
scripts/ci-local.sh --only tslint --only tstest   # biome, tsc, vitest, build
scripts/ci-local.sh --only tsdrift                # conformance pack and TOON fixture checksums
scripts/ci-local.sh --only tspack                 # build, npm pack --dry-run contents, publint, attw
```

## Licence

MIT.
