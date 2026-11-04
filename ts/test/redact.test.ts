import { afterEach, describe, expect, it } from "vitest";
import {
  BEARER,
  JWT,
  MIN_SECRET_LENGTH,
  REDACTED,
  Redactor,
  redact,
  registeredPatterns,
  registerPattern,
  registerPatterns,
  registerSecret,
  reset,
  resetSecrets,
} from "../src/redact.js";
import { pack } from "./pack.js";

interface Rule {
  source: string;
  flags: string;
}
interface Fragment {
  join?: string[];
  header?: string;
  payload?: string;
  signature?: string;
}
interface RedactionPack {
  redacted: string;
  min_secret_length: number;
  order: string[];
  builtin: { bearer: Rule; token: Rule };
  fragments: Record<string, Fragment>;
  tools: Record<
    string,
    {
      patterns: Rule[];
      secrets: { value: string; min_length: number }[];
      cases: { name: string; input: (string | { ref: string })[]; expected: string }[];
    }
  >;
}

const data = pack<RedactionPack>("redaction.json");

function segment(text: string): string {
  return Buffer.from(text).toString("base64url");
}

/** A JWT-shaped value, built at run time and never written down. */
function syntheticJwt(): string {
  return [segment('{"alg": "HS256"}'), segment('{"sub": "synthetic"}'), "c2lnbmF0dXJl"].join(".");
}

function fragment(name: string): string {
  const recipe = data.fragments[name] as Fragment;
  if (recipe.join) return recipe.join.join("");
  return [
    segment(recipe.header as string),
    segment(recipe.payload as string),
    recipe.signature as string,
  ].join(".");
}

function assemble(input: (string | { ref: string })[]): string {
  return input.map((piece) => (typeof piece === "string" ? piece : fragment(piece.ref))).join("");
}

afterEach(() => reset());

describe("the redaction pack", () => {
  it("agrees on the constants and the order", () => {
    expect(REDACTED).toBe(data.redacted);
    expect(MIN_SECRET_LENGTH).toBe(data.min_secret_length);
    expect(data.order).toEqual(["literals", "bearer", "registered", "token"]);
  });

  it("agrees on the built-in shapes, up to the engine's whitespace", () => {
    // The pack writes `\s`; the port writes Python's whitespace set out, so U+FEFF is
    // not whitespace and U+0085 is. Everything else is the same source and flags.
    expect(JWT.source).toBe(data.builtin.token.source);
    expect(JWT.flags.replace("g", "")).toBe(data.builtin.token.flags);
    expect(BEARER.flags.replace("g", "")).toBe(data.builtin.bearer.flags);
    const [head, tail] = data.builtin.bearer.source.split("\\s+");
    expect(BEARER.source.startsWith(head as string)).toBe(true);
    expect(BEARER.source.endsWith(tail as string)).toBe(true);
  });

  for (const [tool, spec] of Object.entries(data.tools)) {
    describe(tool, () => {
      for (const kase of spec.cases) {
        it(kase.name, () => {
          const redactor = new Redactor();
          for (const rule of spec.patterns) {
            redactor.registerPattern(new RegExp(rule.source, rule.flags));
          }
          for (const secret of spec.secrets) {
            redactor.registerSecret(secret.value, { minLength: secret.min_length });
          }
          expect(redactor.redact(assemble(kase.input))).toBe(kase.expected);
        });
      }
    });
  }
});

describe("redact", () => {
  it("redacts a literal, longest first so an overlapping pair goes whole", () => {
    const redactor = new Redactor();
    redactor.registerSecret("example-secret", { minLength: 4 });
    redactor.registerSecret("someone:example-secret", { minLength: 4 });
    expect(redactor.redact("see someone:example-secret and example-secret")).toBe(
      `see ${REDACTED} and ${REDACTED}`,
    );
  });

  it("ignores a literal that is empty, absent or shorter than its minimum", () => {
    const redactor = new Redactor();
    redactor.registerSecret(null);
    redactor.registerSecret(undefined);
    redactor.registerSecret("");
    redactor.registerSecret("1234567");
    expect(redactor.redact("1234567 and more")).toBe("1234567 and more");
  });

  it("counts the minimum in code points, as Python does", () => {
    const redactor = new Redactor();
    const wide = "\u{1F511}".repeat(4); // 4 code points, 8 UTF-16 units
    redactor.registerSecret(wide, { minLength: 8 });
    expect(redactor.redact(`x${wide}x`)).toBe(`x${wide}x`);
    redactor.registerSecret(wide, { minLength: 4 });
    expect(redactor.redact(`x${wide}x`)).toBe(`x${REDACTED}x`);
  });

  it("treats a literal as text, never as a pattern or a replacement template", () => {
    const redactor = new Redactor();
    redactor.registerSecret("a.b*c$&(d)");
    expect(redactor.redact("a.b*c$&(d) and axbbbc$&(d)")).toBe(`${REDACTED} and axbbbc$&(d)`);
  });

  it("keeps group 1 of a grouped pattern and replaces an ungrouped one whole", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(key=)[a-z]{4,}/u);
    redactor.registerPattern("pw:[a-z]{4,}");
    expect(redactor.redact("key=abcd pw:efgh")).toBe(`key=${REDACTED} ${REDACTED}`);
  });

  it("counts a group that did not participate as empty rather than failing", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(a)?b+/u);
    expect(redactor.redact("bb")).toBe(REDACTED);
  });

  it("registers a source and flag set once, whatever form it arrives in", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(k=)\w+/u);
    redactor.registerPattern(/(k=)\w+/gu);
    redactor.registerPattern("(k=)\\w+");
    expect(redactor.registeredPatterns()).toEqual(["(k=)\\w+"]);
  });

  it("never keeps a sticky flag, which would match only at index 0", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(tok=)\w+/y);
    expect(redactor.redact("x tok=abc tok=def")).toBe(`x tok=${REDACTED} tok=${REDACTED}`);
  });

  it("keeps two registrations that differ only in flags", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(tok=)\w+/u);
    redactor.registerPattern(/(tok=)\w+/iu);
    expect(redactor.redact("TOK=abc")).toBe(`TOK=${REDACTED}`);
  });

  it("accepts a string shape with an identity escape that Python allows", () => {
    const redactor = new Redactor();
    redactor.registerPattern(String.raw`(key\=)[a-z]+`);
    expect(redactor.redact("key=abc")).toBe(`key=${REDACTED}`);
  });

  it("returns the compiled pattern, always global", () => {
    const redactor = new Redactor();
    expect(redactor.registerPattern(/x/u).flags).toContain("g");
    expect(redactor.registerPattern("y").flags).toContain("g");
  });

  it("does not let a registered pattern's flags leak between calls", () => {
    const redactor = new Redactor();
    redactor.registerPattern(/(t=)\d+/u);
    expect(redactor.redact("t=1 t=2")).toBe(`t=${REDACTED} t=${REDACTED}`);
    expect(redactor.redact("t=3")).toBe(`t=${REDACTED}`);
  });

  it("runs literals, then bearer, then registered shapes, then the token rule", () => {
    // A rule that keeps a prefix must see the text before the token rule replaces it whole.
    const redactor = new Redactor();
    redactor.registerPattern(/([?&]t=)[^&\s]+/u);
    const jwt = syntheticJwt();
    expect(redactor.redact(`?t=ab.${jwt}`)).toBe(`?t=${REDACTED}`);
    // The bearer rule runs first, then a pattern that reads the word `Bearer` as a value.
    expect(redactor.redact(`?t=Bearer abcdefgh12`)).toBe(`?t=${REDACTED} ${REDACTED}`);
  });

  it("reads the bearer scheme case-insensitively and keeps its prefix", () => {
    const redactor = new Redactor();
    expect(redactor.redact("Authorization: BeArEr  abcdefgh12345")).toBe(
      `Authorization: BeArEr  ${REDACTED}`,
    );
  });

  it("does not redact a bearer value shorter than eight characters", () => {
    expect(new Redactor().redact("bearer abcdefg")).toBe("bearer abcdefg");
  });

  it("redacts the whole of a token, wherever it sits", () => {
    expect(new Redactor().redact(`a ${syntheticJwt()} b ${syntheticJwt()}`)).toBe(
      `a ${REDACTED} b ${REDACTED}`,
    );
  });

  it("keeps two redactors apart", () => {
    const one = new Redactor();
    const two = new Redactor();
    one.registerSecret("only-in-one");
    expect(two.redact("only-in-one")).toBe("only-in-one");
  });

  it("resets literals and shapes separately and together", () => {
    const redactor = new Redactor();
    redactor.registerSecret("literal-value");
    redactor.registerPattern("shape");
    redactor.resetSecrets();
    expect(redactor.redact("literal-value shape")).toBe(`literal-value ${REDACTED}`);
    redactor.registerSecret("literal-value");
    redactor.reset();
    expect(redactor.redact("literal-value shape")).toBe("literal-value shape");
    expect(redactor.registeredPatterns()).toEqual([]);
  });
});

describe("the shared redactor", () => {
  it("is what the module functions operate on", () => {
    registerSecret("a-shared-literal");
    registerPatterns(["one", /(two=)\d+/u]);
    expect(registeredPatterns()).toEqual(["one", "(two=)\\d+"]);
    expect(registerPattern("one").source).toBe("one");
    expect(redact("a-shared-literal one two=5")).toBe(`${REDACTED} ${REDACTED} two=${REDACTED}`);
    resetSecrets();
    expect(redact("a-shared-literal")).toBe("a-shared-literal");
    reset();
    expect(registeredPatterns()).toEqual([]);
  });
});
