// What `npm pack` would ship, checked against what the package promises.
//
// `npm pack --dry-run --json` lists the tarball without writing it. The check requires
// the build to be present, every file an `exports` entry names to be in the tarball, the
// licence and README to travel with it, and nothing but built output and those files to
// leave the package: no source, tests, fixtures or lockfile.

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

const output = execFileSync("npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], {
  cwd: root,
  encoding: "utf8",
});
const shipped = JSON.parse(output)[0].files.map((file) => file.path).sort();

const ROOT_FILES = ["package.json", "README.md", "LICENSE"];
const problems = [];
const required = new Set(ROOT_FILES);

(function collect(value) {
  if (typeof value === "string") required.add(value.replace(/^\.\//, ""));
  else if (value && typeof value === "object") Object.values(value).forEach(collect);
})(manifest.exports);

for (const path of required) {
  if (!shipped.includes(path)) problems.push(`missing from the tarball: ${path}`);
}
for (const path of shipped) {
  if (!path.startsWith("dist/") && !ROOT_FILES.includes(path)) problems.push(`must not ship: ${path}`);
}

if (readFileSync(join(root, "LICENSE"), "utf8") !== readFileSync(join(root, "..", "LICENSE"), "utf8")) {
  problems.push("ts/LICENSE differs from the repository LICENSE");
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`pack: ${shipped.length} files, every exports target present, nothing extra`);
