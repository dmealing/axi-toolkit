import { describe, expect, it } from "vitest";
import { mentionsTool, type Recovery, recoveryFromJSON, recoveryToJSON } from "../src/errors.js";
import { line, lines, parse, parseAll } from "../src/render/cli.js";
import { sentence, sentences } from "../src/render/prose.js";
import { pack } from "./pack.js";

type Wire = Record<string, unknown>;
interface Rendering {
  line: string;
  sentence: string;
}
interface RulesPack {
  cases: {
    name: string;
    recovery: Wire;
    mentions_tool: boolean;
    renders: Record<string, Rendering>;
  }[];
  hand_written: {
    name: string;
    input: Wire;
    recovery: Wire;
    renders: Record<string, Rendering>;
  }[];
  rejected: { name: string; input: Wire }[];
  parse: { tool: string; line: string; intent: Wire; renders_back: string }[];
  parse_refused: string[];
}
interface RecoveryPack {
  sibling: string;
  entries: {
    tool: string;
    line: string;
    intent: Wire;
    sentence: string;
    other: Rendering;
  }[];
}

const rules = pack<RulesPack>("render-rules.json");
const corpus = pack<RecoveryPack>("recovery.json");

describe("render-rules: one recovery per rule", () => {
  for (const testCase of rules.cases) {
    describe(testCase.name, () => {
      const recovery = recoveryFromJSON(testCase.recovery);

      it("has the wire form the pack gives", () => {
        expect(recoveryToJSON(recovery)).toEqual(testCase.recovery);
      });

      it.each(Object.entries(testCase.renders))("renders for %s", (tool, expected) => {
        expect(line(recovery, tool)).toBe(expected.line);
        expect(sentence(recovery, tool)).toBe(expected.sentence);
      });

      it("mentions the tool exactly as the pack says", () => {
        expect(mentionsTool(recovery)).toBe(testCase.mentions_tool);
      });
    });
  }
});

describe("render-rules: hand-written wire forms", () => {
  it.each(rules.hand_written)("$name", (testCase) => {
    const recovery = recoveryFromJSON(testCase.input);
    expect(recoveryToJSON(recovery)).toEqual(testCase.recovery);
    for (const [tool, expected] of Object.entries(testCase.renders)) {
      expect(line(recovery, tool)).toBe(expected.line);
      expect(sentence(recovery, tool)).toBe(expected.sentence);
    }
  });

  it("never renders with a leading space", () => {
    for (const testCase of rules.hand_written) {
      const recovery = recoveryFromJSON(testCase.input);
      if ("lead" in testCase.input && testCase.input.lead === "") continue;
      expect(line(recovery, "t").startsWith(" ")).toBe(false);
      expect(sentence(recovery, "t").startsWith(" ")).toBe(false);
    }
  });
});

describe("render-rules: wire forms that must be refused", () => {
  it.each(rules.rejected)("$name", (testCase) => {
    expect(() => recoveryFromJSON(testCase.input)).toThrow();
  });
});

describe("render-rules: parse", () => {
  it.each(rules.parse)("$line", (testCase) => {
    const recovery = parse(testCase.line, testCase.tool);
    expect(recoveryToJSON(recovery)).toEqual(testCase.intent);
    expect(line(recovery, testCase.tool)).toBe(testCase.renders_back);
  });

  it.each(rules.parse_refused)("refuses %j", (text) => {
    expect(() => parse(text, "t")).toThrow("an empty line is not a recovery");
  });

  it("uses Python's whitespace set for the empty check and the argument split", () => {
    expect(() => parse("\x85\x1c\u00a0\u2003", "t")).toThrow();
    // U+FEFF is whitespace to JavaScript and not to Python.
    expect(() => parse("\ufeff", "t")).not.toThrow();
    expect(recoveryToJSON(parse("Run `t a\x1cb\x85c`", "t"))).toMatchObject({
      args: ["a", "b", "c"],
    });
  });

  it("does not let a set_env description cross a newline, as Python's . does not", () => {
    expect(parse("Set V to a\nb", "t").kind).toBe("note");
    // ...but does cross a carriage return, which JS's . would not.
    expect(parse("Set V to a\rb", "t").kind).toBe("set_env");
  });
});

describe("the recovery corpus", () => {
  // Parsed once: three tests below walk every entry, and parsing is the expensive step.
  const parsed: Recovery[] = corpus.entries.map((entry) => parse(entry.line, entry.tool));

  it("holds the population the plan names", () => {
    expect(corpus.entries.length).toBe(307);
  });

  it.each(corpus.entries.map((entry, index) => [index, entry.tool, entry.line] as const))(
    "entry %i (%s)",
    (index, tool) => {
      const entry = corpus.entries[index];
      const recovery = parsed[index];
      if (entry === undefined || recovery === undefined) throw new Error("no such entry");
      // the intent, in the wire form Python writes
      expect(recoveryToJSON(recovery)).toEqual(entry.intent);
      expect(recoveryFromJSON(entry.intent)).toEqual(recovery);
      // byte for byte, as a shell line and as prose
      expect(line(recovery, tool)).toBe(entry.line);
      expect(sentence(recovery, tool)).toBe(entry.sentence);
      // and for the sibling tool, which is the proof that no name was stored
      expect(line(recovery, corpus.sibling)).toBe(entry.other.line);
      expect(sentence(recovery, corpus.sibling)).toBe(entry.other.sentence);
    },
  );

  it("never stores the tool's name: rendered for another tool, the first one is absent", () => {
    // Unconditional, not gated on mentionsTool: a hand-authored intent holding the literal
    // name would sail through that gate.
    corpus.entries.forEach((entry, index) => {
      const recovery = parsed[index] as Recovery;
      expect(line(recovery, "other-tool")).not.toContain(entry.tool);
      expect(sentence(recovery, "other-tool")).not.toContain(entry.tool);
    });
  });

  it("renders identically for any tool when mentionsTool is false, and differently when true", () => {
    for (const recovery of parsed) {
      const same = line(recovery, "one-tool") === line(recovery, "two-tool");
      expect(same).toBe(!mentionsTool(recovery));
    }
  });

  it("exercises every kind", () => {
    const kinds = new Set(corpus.entries.map((entry) => entry.intent.kind));
    expect([...kinds].sort()).toEqual(
      ["choose", "note", "retry", "run", "set_env"].filter((k) => kinds.has(k)),
    );
    expect(
      kinds.has("run") && kinds.has("retry") && kinds.has("set_env") && kinds.has("note"),
    ).toBe(true);
  });
});

describe("lines, sentences and parseAll", () => {
  it("map in order", () => {
    const recoveries: Recovery[] = parseAll(["Run `hass-axi a` to b", "plain text"], "hass-axi");
    expect(lines(recoveries, "hass-axi")).toEqual(["Run `hass-axi a` to b", "plain text"]);
    expect(sentences(recoveries, "hass-axi")).toEqual([
      "To b, use hass-axi's `a` command.",
      "plain text.",
    ]);
  });
});

describe("a tool name is substituted literally, as Python's replace does", () => {
  it("does not interpret replacement patterns in the name", () => {
    const tool = "x$&y$1$`$'";
    expect(line(recoveryFromJSON({ kind: "note", text: "a {tool}" }), tool)).toBe(`a ${tool}`);
    expect(sentence(recoveryFromJSON({ kind: "note", text: "a {tool}" }), tool)).toBe(`a ${tool}.`);
    expect(recoveryToJSON(parse(`see ${tool} now`, tool))).toEqual({
      kind: "note",
      text: "see {tool} now",
    });
  });
});
