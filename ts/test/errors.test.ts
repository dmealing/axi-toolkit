import { describe, expect, it } from "vitest";
import {
  ApiError,
  AuthFailed,
  AxiError,
  CLASS_UNCLASSIFIED,
  CLASSES,
  ConfigError,
  ConnectionFailed,
  choose,
  EXIT_ERROR,
  EXIT_OK,
  EXIT_USAGE,
  Forbidden,
  faultClass,
  KINDS,
  mentionsTool,
  NotFound,
  note,
  type Recovery,
  recoveryFromJSON,
  recoveryToJSON,
  retry,
  run,
  setEnv,
  TOOL_SLOT,
  UsageError,
  withPurpose,
} from "../src/errors.js";
import { pack } from "./pack.js";

interface ErrorsPack {
  exit_codes: Record<string, number>;
  kinds: string[];
  tool_slot: string;
  classes: string[];
  unclassified: string;
  exceptions: { name: string; exit_code: number }[];
  fault_classes: {
    table: Record<string, string>;
    cases: { code: string | null; expected: string }[];
  };
  error_dicts: {
    name: string;
    exception: string;
    message: string;
    code: string | null;
    recovery: Record<string, unknown>[];
    expected: unknown;
  }[];
}

const errors = pack<ErrorsPack>("errors.json");
const CLASSES_BY_NAME: Record<string, new (message: string, options?: object) => AxiError> = {
  AxiError,
  UsageError,
  ConfigError,
  ConnectionFailed,
  AuthFailed,
  Forbidden,
  NotFound,
  ApiError,
};

describe("the constants", () => {
  it("match the pack", () => {
    expect({ EXIT_OK, EXIT_ERROR, EXIT_USAGE }).toEqual({
      EXIT_OK: errors.exit_codes.EXIT_OK,
      EXIT_ERROR: errors.exit_codes.EXIT_ERROR,
      EXIT_USAGE: errors.exit_codes.EXIT_USAGE,
    });
    expect([...KINDS]).toEqual(errors.kinds);
    expect(TOOL_SLOT).toBe(errors.tool_slot);
    expect([...CLASSES]).toEqual(errors.classes);
    expect(CLASS_UNCLASSIFIED).toBe(errors.unclassified);
  });
});

describe("the exception hierarchy", () => {
  it.each(errors.exceptions)("$name carries exit code $exit_code", ({ name, exit_code }) => {
    const Cls = CLASSES_BY_NAME[name];
    if (Cls === undefined) throw new Error(`no class named ${name}`);
    const error = new Cls("m");
    expect(error.exitCode).toBe(exit_code);
    expect(error.name).toBe(name);
    expect(error).toBeInstanceOf(AxiError);
    expect(error).toBeInstanceOf(Error);
  });

  it("covers every exception class the pack names, and no more", () => {
    expect(Object.keys(CLASSES_BY_NAME).sort()).toEqual(
      errors.exceptions.map((e) => e.name).sort(),
    );
  });

  it("keeps Forbidden apart from AuthFailed and ApiError", () => {
    const error = new Forbidden("m");
    expect(error).not.toBeInstanceOf(AuthFailed);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("has no helpLines member", () => {
    const error = new AxiError("m") as unknown as Record<string, unknown>;
    expect("helpLines" in error).toBe(false);
    expect("help_lines" in error).toBe(false);
  });

  it("stores the code as null when absent, and recovery as a frozen empty array", () => {
    const error = new AxiError("m");
    expect(error.code).toBeNull();
    expect(error.recovery).toEqual([]);
    expect(Object.isFrozen(error.recovery)).toBe(true);
  });

  it("passes the cause through", () => {
    const cause = new Error("inner");
    expect(new AxiError("m", { cause }).cause).toBe(cause);
  });
});

describe("faultClass", () => {
  it.each(errors.fault_classes.cases)("$code is $expected", ({ code, expected }) => {
    expect(faultClass(code, errors.fault_classes.table)).toBe(expected);
    expect(faultClass(code, new Map(Object.entries(errors.fault_classes.table)))).toBe(expected);
    expect(new AxiError("m", { code }).faultClass(errors.fault_classes.table)).toBe(expected);
  });

  it("does not read inherited members", () => {
    for (const code of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(faultClass(code, {})).toBe(CLASS_UNCLASSIFIED);
    }
  });
});

describe("the JSON wire form of an error", () => {
  it.each(errors.error_dicts)("$name", (entry) => {
    const Cls = CLASSES_BY_NAME[entry.exception];
    if (Cls === undefined) throw new Error(`no class named ${entry.exception}`);
    const error = new Cls(entry.message, {
      code: entry.code,
      recovery: entry.recovery.map(recoveryFromJSON),
    });
    expect(error.toJSON()).toEqual(entry.expected);
    expect(JSON.parse(JSON.stringify(error))).toEqual(entry.expected);
  });
});

describe("the factories", () => {
  it("apply the per-kind defaults", () => {
    expect(run(["a"])).toMatchObject({ lead: "Run", separator: " ", purpose: "" });
    expect(retry("--x")).toMatchObject({ lead: "Run the command again with", separator: " " });
    expect(setEnv("V", "d")).toMatchObject({ example: "", reference: "" });
  });

  it.each([
    ["a run without arguments", () => run([])],
    ["a retry without a fragment", () => retry("")],
    ["a set_env without a variable", () => setEnv("", "d")],
    ["a set_env without a description", () => setEnv("V", "")],
    ["a choose without values", () => choose("l", [])],
    ["a choose without a label", () => choose("", ["a"])],
    ["a note without text", () => note("")],
    ["a note with a second placeholder", () => note("a {count} of things")],
  ])("refuse %s", (_name, build) => {
    expect(build).toThrow(Error);
  });

  it("let a note write the tool slot, and only that", () => {
    expect(note("hi {tool}, {tool}").text).toBe("hi {tool}, {tool}");
    expect(() => note("{ tool }")).toThrow();
  });

  it("copy their input, so a caller cannot change a recovery afterwards", () => {
    const args = ["a"];
    const recovery = run(args);
    args.push("b");
    expect(recovery.args).toEqual(["a"]);
    expect(Object.isFrozen(recovery)).toBe(true);
  });

  it("replace the purpose of a run or retry only", () => {
    expect(withPurpose(run(["a"]), "to b").purpose).toBe("to b");
    expect(withPurpose(retry("--x"), "for c").purpose).toBe("for c");
  });
});

describe("the wire form of a recovery", () => {
  it("writes kind first, then the kind's fields in sorted order", () => {
    expect(Object.keys(recoveryToJSON(run(["a"], { separator: ": ", purpose: "p" })))).toEqual([
      "kind",
      "args",
      "lead",
      "purpose",
      "separator",
    ]);
    expect(Object.keys(recoveryToJSON(setEnv("V", "d", { example: "e", reference: "r" })))).toEqual(
      ["kind", "describes", "example", "reference", "variable"],
    );
  });

  it("writes a note's text under text, and omits unset fields", () => {
    expect(recoveryToJSON(note("hi {tool}"))).toEqual({ kind: "note", text: "hi {tool}" });
    expect(recoveryToJSON(setEnv("V", "d"))).toEqual({
      kind: "set_env",
      describes: "d",
      variable: "V",
    });
  });

  it("always writes the lead of a run or retry, an empty one included", () => {
    expect(recoveryToJSON(run(["a"]))).toEqual({ kind: "run", args: ["a"], lead: "Run" });
    expect(recoveryToJSON({ ...run(["a"]), lead: "" })).toEqual({
      kind: "run",
      args: ["a"],
      lead: "",
    });
  });

  it("round-trips through the wire form", () => {
    const all: Recovery[] = [
      run(["a", "b"], { purpose: "p", lead: "Do", separator: ": " }),
      { ...retry("--x"), lead: "" },
      setEnv("V", "d", { example: "e", reference: "r" }),
      choose("l", ["a", "b"]),
      note("hi {tool}"),
    ];
    for (const recovery of all) {
      expect(recoveryFromJSON(JSON.parse(JSON.stringify(recoveryToJSON(recovery))))).toEqual(
        recovery,
      );
    }
  });

  it.each([
    [null],
    [[]],
    ["run"],
    [{ kind: "run", args: "x" }],
    [{ kind: "run", args: [1] }],
    [{ kind: "retry", fragment: 1 }],
    [{ kind: "run", args: ["x"], lead: 1 }],
  ])("refuses a malformed wire form %j", (input) => {
    expect(() => recoveryFromJSON(input)).toThrow();
  });
});

describe("mentionsTool", () => {
  it("is true for a run and a note with the slot, and false otherwise", () => {
    expect(mentionsTool(run(["a"]))).toBe(true);
    expect(mentionsTool(note("x {tool}"))).toBe(true);
    expect(mentionsTool(note("x"))).toBe(false);
    expect(mentionsTool(retry("--x"))).toBe(false);
    expect(mentionsTool(setEnv("V", "d"))).toBe(false);
    expect(mentionsTool(choose("l", ["a"]))).toBe(false);
  });
});

describe("parity with Python on inputs the pack never emits", () => {
  it("keeps an explicit empty separator on the wire and through a round trip", () => {
    const recovery = run(["x"], { separator: "", purpose: "p" });
    expect(recoveryToJSON(recovery)).toMatchObject({ separator: "" });
    expect(recoveryFromJSON(recoveryToJSON(recovery))).toEqual(recovery);
  });

  it("refuses a purpose on a kind that cannot carry one", () => {
    expect(() => withPurpose(note("hi") as never, "p")).toThrow("cannot carry 'purpose'");
  });

  it("accepts any ReadonlyMap-like table", () => {
    const table = {
      get: (k: string) => (k === "A" ? "auth" : undefined),
    } as unknown as ReadonlyMap<string, string>;
    expect(faultClass("A", table)).toBe("auth");
  });
});
