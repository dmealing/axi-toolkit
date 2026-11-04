import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CONFORMANCE_ROOT } from "../src/toon-spec/index.js";

/** A conformance pack file, read in place from the repository root. */
export function pack<T>(name: string): T {
  return JSON.parse(readFileSync(join(CONFORMANCE_ROOT, name), "utf8")) as T;
}
