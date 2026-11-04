/**
 * The TOON conformance fixtures, read in place from the repository's conformance pack.
 *
 * `conformance/toon-spec.json` says where the fixtures are; this module follows that
 * pointer and keeps no copy, so there is one source of truth for the bytes. The rig takes
 * the encoder as an argument (`run(encode)`) so it can judge any implementation, and the
 * offline check (`digestMismatches`) catches a fixture edited to suit an encoder.
 *
 * Reading needs a checkout of the repository: the fixtures are not in the npm tarball yet.
 */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Delimiter, EncodeOptions } from "../toon.js";

/** The repository root, three levels above `ts/src/toon-spec` (and `ts/dist/toon-spec`). */
export const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
export const CONFORMANCE_ROOT = join(REPOSITORY_ROOT, "conformance");

interface Pointer {
  fixtures: string;
  checksums: string;
  license: string;
  provenance: string;
}

function readPointer(): Pointer {
  let text: string;
  try {
    text = readFileSync(join(CONFORMANCE_ROOT, "toon-spec.json"), "utf8");
  } catch {
    throw new Error(
      "axi-toolkit/toon-spec reads the conformance pack in place and needs a checkout of the repository",
    );
  }
  const pointer = JSON.parse(text) as Partial<Pointer>;
  for (const key of ["fixtures", "checksums", "license", "provenance"] as const) {
    if (typeof pointer[key] !== "string") {
      throw new Error(`conformance/toon-spec.json carries no ${JSON.stringify(key)}`);
    }
  }
  return pointer as Pointer;
}

// Read lazily: importing this module outside a checkout must not throw.
let pointer: Pointer | undefined;
function resolved(): Pointer {
  pointer ??= readPointer();
  return pointer;
}
export function encodeRoot(): string {
  return resolve(CONFORMANCE_ROOT, resolved().fixtures);
}
function checksumsPath(): string {
  return resolve(CONFORMANCE_ROOT, resolved().checksums);
}

/** Fixture categories this rig runs. A decode fixture arriving in `encode/` must fail. */
export const RUNNABLE_CATEGORIES: ReadonlySet<string> = new Set(["encode"]);
/** The only options the rig applies. Any other option is an error, never skipped. */
export const KNOWN_OPTIONS: ReadonlySet<string> = new Set(["delimiter", "indentSize"]);

export interface Case {
  readonly file: string;
  readonly index: number;
  readonly name: string;
  readonly specSection: string;
  readonly input: unknown;
  readonly expected: string;
  readonly options: Readonly<Record<string, unknown>>;
}

export interface Failure {
  readonly case: Case;
  readonly got: string;
}

export interface Report {
  readonly passed: number;
  readonly total: number;
  readonly failures: readonly Failure[];
  /** `"N/N"`, passed over total. */
  readonly score: string;
}

/** The toolkit's `encode`, or any encoder taking options spelled the toolkit's way. */
export type Encoder = (value: unknown, options?: EncodeOptions) => string;

interface Fixture {
  category?: unknown;
  tests: Record<string, unknown>[];
}

/** Every vendored fixture file name, in a stable order. */
export function fixtureFiles(): string[] {
  return listJson(encodeRoot());
}

function listJson(directory: string): string[] {
  return readdirSync(directory)
    .filter((name) => name.endsWith(".json"))
    .sort();
}

// Each fixture is parsed once; the listing helpers all come through here.
const loaded = new Map<string, Fixture>();

function load(file: string): Fixture {
  let fixture = loaded.get(file);
  if (fixture === undefined) {
    fixture = JSON.parse(readFileSync(join(encodeRoot(), file), "utf8")) as Fixture;
    loaded.set(file, fixture);
  }
  return fixture;
}

/** The `category` each fixture file declares. */
export function categories(): string[] {
  return fixtureFiles().map((file) => String(load(file).category ?? ""));
}

/** Every published encode case, in file-then-index order. Refuses a fixture this rig does not run. */
export function cases(): Case[] {
  return fixtureFiles().flatMap((file) => {
    const fixture = load(file);
    if (!RUNNABLE_CATEGORIES.has(String(fixture.category))) {
      throw new Error(
        `${file} declares category ${JSON.stringify(fixture.category)}, which this rig does not run`,
      );
    }
    return fixture.tests.map((test, index) => ({
      file,
      index,
      name: String(test.name ?? ""),
      specSection: String(test.specSection ?? ""),
      input: test.input,
      expected: test.expected as string,
      options: { ...((test.options as Record<string, unknown> | undefined) ?? {}) },
    }));
  });
}

/** `"primitives-34"`: what a failing case is called in a report. Never the prose name. */
export function caseId(testCase: Case): string {
  return `${testCase.file.replace(/\.json$/, "")}-${testCase.index}`;
}

/** Every option name any published case uses, deduplicated and sorted. */
export function optionNames(): string[] {
  return [...new Set(cases().flatMap((testCase) => Object.keys(testCase.options)))].sort();
}

/** Every delimiter the published cases ask for, including the implied default. */
export function exercisedDelimiters(): string[] {
  const seen = new Set([","]);
  for (const testCase of cases()) {
    if ("delimiter" in testCase.options) seen.add(String(testCase.options.delimiter));
  }
  return [...seen].sort();
}

/**
 * Map a case's options onto the toolkit's encoder options. The specification spells the
 * indentation option `indentSize` and the toolkit's is `indent`; the mapping lives here.
 * Throws on an option this rig does not apply.
 */
export function encoderOptions(testCase: Case): EncodeOptions {
  const unknown = Object.keys(testCase.options)
    .filter((name) => !KNOWN_OPTIONS.has(name))
    .sort();
  if (unknown.length > 0) {
    throw new Error(
      `${caseId(testCase)} uses fixture options this rig does not apply: ${JSON.stringify(unknown)}`,
    );
  }
  const options: EncodeOptions = {};
  if ("delimiter" in testCase.options) {
    options.delimiter = testCase.options.delimiter as Delimiter;
  }
  if ("indentSize" in testCase.options) options.indent = testCase.options.indentSize as number;
  return options;
}

/** The SHA-256 of each file as recorded when the fixtures were vendored. */
export function recordedDigests(): Record<string, string> {
  return parseChecksums(readFileSync(checksumsPath(), "utf8"));
}

/** `sha256sum` lines to `{ name: digest }`. */
function parseChecksums(text: string): Record<string, string> {
  const recorded: Record<string, string> = {};
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    const [digest, ...rest] = line.trim().split(/\s+/);
    recorded[rest.join(" ")] = digest as string;
  }
  return recorded;
}

/** The SHA-256 of each file as it stands on disk now. */
export function actualDigests(): Record<string, string> {
  const actual: Record<string, string> = {};
  for (const file of fixtureFiles()) {
    actual[file] = createHash("sha256")
      .update(readFileSync(join(encodeRoot(), file)))
      .digest("hex");
  }
  return actual;
}

/**
 * File names whose content no longer matches the recorded checksums, including a file
 * present in one view and not the other.
 */
export function digestMismatches(
  recorded: Record<string, string> = recordedDigests(),
  actual: Record<string, string> = actualDigests(),
): string[] {
  return [...new Set([...Object.keys(recorded), ...Object.keys(actual)])]
    .filter((name) => recorded[name] !== actual[name])
    .sort();
}

/**
 * Encode every published case with `encode` and report the score. `encode` is a
 * parameter so the rig can judge a different implementation.
 */
export function run(encode: Encoder, only?: Iterable<Case>): Report {
  const selected = only === undefined ? cases() : [...only];
  const failures: Failure[] = [];
  for (const testCase of selected) {
    const got = encode(testCase.input, encoderOptions(testCase));
    if (got !== testCase.expected) failures.push({ case: testCase, got });
  }
  const passed = selected.length - failures.length;
  return { passed, total: selected.length, failures, score: `${passed}/${selected.length}` };
}
