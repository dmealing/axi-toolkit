import { afterEach, describe, expect, it } from "vitest";
import {
  type CredentialSpec,
  credentialSpec,
  DEFAULT_TIMEOUT,
  describeEnvironment,
  firstEnv,
  ILLEGAL_TOKEN,
  load,
  missingVars,
  normalizeBaseUrl,
  setupRecovery,
  splitUserinfo,
} from "../src/envconfig.js";
import {
  AxiError,
  ConfigError,
  note,
  type Recovery,
  recoveryFromJSON,
  recoveryToJSON,
  run,
} from "../src/errors.js";
import { redact, reset } from "../src/redact.js";
import { lines } from "../src/render/cli.js";
import { pack } from "./pack.js";

type Wire = Record<string, unknown>;
interface Failure {
  name: string;
  operation: "load" | "normalize_base_url";
  environ?: Record<string, string>;
  raw?: string;
  expected: { message: string; code: string; recovery: Wire[]; lines: string[] };
}
interface CredentialsPack {
  constants: {
    default_timeout: number;
    illegal_token: { source: string; flags: string };
    error_codes: string[];
  };
  tools: Record<
    string,
    {
      spec: {
        url_vars: string[];
        token_vars: string[];
        setup: Wire[];
        verify: Wire | null;
        token_recovery: Wire[];
        default_scheme: "http" | "https";
        default_port: number | null;
        strip_path_suffix: string;
        default_timeout: number;
      };
      normalized_urls: { raw: string; expected: string }[];
      failures: Failure[];
      loads: {
        name: string;
        environ: Record<string, string>;
        timeout: number | null;
        expected: {
          base_url: string;
          token: string;
          timeout: number;
          url_var: string;
          token_var: string;
        };
      }[];
      describes: {
        name: string;
        environ: Record<string, string>;
        describe_environment: {
          url_var: string;
          url_set: boolean;
          token_var: string;
          token_set: boolean;
        };
        missing_vars: string[];
      }[];
    }
  >;
}

const data = pack<CredentialsPack>("credentials.json");

function specOf(tool: string): CredentialSpec {
  const wire = (data.tools[tool] as CredentialsPack["tools"][string]).spec;
  return credentialSpec({
    urlVars: wire.url_vars,
    tokenVars: wire.token_vars,
    setup: wire.setup.map(recoveryFromJSON),
    verify: wire.verify === null ? null : recoveryFromJSON(wire.verify),
    tokenRecovery: wire.token_recovery.map(recoveryFromJSON),
    defaultScheme: wire.default_scheme,
    defaultPort: wire.default_port,
    stripPathSuffix: wire.strip_path_suffix,
    defaultTimeout: wire.default_timeout,
  });
}

function caught(fn: () => unknown): ConfigError {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(ConfigError);
    return error as ConfigError;
  }
  throw new Error("expected a ConfigError");
}

afterEach(() => reset());

describe("the credentials pack", () => {
  it("agrees on the constants", () => {
    expect(DEFAULT_TIMEOUT).toBe(data.constants.default_timeout);
    expect(data.constants.error_codes).toEqual(["BAD_TOKEN", "BAD_URL", "NOT_CONFIGURED"]);
  });

  it("agrees with the pack's illegal-token rule except where Python and JS whitespace differ", () => {
    const theirs = new RegExp(
      data.constants.illegal_token.source,
      data.constants.illegal_token.flags,
    );
    const differing: number[] = [];
    for (let code = 0; code < 0x10000; code += 1) {
      if (code >= 0xd800 && code <= 0xdfff) continue;
      const char = String.fromCharCode(code);
      if (theirs.test(char) !== ILLEGAL_TOKEN.test(char)) differing.push(code);
    }
    // Python's `\s` has U+0085 and not U+FEFF; the engine's `\s` has the reverse.
    expect(differing).toEqual([0x85, 0xfeff]);
  });

  for (const tool of Object.keys(data.tools)) {
    const section = data.tools[tool] as CredentialsPack["tools"][string];
    describe(tool, () => {
      it("declares a spec the factory accepts unchanged", () => {
        const spec = specOf(tool);
        expect(spec.urlVars).toEqual(section.spec.url_vars);
        expect(spec.defaultPort).toBe(section.spec.default_port);
        expect(spec.verify === null ? null : recoveryToJSON(spec.verify)).toEqual(
          section.spec.verify,
        );
      });

      for (const { raw, expected } of section.normalized_urls) {
        it(`normalises ${JSON.stringify(raw)}`, () => {
          expect(normalizeBaseUrl(raw, specOf(tool))).toBe(expected);
        });
      }

      for (const failure of section.failures) {
        it(`refuses ${failure.name}`, () => {
          const spec = specOf(tool);
          const error = caught(() =>
            failure.operation === "load"
              ? load(spec, failure.environ ?? {})
              : normalizeBaseUrl(failure.raw as string, spec),
          );
          expect(error.message).toBe(failure.expected.message);
          expect(error.code).toBe(failure.expected.code);
          expect(error.recovery.map(recoveryToJSON)).toEqual(failure.expected.recovery);
          expect(lines(error.recovery, tool)).toEqual(failure.expected.lines);
        });
      }

      for (const kase of section.loads) {
        it(`loads ${kase.name}`, () => {
          const got = load(
            specOf(tool),
            kase.environ,
            kase.timeout === null ? {} : { timeout: kase.timeout },
          );
          expect({
            base_url: got.baseUrl,
            token: got.token,
            timeout: got.timeout,
            url_var: got.urlVar,
            token_var: got.tokenVar,
          }).toEqual(kase.expected);
        });
      }

      for (const kase of section.describes) {
        it(`describes ${kase.name}`, () => {
          const spec = specOf(tool);
          const got = describeEnvironment(spec, kase.environ);
          expect({
            url_var: got.urlVar,
            url_set: got.urlSet,
            token_var: got.tokenVar,
            token_set: got.tokenSet,
          }).toEqual(kase.describe_environment);
          expect(missingVars(spec, kase.environ)).toEqual(kase.missing_vars);
        });
      }
    });
  }
});

const SPEC = credentialSpec({
  urlVars: ["EXAMPLE_URL", "EXAMPLE_ALIAS"],
  tokenVars: ["EXAMPLE_TOKEN"],
  setup: [note("set it")],
  verify: run(["doctor"]),
});

describe("credentialSpec", () => {
  it("fills the defaults and freezes the result", () => {
    const spec = credentialSpec({ urlVars: ["U"], tokenVars: ["T"] });
    expect(spec).toMatchObject({
      defaultScheme: "https",
      defaultPort: null,
      stripPathSuffix: "",
      defaultTimeout: 30,
      verify: null,
      setup: [],
      tokenRecovery: [],
    });
    expect(Object.isFrozen(spec)).toBe(true);
  });

  it("refuses a spec with no variable to read", () => {
    expect(() => credentialSpec({ urlVars: [], tokenVars: ["T"] })).toThrow(RangeError);
    expect(() => credentialSpec({ urlVars: ["U"], tokenVars: [] })).toThrow(RangeError);
  });

  it("refuses a scheme other than http or https", () => {
    expect(() =>
      credentialSpec({ urlVars: ["U"], tokenVars: ["T"], defaultScheme: "ftp" as "http" }),
    ).toThrow("defaultScheme must be one of");
  });
});

describe("environment reading", () => {
  it("strips a value and skips a blank one", () => {
    expect(firstEnv(["A", "B"], { A: " \u0085 ", B: "  v  " })).toEqual(["B", "v"]);
    expect(firstEnv(["A"], {})).toEqual([null, null]);
    expect(firstEnv(["A"], { A: "" })).toEqual([null, null]);
  });

  it("ignores a prototype member that is not a string, and reads an inherited string", () => {
    expect(firstEnv(["toString", "constructor"], {})).toEqual([null, null]);
    expect(firstEnv(["A"], Object.create({ A: " v " }))).toEqual(["A", "v"]);
  });

  it("reads process.env when given no environment", () => {
    process.env.AXI_TEST_PROBE = " here ";
    try {
      expect(firstEnv(["AXI_TEST_PROBE"], process.env)).toEqual(["AXI_TEST_PROBE", "here"]);
      expect(
        describeEnvironment(
          credentialSpec({ urlVars: ["AXI_TEST_PROBE"], tokenVars: ["NOPE_NOT_SET"] }),
        ),
      ).toMatchObject({
        urlVar: "AXI_TEST_PROBE",
        urlSet: true,
        tokenSet: false,
      });
    } finally {
      delete process.env.AXI_TEST_PROBE;
    }
  });

  it("splits userinfo at the last @", () => {
    expect(splitUserinfo("a:b@c@host:1")).toEqual(["a:b@c", "host:1"]);
    expect(splitUserinfo("host")).toEqual(["", "host"]);
  });
});

describe("load", () => {
  const environ = { EXAMPLE_URL: "host.example.com", EXAMPLE_TOKEN: "probe-0123456789abcdef" };

  it("registers the token so it cannot be printed", () => {
    load(SPEC, environ);
    expect(redact("token is probe-0123456789abcdef")).toBe("token is <redacted>");
  });

  it("registers the userinfo and the password of a URL, at four characters", () => {
    const got = load(SPEC, { ...environ, EXAMPLE_URL: "https://someone:pw-ab@host.example.com" });
    expect(got.baseUrl).toBe("https://host.example.com");
    expect(redact("someone:pw-ab and pw-ab")).toBe("<redacted> and <redacted>");
  });

  it("does not register a password the URL does not carry", () => {
    normalizeBaseUrl("https://onlyuser@host.example.com", SPEC);
    expect(redact("onlyuser")).toBe("<redacted>");
    expect(redact("host.example.com")).toBe("host.example.com");
  });

  it("names the variable and never the value of a rejected token", () => {
    const error = caught(() => load(SPEC, { ...environ, EXAMPLE_TOKEN: "abc\u0085def" }));
    expect(error.message).toBe("EXAMPLE_TOKEN contains whitespace or a control character");
    expect(error.message).not.toContain("abc");
    expect(error.code).toBe("BAD_TOKEN");
  });

  it("accepts a token holding U+FEFF, which Python does not call whitespace", () => {
    expect(load(SPEC, { ...environ, EXAMPLE_TOKEN: "probe﻿0123456789" }).token).toBe(
      "probe﻿0123456789",
    );
  });

  it("is an AxiError and a ConfigError", () => {
    const error = caught(() => load(SPEC, {}));
    expect(error).toBeInstanceOf(AxiError);
    expect(error.message).toBe("EXAMPLE_URL and EXAMPLE_TOKEN are not set in the environment");
  });

  it("returns a frozen result", () => {
    expect(Object.isFrozen(load(SPEC, environ))).toBe(true);
  });

  it("reads process.env by default", () => {
    process.env.EXAMPLE_URL = "host.example.com";
    process.env.EXAMPLE_TOKEN = "probe-0123456789abcdef";
    try {
      expect(load(SPEC).baseUrl).toBe("https://host.example.com");
    } finally {
      delete process.env.EXAMPLE_URL;
      delete process.env.EXAMPLE_TOKEN;
    }
  });
});

describe("normalizeBaseUrl", () => {
  const withPort = credentialSpec({ urlVars: ["U"], tokenVars: ["T"], defaultPort: 8000 });

  it("repr-quotes the offending value with Python's rules", () => {
    expect(caught(() => normalizeBaseUrl("://it's", SPEC)).message).toBe(
      `EXAMPLE_URL is not a usable URL: "://it's"`,
    );
    expect(caught(() => normalizeBaseUrl("ftp://h", SPEC)).message).toBe(
      "EXAMPLE_URL must use http or https, got 'ftp'",
    );
  });

  it("recovers with the first setup step only", () => {
    const spec = credentialSpec({
      urlVars: ["U"],
      tokenVars: ["T"],
      setup: [note("one"), note("two")],
    });
    const recovery: readonly Recovery[] = caught(() => normalizeBaseUrl("", spec)).recovery;
    expect(recovery.map(recoveryToJSON)).toEqual([recoveryToJSON(note("one"))]);
  });

  it("keeps a host's case and an explicit default port, unlike WHATWG URL", () => {
    expect(normalizeBaseUrl("https://User:pw-ab@Host.Example.COM:443/api/", SPEC)).toBe(
      "https://Host.Example.COM:443/api",
    );
  });

  it("adds the default port once, and not to a bracketed host that already has one", () => {
    expect(normalizeBaseUrl("h.example.com", withPort)).toBe("https://h.example.com:8000");
    expect(normalizeBaseUrl("http://[::1]", withPort)).toBe("http://[::1]:8000");
    expect(normalizeBaseUrl("http://[::1]:9", withPort)).toBe("http://[::1]:9");
  });

  it("strips the declared suffix from the end of the path only", () => {
    const spec = credentialSpec({ urlVars: ["U"], tokenVars: ["T"], stripPathSuffix: "/api" });
    expect(normalizeBaseUrl("h/x/api//", spec)).toBe("https://h/x");
    expect(normalizeBaseUrl("h/api/x", spec)).toBe("https://h/api/x");
  });

  it("drops a query and a fragment", () => {
    expect(normalizeBaseUrl("https://h/p?x=1#y", SPEC)).toBe("https://h/p");
  });

  it("reports an unbalanced bracket as BAD_URL rather than a bare Error", () => {
    const error = caught(() => normalizeBaseUrl("http://[::1", SPEC));
    expect(error.code).toBe("BAD_URL");
  });

  it("registers the userinfo of a URL it refuses, so the message redacts", () => {
    const password = ["example", "refused", "secret"].join("-");
    for (const raw of [
      `https://someone:${password}@[fe80::1`,
      `https:///someone:${password}@host.example.com`,
    ]) {
      const error = caught(() => normalizeBaseUrl(raw, SPEC));
      expect(error.code).toBe("BAD_URL");
      expect(error.message).toBe(`EXAMPLE_URL is not a usable URL: '${raw}'`);
      expect(redact(error.message)).not.toContain(password);
      reset();
    }
  });

  it("lowercases the scheme before checking it", () => {
    expect(normalizeBaseUrl("HTTP://h", SPEC)).toBe("http://h");
  });
});

describe("setupRecovery", () => {
  it("appends the verify step unless asked not to", () => {
    expect(setupRecovery(SPEC).map(recoveryToJSON)).toEqual(
      [note("set it"), run(["doctor"])].map(recoveryToJSON),
    );
    expect(setupRecovery(SPEC, { includeVerify: false })).toEqual([note("set it")]);
    expect(setupRecovery(credentialSpec({ urlVars: ["U"], tokenVars: ["T"] }))).toEqual([]);
  });
});
