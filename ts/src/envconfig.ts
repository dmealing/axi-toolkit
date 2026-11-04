/**
 * Connection settings, read from the environment and never from a file.
 *
 * A credential passed on a command line leaks into shell history and the process table,
 * and a credential in a file leaks into commits. The environment is the only channel, and
 * there is deliberately no `--token` flag anywhere.
 *
 * Everything that differs between tools (variable names and aliases, the scheme a bare host
 * gets, a default port, a path suffix to strip) is a property of the system behind the tool,
 * so it lives on a `CredentialSpec` the tool declares. Three mechanisms are shared: the
 * environment is the only source, a token that cannot be an HTTP header value is rejected
 * before anything sends it, and `user:password@` in a URL is separated off and registered as
 * a secret rather than carried into anything printable.
 *
 * URLs are split the way Python's `urlsplit` splits them (see `internal/pystr`), not with
 * WHATWG `URL`, which would lowercase the host and drop a default port.
 */

import { ConfigError, type Recovery } from "./errors.js";
import {
  isBlank,
  PY_WS,
  pyRepr,
  pyStrip,
  pyUrlsplit,
  pyUrlunsplit,
  rstripSlashes,
  type UrlParts,
} from "./internal/pystr.js";
import { registerSecret } from "./redact.js";

export const DEFAULT_TIMEOUT = 30;

/**
 * Anything a token must not contain. A header value cannot carry a line break, and an HTTP
 * client throws an error embedding the whole `Bearer ...` header when it finds one, which
 * is a credential inside a stack trace. So the check happens where the value is read.
 * Python's whitespace set, so U+0085 is illegal and U+FEFF is not.
 */
export const ILLEGAL_TOKEN = new RegExp(`[${PY_WS}\\x00-\\x1f\\x7f]`, "u");

const SCHEMES = ["http", "https"] as const;
type Scheme = (typeof SCHEMES)[number];

function isScheme(value: string): value is Scheme {
  return (SCHEMES as readonly string[]).includes(value);
}

/** How one tool reads its credentials from the environment. */
export interface CredentialSpec {
  /** Variable names for the base URL, most-preferred first; later ones are aliases. */
  readonly urlVars: readonly string[];
  /** Variable names for the credential, most-preferred first. */
  readonly tokenVars: readonly string[];
  /** What to set each variable to. */
  readonly setup: readonly Recovery[];
  /** How to confirm the settings work once both are present, kept apart from `setup`. */
  readonly verify: Recovery | null;
  /** What to check when the credential carries a character a header cannot. */
  readonly tokenRecovery: readonly Recovery[];
  /** The scheme a bare host gets: `https` unless the system genuinely serves plain HTTP. */
  readonly defaultScheme: Scheme;
  /** A port appended to a host that names none, or `null`. */
  readonly defaultPort: number | null;
  /** A path suffix stripped from the base URL; `""` for none. */
  readonly stripPathSuffix: string;
  readonly defaultTimeout: number;
}

export type CredentialSpecInit = Pick<CredentialSpec, "urlVars" | "tokenVars"> &
  Partial<Omit<CredentialSpec, "urlVars" | "tokenVars">>;

/** Build a `CredentialSpec`, applying defaults and refusing an unusable declaration. */
export function credentialSpec(init: CredentialSpecInit): CredentialSpec {
  if (init.urlVars.length === 0 || init.tokenVars.length === 0) {
    throw new RangeError("a credential spec names at least one URL and one token variable");
  }
  const defaultScheme = init.defaultScheme ?? "https";
  if (!isScheme(defaultScheme)) {
    throw new RangeError(
      `defaultScheme must be one of ${JSON.stringify(SCHEMES)}, got ${pyRepr(String(defaultScheme))}`,
    );
  }
  return Object.freeze({
    urlVars: Object.freeze([...init.urlVars]),
    tokenVars: Object.freeze([...init.tokenVars]),
    setup: Object.freeze([...(init.setup ?? [])]),
    verify: init.verify ?? null,
    tokenRecovery: Object.freeze([...(init.tokenRecovery ?? [])]),
    defaultScheme,
    defaultPort: init.defaultPort ?? null,
    stripPathSuffix: init.stripPathSuffix ?? "",
    defaultTimeout: init.defaultTimeout ?? DEFAULT_TIMEOUT,
  });
}

/** A resolved, ready-to-use configuration, with the variable names it came from. */
export interface Credentials {
  readonly baseUrl: string;
  readonly token: string;
  readonly timeout: number;
  readonly urlVar: string;
  readonly tokenVar: string;
}

export type Environ = Readonly<Record<string, string | undefined>>;

/** The first of `names` set to something other than whitespace, and its stripped value. */
export function firstEnv(
  names: readonly string[],
  environ: Environ,
): [name: string, value: string] | [null, null] {
  for (const name of names) {
    const value = environ[name];
    if (typeof value === "string" && value && !isBlank(value)) return [name, pyStrip(value)];
  }
  return [null, null];
}

/** Separate any `user:password@` prefix from a network location. */
export function splitUserinfo(netloc: string): [userinfo: string, host: string] {
  const at = netloc.lastIndexOf("@");
  if (at < 0) return ["", netloc];
  return [netloc.slice(0, at), netloc.slice(at + 1)];
}

/**
 * Register `user:password` and the password alone as secrets, so from here on either can only
 * be printed through the redacting output boundary.
 */
function registerUserinfo(userinfo: string): void {
  if (!userinfo) return;
  registerSecret(userinfo, { minLength: 4 });
  const colon = userinfo.indexOf(":");
  if (colon >= 0) registerSecret(userinfo.slice(colon + 1), { minLength: 4 });
}

/** Accept a bare host, apply `spec`'s defaults, and drop any trailing path noise. */
export function normalizeBaseUrl(raw: string, spec: CredentialSpec): string {
  let value = rstripSlashes(pyStrip(raw));
  if (!value.includes("://")) value = `${spec.defaultScheme}://${value}`;
  const refuse = (message: string): ConfigError =>
    new ConfigError(message, { recovery: spec.setup.slice(0, 1), code: "BAD_URL" });
  const unusable = (): ConfigError => {
    registerUserinfo(splitUserinfo(value.slice(value.indexOf("://") + 3))[0]);
    return refuse(`${spec.urlVars[0]} is not a usable URL: ${pyRepr(value)}`);
  };
  let parts: UrlParts;
  try {
    parts = pyUrlsplit(value);
  } catch {
    throw unusable();
  }
  if (!parts.netloc) throw unusable();
  if (!isScheme(parts.scheme)) {
    throw refuse(`${spec.urlVars[0]} must use http or https, got ${pyRepr(parts.scheme)}`);
  }
  let path = rstripSlashes(parts.path);
  if (spec.stripPathSuffix && path.endsWith(spec.stripPathSuffix)) {
    path = path.slice(0, path.length - spec.stripPathSuffix.length);
  }
  const [userinfo, hostPart] = splitUserinfo(parts.netloc);
  let host = hostPart;
  registerUserinfo(userinfo);
  // Slice after the last "]" so a bracketed IPv6 literal's own colons are not read as a port.
  if (spec.defaultPort && !host.slice(host.lastIndexOf("]") + 1).includes(":")) {
    host = `${host}:${spec.defaultPort}`;
  }
  return pyUrlunsplit(parts.scheme, host, path);
}

export interface LoadOptions {
  readonly timeout?: number | null;
}

/** Resolve credentials, or throw a `ConfigError` naming what is absent. */
export function load(
  spec: CredentialSpec,
  environ: Environ = process.env,
  options: LoadOptions = {},
): Credentials {
  const [urlVar, rawUrl] = firstEnv(spec.urlVars, environ);
  const [tokenVar, token] = firstEnv(spec.tokenVars, environ);

  const missing = missingVars(spec, environ);
  if (missing.length > 0) {
    throw new ConfigError(
      `${missing.join(" and ")} ${missing.length > 1 ? "are" : "is"} not set in the environment`,
      { recovery: setupRecovery(spec), code: "NOT_CONFIGURED" },
    );
  }

  if (ILLEGAL_TOKEN.test(token as string)) {
    // The message names the variable and never the value: a rejected credential is still a
    // credential, and an error message is printed.
    throw new ConfigError(`${spec.tokenVars[0]} contains whitespace or a control character`, {
      recovery: spec.tokenRecovery,
      code: "BAD_TOKEN",
    });
  }

  // Registered at the moment it is read, so no later code path can print it.
  registerSecret(token);
  return Object.freeze({
    baseUrl: normalizeBaseUrl(rawUrl as string, spec),
    token: token as string,
    timeout: options.timeout ?? spec.defaultTimeout,
    urlVar: urlVar ?? "",
    tokenVar: tokenVar ?? "",
  });
}

/** The guidance offered wherever configuration is found to be absent. */
export function setupRecovery(
  spec: CredentialSpec,
  options: { readonly includeVerify?: boolean } = {},
): readonly Recovery[] {
  if ((options.includeVerify ?? true) && spec.verify !== null) return [...spec.setup, spec.verify];
  return [...spec.setup];
}

export interface EnvironmentDescription {
  readonly urlVar: string;
  readonly urlSet: boolean;
  readonly tokenVar: string;
  readonly tokenSet: boolean;
}

/** Report which variables are set without ever revealing the credential. */
export function describeEnvironment(
  spec: CredentialSpec,
  environ: Environ = process.env,
): EnvironmentDescription {
  const [urlVar, rawUrl] = firstEnv(spec.urlVars, environ);
  const [tokenVar, token] = firstEnv(spec.tokenVars, environ);
  return {
    urlVar: urlVar ?? "",
    urlSet: Boolean(rawUrl),
    tokenVar: tokenVar ?? "",
    tokenSet: Boolean(token),
  };
}

/** The primary variable names that are absent, in the order to report them. */
export function missingVars(spec: CredentialSpec, environ: Environ = process.env): string[] {
  const described = describeEnvironment(spec, environ);
  const missing: string[] = [];
  if (!described.urlSet) missing.push(spec.urlVars[0] as string);
  if (!described.tokenSet) missing.push(spec.tokenVars[0] as string);
  return missing;
}
