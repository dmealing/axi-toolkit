import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { encode, encodeScalar } from "../src/toon.js";
import {
  actualDigests,
  CONFORMANCE_ROOT,
  caseId,
  cases,
  categories,
  digestMismatches,
  encodeRoot,
  encoderOptions,
  exercisedDelimiters,
  fixtureFiles,
  optionNames,
  parseChecksums,
  recordedDigests,
  run,
} from "../src/toon-spec/index.js";
import { pack } from "./pack.js";

// Ratchets on a fixture refresh, not expectations: the two deliberate literals here.
const CASE_COUNT = 160;
const FIXTURE_FILE_COUNT = 9;

describe("the specification's encode fixtures, read in place", () => {
  it("are the number the ratchet expects", () => {
    expect(cases().length).toBe(CASE_COUNT);
    expect(fixtureFiles().length).toBe(FIXTURE_FILE_COUNT);
  });

  it("are all encode fixtures", () => {
    expect(new Set(categories())).toEqual(new Set(["encode"]));
  });

  it("match the recorded checksums", () => {
    expect(digestMismatches()).toEqual([]);
    expect(Object.keys(recordedDigests()).sort()).toEqual(fixtureFiles());
  });

  it("notice an edit, a deletion and an addition", () => {
    const real = actualDigests();
    expect(real[fixtureFiles()[0] as string]).toMatch(/^[0-9a-f]{64}$/);
    // The check compares two views; prove it reports each way they can differ.
    const recorded = recordedDigests();
    const edited = { ...real, "objects.json": "0".repeat(64) };
    const missing = Object.fromEntries(
      Object.entries(real).filter(([name]) => name !== "objects.json"),
    );
    const extra = { ...real, "new.json": "0".repeat(64) };
    expect(digestMismatches(recorded, edited)).toEqual(["objects.json"]);
    expect(digestMismatches(recorded, missing)).toEqual(["objects.json"]);
    expect(digestMismatches(recorded, extra)).toEqual(["new.json"]);
    expect(digestMismatches(missing, recorded)).toEqual(["objects.json"]);
  });

  it("use only options the rig applies, and name a case by file and index", () => {
    expect(optionNames()).toEqual(["delimiter", "indentSize"]);
    expect(exercisedDelimiters()).toEqual(["\t", ",", "|"].sort());
    const first = cases()[0];
    if (first === undefined) throw new Error("no cases");
    expect(caseId(first)).toBe(`${first.file.replace(".json", "")}-${first.index}`);
  });

  it("refuse an option the rig does not apply, instead of running with defaults", () => {
    const first = cases()[0];
    if (first === undefined) throw new Error("no cases");
    expect(() => encoderOptions({ ...first, options: { keyFolding: "safe" } })).toThrow(
      /keyFolding/,
    );
  });
});

describe("the toolkit's encoder, judged by the rig", () => {
  it("scores every published case", () => {
    const report = run(encode);
    expect(report.failures.map((f) => caseId(f.case))).toEqual([]);
    expect(report.score).toBe(`${CASE_COUNT}/${CASE_COUNT}`);
  });

  it("is failed by an encoder that is wrong, and the report names the case", () => {
    const report = run((value) => `${encode(value)}x`);
    expect(report.passed).toBe(0);
    expect(report.failures.length).toBe(CASE_COUNT);
  });

  it("can judge a subset", () => {
    expect(run(encode, cases().slice(0, 5)).total).toBe(5);
  });
});

describe("encode and encodeScalar", () => {
  it("honour the delimiter and the indentation", () => {
    expect(encode({ a: [1, 2] }, { delimiter: "|" })).toBe("a[2|]: 1|2");
    expect(encode({ a: { b: 1 } }, { indent: 4 })).toBe("a:\n    b: 1");
  });

  it("write a scalar the way it appears as a field value", () => {
    expect(encodeScalar("a,b")).toBe('"a,b"');
    expect(encodeScalar("a,b", { delimiter: "|" })).toBe("a,b");
    expect(encodeScalar(null)).toBe("null");
    expect(encodeScalar(true)).toBe("true");
    expect(encodeScalar(3)).toBe("3");
    // The root-only rule for a leading U+FEFF does not apply inside a document.
    expect(encodeScalar("\ufeffx")).toBe("\ufeffx");
  });

  it("refuses what is not a scalar", () => {
    expect(() => encodeScalar({})).toThrow(TypeError);
    expect(() => encodeScalar([1])).toThrow(TypeError);
  });
});

describe("the conformance pack's own checksums", () => {
  it("match the files they cover", () => {
    const recorded = parseChecksums(readFileSync(join(CONFORMANCE_ROOT, "checksums.txt"), "utf8"));
    expect(Object.keys(recorded).length).toBeGreaterThan(0);
    for (const [name, digest] of Object.entries(recorded)) {
      const actual = createHash("sha256")
        .update(readFileSync(join(CONFORMANCE_ROOT, name)))
        .digest("hex");
      expect(actual, name).toBe(digest);
    }
  });

  it("declare the pack name and version, and the topic their file name", () => {
    const recorded = parseChecksums(readFileSync(join(CONFORMANCE_ROOT, "checksums.txt"), "utf8"));
    for (const name of Object.keys(recorded)) {
      const file = pack<{ pack: string; version: number; topic: string }>(name);
      expect(file.pack).toBe("axi-toolkit-conformance");
      expect(file.version).toBe(1);
      expect(`${file.topic}.json`).toBe(name);
    }
  });

  it("point at fixtures that exist", () => {
    expect(encodeRoot().endsWith("encode")).toBe(true);
    expect(fixtureFiles().length).toBeGreaterThan(0);
  });
});
