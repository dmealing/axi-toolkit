import { describe, expect, it } from "vitest";
import {
  codePointLength,
  isBlank,
  PY_WS,
  pyRepr,
  pySplit,
  pyStrip,
  pyUrlsplit,
  pyUrlunsplit,
  rstripSlashes,
} from "../src/internal/pystr.js";

describe("pyStrip and the whitespace set", () => {
  it("strips Python's whitespace, including U+0085 and U+001C, but not U+FEFF", () => {
    expect(pyStrip("\u0085\u001c x 　")).toBe("x");
    expect(pyStrip("﻿x")).toBe("﻿x");
    expect(isBlank("\u0085  ")).toBe(true);
    expect(isBlank("﻿")).toBe(false);
    expect(pySplit(" a\u0085b  c ")).toEqual(["a", "b", "c"]);
  });

  it("agrees with str.isspace over the Basic Multilingual Plane", () => {
    // The characters Python's str.isspace() accepts below U+10000.
    const expected = new Set([
      0x09,
      0x0a,
      0x0b,
      0x0c,
      0x0d,
      0x1c,
      0x1d,
      0x1e,
      0x1f,
      0x20,
      0x85,
      0xa0,
      0x1680,
      0x2028,
      0x2029,
      0x202f,
      0x205f,
      0x3000,
      ...Array.from({ length: 11 }, (_, i) => 0x2000 + i),
    ]);
    const ws = new RegExp(`^[${PY_WS}]$`, "u");
    const got = new Set<number>();
    for (let code = 0; code < 0x10000; code += 1) {
      if (code >= 0xd800 && code <= 0xdfff) continue;
      if (ws.test(String.fromCharCode(code))) got.add(code);
    }
    expect([...got].sort((a, b) => a - b)).toEqual([...expected].sort((a, b) => a - b));
  });
});

describe("pyStrip on a pathological value", () => {
  it("is linear in a long interior whitespace run", () => {
    const text = `a${" ".repeat(200_000)}b`;
    const started = performance.now();
    expect(pyStrip(text)).toBe(text);
    expect(performance.now() - started).toBeLessThan(500);
  });
});

describe("small string helpers", () => {
  it("counts code points", () => {
    expect(codePointLength("ab\u{1F511}")).toBe(3);
    expect(codePointLength("")).toBe(0);
  });
  it("strips trailing slashes only", () => {
    expect(rstripSlashes("a//b///")).toBe("a//b");
    expect(rstripSlashes("///")).toBe("");
    expect(rstripSlashes("")).toBe("");
  });
});

describe("pyRepr", () => {
  const cases: [string, string][] = [
    ["plain", "'plain'"],
    ["", "''"],
    ["it's", `"it's"`],
    [`say "hi"`, `'say "hi"'`],
    [`it's "both"`, `'it\\'s "both"'`],
    ["a\\b", "'a\\\\b'"],
    ["a\nb\rc\td", "'a\\nb\\rc\\td'"],
    ["\u0000\u001f\u007f", "'\\x00\\x1f\\x7f'"],
    ["\u0085 ­", "'\\x85\\xa0\\xad'"],
    ["café ü", "'café ü'"],
    [" ​﻿", "'\\u2028\\u200b\\ufeff'"],
    ["\u{1F511}", "'\u{1F511}'"],
    ["\u{E0001}", "'\\U000e0001'"],
    ["\ud800", "'\\ud800'"],
    ["͸", "'\\u0378'"],
  ];
  for (const [input, expected] of cases) {
    it(JSON.stringify(input), () => expect(pyRepr(input)).toBe(expected));
  }
});

describe("pyUrlsplit", () => {
  it("splits scheme, netloc and path, lowercasing only the scheme", () => {
    expect(pyUrlsplit("HTTPS://User:pw@Host.Example.COM:443/api/?q=1#f")).toEqual({
      scheme: "https",
      netloc: "User:pw@Host.Example.COM:443",
      path: "/api/",
    });
  });

  it("ends the netloc at the first of / ? #", () => {
    expect(pyUrlsplit("http://h?x=/y").netloc).toBe("h");
    expect(pyUrlsplit("http://h#x/y").netloc).toBe("h");
    expect(pyUrlsplit("http://h?x").path).toBe("");
  });

  it("finds no scheme where Python finds none", () => {
    expect(pyUrlsplit("://nope")).toEqual({ scheme: "", netloc: "", path: "://nope" });
    expect(pyUrlsplit("1http://h").scheme).toBe("");
    expect(pyUrlsplit("ht tp://h").scheme).toBe("");
    expect(pyUrlsplit("/just/a/path")).toEqual({ scheme: "", netloc: "", path: "/just/a/path" });
  });

  it("removes tabs and newlines and leading control characters first", () => {
    expect(pyUrlsplit("\u0001 ht\ttp://ho\nst/p")).toEqual({
      scheme: "http",
      netloc: "host",
      path: "/p",
    });
  });

  it("keeps a bracketed host whole and refuses a lone bracket", () => {
    expect(pyUrlsplit("http://[2001:db8::1]:80/x").netloc).toBe("[2001:db8::1]:80");
    expect(() => pyUrlsplit("http://[2001:db8::1/x")).toThrow("Invalid IPv6 URL");
    expect(() => pyUrlsplit("http://2001:db8::1]/x")).toThrow("Invalid IPv6 URL");
  });
});

describe("pyUrlunsplit", () => {
  it("writes // for a netloc and roots a relative path", () => {
    expect(pyUrlunsplit("http", "h:1", "")).toBe("http://h:1");
    expect(pyUrlunsplit("http", "h", "p/q")).toBe("http://h/p/q");
    expect(pyUrlunsplit("https", "h", "/p")).toBe("https://h/p");
  });
  it("writes // for an empty netloc unless the path already opens with it", () => {
    expect(pyUrlunsplit("http", "", "")).toBe("http://");
    expect(pyUrlunsplit("http", "", "/x")).toBe("http:///x");
    expect(pyUrlunsplit("http", "", "//x")).toBe("http://x");
  });
});
