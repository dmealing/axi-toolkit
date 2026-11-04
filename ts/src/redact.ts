/**
 * The redaction boundary: register a secret, and get it back out of anything printed.
 *
 * What has to hold identically across ports is a set of literal secrets, a list of
 * credential shapes, and one function that removes both. The shapes are not a fixed list:
 * `registerPattern` is how a tool adds its own, and the order they run in is fixed because
 * that order is observable.
 *
 * **The order is: literals, then the bearer header, then registered patterns, then the
 * JWT.** Literals go first and longest-first, so an overlapping pair (`user:password`) is
 * replaced whole rather than leaving a half-redacted fragment. The JWT rule goes last
 * because it replaces its whole match rather than keeping a prefix, and a rule that keeps a
 * prefix should have had its chance first.
 *
 * Differences from the Python module, all of which only redact more or are pinned by the
 * conformance pack: shapes are `RegExp` objects (or source strings compiled with the `u`
 * flag), `\b` is ASCII-only, and `MIN_SECRET_LENGTH` counts code points as Python does.
 */

import { codePointLength, PY_WS } from "./internal/pystr.js";

/** Placeholder substituted for anything that looks like a credential. */
export const REDACTED = "<redacted>";

/**
 * Below this length, redacting a literal does more damage than good: a short string
 * collides with ordinary words. Lowered only for values known to be credentials by where
 * they came from (URL userinfo, say) rather than by their shape.
 */
export const MIN_SECRET_LENGTH = 8;

/**
 * A bearer credential in an HTTP header. Keeps the `Bearer ` prefix so the reader can
 * still see what kind of header was involved. Global, so do not call `.test` on it.
 */
export const BEARER = new RegExp(`\\b(bearer[${PY_WS}]+)[A-Za-z0-9._~+/=-]{8,}`, "giu");

/** A JSON Web Token: three base64url segments, the first starting `eyJ`. Global, as above. */
export const JWT = /\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}/gu;

export interface RegisterSecretOptions {
  readonly minLength?: number;
}

function globalised(pattern: string | RegExp): RegExp {
  if (typeof pattern === "string") return new RegExp(pattern, "gu");
  return new RegExp(
    pattern.source,
    pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`,
  );
}

/** How many capturing groups a pattern has. */
function groupCount(pattern: RegExp): number {
  const match = new RegExp(`${pattern.source}|`, pattern.flags.replace(/[gy]/g, "")).exec("");
  return (match?.length ?? 1) - 1;
}

function apply(pattern: RegExp, text: string): string {
  if (groupCount(pattern) > 0) {
    return text.replace(
      pattern,
      (...args: unknown[]) => `${(args[1] as string | undefined) ?? ""}${REDACTED}`,
    );
  }
  return text.replace(pattern, REDACTED);
}

/**
 * A set of literal secrets and credential shapes, and the filter over them.
 *
 * A class rather than only module state so a test can hold one in isolation, and so a
 * caller embedding two tools at once can keep their shapes apart. The module-level
 * functions operate on one shared instance, which is what a CLI wants.
 */
export class Redactor {
  readonly #secrets = new Set<string>();
  readonly #patterns: RegExp[] = [];

  /** Register a literal string that must never reach stdout or stderr. */
  registerSecret(value: string | null | undefined, options: RegisterSecretOptions = {}): void {
    const minLength = options.minLength ?? MIN_SECRET_LENGTH;
    if (value && codePointLength(value) >= minLength) this.#secrets.add(value);
  }

  /** Drop registered literals, keeping registered shapes. */
  resetSecrets(): void {
    this.#secrets.clear();
  }

  /**
   * Register a credential shape this caller's system produces. A pattern with a capturing
   * group keeps group 1 and redacts the rest, which is how `X-Plex-Token=abc123` becomes
   * `X-Plex-Token=<redacted>`; one with no group is replaced whole. Registering the same
   * source twice is a no-op. Returns the compiled (global) pattern.
   */
  registerPattern(pattern: string | RegExp): RegExp {
    const compiled = globalised(pattern);
    if (this.#patterns.every((existing) => existing.source !== compiled.source)) {
      this.#patterns.push(compiled);
    }
    return compiled;
  }

  /** The source of each registered shape, in the order they run. */
  registeredPatterns(): readonly string[] {
    return this.#patterns.map((pattern) => pattern.source);
  }

  /** Drop literals and shapes both. */
  reset(): void {
    this.#secrets.clear();
    this.#patterns.length = 0;
  }

  /** Remove credentials from `text` by literal match and by shape. */
  redact(text: string): string {
    let out = text;
    const longestFirst = [...this.#secrets].sort((a, b) => codePointLength(b) - codePointLength(a));
    for (const secret of longestFirst) out = out.replaceAll(secret, REDACTED);
    out = apply(BEARER, out);
    for (const pattern of this.#patterns) out = apply(pattern, out);
    return apply(JWT, out);
  }
}

/** The instance a CLI uses. One process, one output boundary, one set of secrets. */
const shared = new Redactor();

/** Register a literal on the shared redactor. */
export function registerSecret(
  value: string | null | undefined,
  options: RegisterSecretOptions = {},
): void {
  shared.registerSecret(value, options);
}

/** Register one shape on the shared redactor. */
export function registerPattern(pattern: string | RegExp): RegExp {
  return shared.registerPattern(pattern);
}

/** Register several shapes on the shared redactor, in order. */
export function registerPatterns(patterns: Iterable<string | RegExp>): void {
  for (const pattern of patterns) shared.registerPattern(pattern);
}

/** The shapes registered on the shared redactor, in the order they run. */
export function registeredPatterns(): readonly string[] {
  return shared.registeredPatterns();
}

/** Remove credentials from `text` using the shared redactor. */
export function redact(text: string): string {
  return shared.redact(text);
}

/** Drop the shared redactor's literals. */
export function resetSecrets(): void {
  shared.resetSecrets();
}

/** Drop the shared redactor's literals and shapes. */
export function reset(): void {
  shared.reset();
}
