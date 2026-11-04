import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  actualDigests,
  CONFORMANCE_ROOT,
  digestMismatches,
  recordedDigests,
} from "../src/toon-spec/index.js";
import { pack } from "./pack.js";

// The TypeScript package reads `conformance/` and the TOON fixtures in place, so there is no
// copy to go stale and no second repository to fetch. What can drift is the committed
// checksum record against the bytes on disk: a pack file edited by hand, or regenerated
// without its checksums. This is the local drift check; it needs no network.

type Digests = Record<string, string>;

/** `sha256sum` lines → `{ name: digest }`. */
function parseChecksums(text: string): Digests {
  const recorded: Digests = {};
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    const [digest, ...name] = line.trim().split(/\s+/);
    recorded[name.join(" ")] = digest as string;
  }
  return recorded;
}

function packDigests(): { recorded: Digests; actual: Digests } {
  const recorded = parseChecksums(readFileSync(join(CONFORMANCE_ROOT, "checksums.txt"), "utf8"));
  const actual: Digests = {};
  for (const name of readdirSync(CONFORMANCE_ROOT).filter((n) => n.endsWith(".json"))) {
    actual[name] = createHash("sha256")
      .update(readFileSync(join(CONFORMANCE_ROOT, name)))
      .digest("hex");
  }
  return { recorded, actual };
}

describe("conformance pack drift", () => {
  it("matches conformance/checksums.txt, file for file", () => {
    const { recorded, actual } = packDigests();
    expect(digestMismatches(recorded, actual)).toEqual([]);
    expect(Object.keys(recorded).length).toBeGreaterThan(0);
  });

  it("notices an edit, a deletion and an addition", () => {
    const { recorded, actual } = packDigests();
    const first = Object.keys(actual)[0] as string;
    expect(digestMismatches(recorded, { ...actual, [first]: "0".repeat(64) })).toEqual([first]);
    const { [first]: _dropped, ...without } = actual;
    expect(digestMismatches(recorded, without)).toEqual([first]);
    expect(digestMismatches(recorded, { ...actual, "new.json": "0".repeat(64) })).toEqual([
      "new.json",
    ]);
  });

  it("is the pack version and name every file declares", () => {
    for (const name of Object.keys(packDigests().recorded)) {
      const file = pack<{ pack: string; version: number; topic: string }>(name);
      expect(file.pack).toBe("axi-toolkit-conformance");
      expect(file.version).toBe(1);
      expect(`${file.topic}.json`).toBe(name);
    }
  });
});

describe("TOON fixture drift", () => {
  it("matches the fixtures' own checksums as the package reads them", () => {
    expect(digestMismatches(recordedDigests(), actualDigests())).toEqual([]);
  });
});
