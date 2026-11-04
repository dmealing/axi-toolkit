import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8")) as {
  dependencies: Record<string, string>;
};

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory()
      ? sources(join(directory, entry.name))
      : entry.name.endsWith(".ts")
        ? [join(directory, entry.name)]
        : [],
  );
}

describe("the package's dependency contract", () => {
  it("declares exactly one runtime dependency, on the TOON encoder", () => {
    expect(Object.keys(manifest.dependencies)).toEqual(["@toon-format/toon"]);
    expect(manifest.dependencies["@toon-format/toon"]).toMatch(/^~4\.4\./);
  });

  it("imports nothing that reaches the network, and imports the encoder in one place", () => {
    const forbidden =
      /from\s+["'](?:node:)?(?:http|https|http2|net|tls|dgram|undici)["']|\bfetch\s*\(/;
    const importsEncoder: string[] = [];
    for (const file of sources(join(root, "src"))) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(forbidden);
      if (text.includes("@toon-format/toon")) importsEncoder.push(file.slice(root.length + 1));
    }
    expect(importsEncoder).toEqual([join("src", "toon.ts")]);
  });
});
