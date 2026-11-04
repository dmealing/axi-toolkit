import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
  name: string;
  dependencies: Record<string, string>;
  exports: Record<string, unknown>;
};

const NETWORK = new Set(["http", "https", "http2", "net", "tls", "dgram", "dns", "dns/promises"]);

interface Resolution {
  specifier: string;
  parent: string | null;
  url: string;
}

const PROBE = `
import { registerHooks } from "node:module";
const seen = [];
registerHooks({
  resolve(specifier, context, next) {
    const result = next(specifier, context);
    seen.push({ specifier, parent: context.parentURL ?? null, url: result.url });
    return result;
  },
});
for (const entry of JSON.parse(process.argv[1])) await import(entry);
process.stdout.write(JSON.stringify(seen));
`;

/** Every module resolution Node performs while importing `entries` in a fresh process. */
function loadedGraph(entries: string[]): Resolution[] {
  const output = execFileSync(
    process.execPath,
    ["--input-type=module", "--eval", PROBE, JSON.stringify(entries)],
    { cwd: root, encoding: "utf8" },
  );
  return JSON.parse(output) as Resolution[];
}

function networkBuiltins(graph: Resolution[]): string[] {
  return graph
    .filter((r) => r.url.startsWith("node:") && NETWORK.has(r.url.slice("node:".length)))
    .map((r) => r.url);
}

describe("the package's dependency contract", () => {
  it("declares exactly one runtime dependency, on the TOON encoder", () => {
    expect(Object.keys(manifest.dependencies)).toEqual(["@toon-format/toon"]);
    expect(manifest.dependencies["@toon-format/toon"]).toMatch(/^~4\.4\./);
  });

  describe("as Node loads every export of the built package", () => {
    let graph: Resolution[];
    const dist = pathToFileURL(join(root, "dist")).href;

    beforeAll(() => {
      execFileSync(join(root, "node_modules", ".bin", "tsc"), ["-p", "tsconfig.build.json"], {
        cwd: root,
      });
      const entries = Object.keys(manifest.exports).map((subpath) =>
        subpath === "." ? manifest.name : `${manifest.name}${subpath.slice(1)}`,
      );
      graph = loadedGraph(entries);
    });

    it("loads every export from dist", () => {
      const loaded = new Set(graph.map((r) => r.url));
      for (const subpath of Object.keys(manifest.exports)) {
        const target = (manifest.exports[subpath] as { default: string }).default;
        expect(loaded, subpath).toContain(pathToFileURL(join(root, target)).href);
      }
    });

    it("loads nothing that reaches the network", () => {
      expect(networkBuiltins(graph)).toEqual([]);
    });

    it("resolves the encoder from one module only", () => {
      const importers = graph
        .filter((r) => r.specifier === "@toon-format/toon" && r.parent?.startsWith(dist))
        .map((r) => (r.parent as string).slice(dist.length + 1));
      expect([...new Set(importers)]).toEqual(["toon.js"]);
    });

    it("would see a network module reached by a computed dynamic import", () => {
      const control = `data:text/javascript,await import("node:" + "ht" + "tp")`;
      expect(networkBuiltins(loadedGraph([control]))).toEqual(["node:http"]);
    });
  });
});
