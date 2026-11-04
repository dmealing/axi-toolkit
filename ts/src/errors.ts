/**
 * The AXI error contract: a code, a fault class, and recovery carried as data.
 *
 * Recovery is structured intent, never a rendered line. The tool's name arrives when
 * somebody renders it (`render/cli` for a shell, `render/prose` for a caller that is not
 * one) and is never stored. `note` is the one kind that may name a tool, as `{tool}`.
 *
 * The wire strings (`set_env`, `text`, ...) are the same as the Python package's; the
 * language-neutral conformance pack under `conformance/` judges both.
 */

export const EXIT_OK = 0;
export const EXIT_ERROR = 1;
export const EXIT_USAGE = 2;

export const CLASSES = [
  "usage",
  "config",
  "transport",
  "auth",
  "permission",
  "not_found",
  "refused",
  "internal",
] as const;
export const CLASS_UNCLASSIFIED = "unclassified";

export type FaultClass = (typeof CLASSES)[number] | typeof CLASS_UNCLASSIFIED;

/**
 * The class `codes` declares for `code`, or `"unclassified"`.
 *
 * Fails closed on an unknown code rather than guessing from the error's type. A code is
 * looked up as an own key, so `"constructor"` is unclassified rather than an inherited member.
 */
export function faultClass(
  code: string | null | undefined,
  codes: Readonly<Record<string, string>> | ReadonlyMap<string, string>,
): string {
  const key = code ?? "";
  if (typeof (codes as ReadonlyMap<string, string>).get === "function") {
    return (codes as ReadonlyMap<string, string>).get(key) ?? CLASS_UNCLASSIFIED;
  }
  const table = codes as Readonly<Record<string, string>>;
  return Object.hasOwn(table, key) ? (table[key] as string) : CLASS_UNCLASSIFIED;
}

export const KINDS = ["run", "retry", "set_env", "choose", "note"] as const;
export type Kind = (typeof KINDS)[number];

export const TOOL_SLOT = "{tool}";

export const DEFAULT_RUN_LEAD = "Run";
export const DEFAULT_RETRY_LEAD = "Run the command again with";
export const DEFAULT_SEPARATOR = " ";

export interface RunRecovery {
  readonly kind: "run";
  /** The words after the tool's name. */
  readonly args: readonly string[];
  readonly purpose: string;
  readonly lead: string;
  readonly separator: string;
}
export interface RetryRecovery {
  readonly kind: "retry";
  readonly fragment: string;
  readonly purpose: string;
  readonly lead: string;
  readonly separator: string;
}
export interface SetEnvRecovery {
  readonly kind: "set_env";
  readonly variable: string;
  readonly describes: string;
  readonly example: string;
  readonly reference: string;
}
export interface ChooseRecovery {
  readonly kind: "choose";
  readonly label: string;
  readonly values: readonly string[];
}
export interface NoteRecovery {
  readonly kind: "note";
  readonly text: string;
}
export type Recovery = RunRecovery | RetryRecovery | SetEnvRecovery | ChooseRecovery | NoteRecovery;

/** A recovery that carries a trailing clause: the two kinds `withPurpose` applies to. */
export type PurposeRecovery = RunRecovery | RetryRecovery;

const FOREIGN_SLOT = /\{(?!tool\})[^}]*\}/;

export interface TailOptions {
  purpose?: string;
  lead?: string;
  separator?: string;
}

export function run(args: Iterable<string>, options: TailOptions = {}): RunRecovery {
  const words = [...args];
  if (words.length === 0) throw new Error("a run recovery names at least one argument");
  return Object.freeze({
    kind: "run",
    args: Object.freeze(words),
    purpose: options.purpose ?? "",
    lead: options.lead ?? DEFAULT_RUN_LEAD,
    separator: options.separator ?? DEFAULT_SEPARATOR,
  });
}

export function retry(fragment: string, options: TailOptions = {}): RetryRecovery {
  if (!fragment) throw new Error("a retry recovery names what to add");
  return Object.freeze({
    kind: "retry",
    fragment,
    purpose: options.purpose ?? "",
    lead: options.lead ?? DEFAULT_RETRY_LEAD,
    separator: options.separator ?? DEFAULT_SEPARATOR,
  });
}

export function setEnv(
  variable: string,
  describes: string,
  options: { example?: string; reference?: string } = {},
): SetEnvRecovery {
  if (!(variable && describes)) {
    throw new Error("a set_env recovery names a variable and what to set it to");
  }
  return Object.freeze({
    kind: "set_env",
    variable,
    describes,
    example: options.example ?? "",
    reference: options.reference ?? "",
  });
}

export function choose(label: string, values: Iterable<string>): ChooseRecovery {
  const list = [...values];
  if (!(label && list.length > 0)) {
    throw new Error("a choose recovery names a label and at least one value");
  }
  return Object.freeze({ kind: "choose", label, values: Object.freeze(list) });
}

/** Prose that is not a command. It may write `{tool}` and no other placeholder. */
export function note(text: string): NoteRecovery {
  if (!text) throw new Error("a note recovery carries text");
  if (FOREIGN_SLOT.test(text)) {
    throw new Error(
      `a note may write {tool} and no other placeholder; found one in ${JSON.stringify(text)}`,
    );
  }
  return Object.freeze({ kind: "note", text });
}

/** A copy of a `run` or `retry` carrying a different trailing clause. */
export function withPurpose<T extends PurposeRecovery>(recovery: T, purpose: string): T {
  if (recovery.kind !== "run" && recovery.kind !== "retry") {
    throw new Error(`${(recovery as Recovery).kind} recovery cannot carry 'purpose'`);
  }
  return Object.freeze({ ...recovery, purpose }) as unknown as T;
}

/**
 * Whether rendering this recovery will name a tool at all: every `run`, and a note that
 * writes `{tool}`.
 */
export function mentionsTool(recovery: Recovery): boolean {
  if (recovery.kind === "run") return true;
  if (recovery.kind === "note") return recovery.text.includes(TOOL_SLOT);
  return false;
}

const ALLOWED: Readonly<Record<Kind, readonly string[]>> = {
  run: ["args", "lead", "purpose", "separator"],
  retry: ["fragment", "lead", "purpose", "separator"],
  set_env: ["describes", "example", "reference", "variable"],
  choose: ["label", "values"],
  note: ["text"],
};

/** The fields whose absence means the factory default, not the empty string. */
const FACTORY_LEADS: Readonly<Record<string, string>> = {
  run: DEFAULT_RUN_LEAD,
  retry: DEFAULT_RETRY_LEAD,
};

/** A JSON-shaped object carrying exactly the fields this kind uses. */
export function recoveryToJSON(recovery: Recovery): Record<string, unknown> {
  const source = recovery as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = { kind: recovery.kind };
  for (const name of ALLOWED[recovery.kind]) {
    const value = source[name];
    const alwaysWritten = name === "lead";
    // Only the default separator is unset: an explicit empty one is a real value.
    const unset =
      name === "separator"
        ? value === DEFAULT_SEPARATOR
        : value === "" || (Array.isArray(value) && value.length === 0);
    if (unset && !alwaysWritten) continue;
    out[name] = Array.isArray(value) ? [...value] : value;
  }
  return out;
}

function stringField(data: Record<string, unknown>, name: string): string {
  const value = data[name];
  if (value === undefined) return "";
  if (typeof value !== "string")
    throw new Error(`recovery field ${JSON.stringify(name)} must be a string`);
  return value;
}

function listField(data: Record<string, unknown>, name: string): string[] {
  const value = data[name];
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw new Error(`recovery field ${JSON.stringify(name)} must be an array of strings`);
  }
  return [...value] as string[];
}

/**
 * Rebuild a recovery from its wire form, refusing a field the kind does not own.
 *
 * An absent `lead` on a `run` or `retry` takes the factory default rather than `""`;
 * the toJSON form always writes the lead of those two, so every recovery round-trips.
 */
export function recoveryFromJSON(data: unknown): Recovery {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new Error("a recovery is an object");
  }
  const record = data as Record<string, unknown>;
  const kind = record.kind;
  if (typeof kind !== "string" || !(KINDS as readonly string[]).includes(kind)) {
    throw new Error(`unknown recovery kind: ${JSON.stringify(kind)}`);
  }
  const allowed = ALLOWED[kind as Kind];
  for (const name of Object.keys(record)) {
    if (name !== "kind" && !allowed.includes(name)) {
      throw new Error(`${kind} recovery cannot carry ${JSON.stringify(name)}`);
    }
  }
  const lead = (): string =>
    record.lead === undefined ? (FACTORY_LEADS[kind] as string) : stringField(record, "lead");
  const tail = (): TailOptions => ({
    purpose: stringField(record, "purpose"),
    lead: lead(),
    separator:
      record.separator === undefined ? DEFAULT_SEPARATOR : stringField(record, "separator"),
  });
  switch (kind as Kind) {
    case "run":
      return run(listField(record, "args"), tail());
    case "retry":
      return retry(stringField(record, "fragment"), tail());
    case "set_env":
      return setEnv(stringField(record, "variable"), stringField(record, "describes"), {
        example: stringField(record, "example"),
        reference: stringField(record, "reference"),
      });
    case "choose":
      return choose(stringField(record, "label"), listField(record, "values"));
    case "note":
      return note(stringField(record, "text"));
  }
}

export interface AxiErrorOptions {
  recovery?: Iterable<Recovery>;
  code?: string | null;
  cause?: unknown;
}

/**
 * An error the agent should be able to read, understand and act on.
 *
 * `recovery` carries the next steps as data. `code` is a literal from the owning tool's
 * closed table, never a string built from what the server said. There is deliberately no
 * `helpLines`: rendered lines are what `render/*` produces once somebody knows which tool
 * is asking.
 */
export class AxiError extends Error {
  readonly exitCode: number = EXIT_ERROR;
  readonly code: string | null;
  readonly recovery: readonly Recovery[];

  constructor(message: string, options: AxiErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = new.target.name;
    this.code = options.code ?? null;
    this.recovery = Object.freeze([...(options.recovery ?? [])]);
  }

  faultClass(codes: Readonly<Record<string, string>> | ReadonlyMap<string, string>): string {
    return faultClass(this.code, codes);
  }

  /** The error as JSON-shaped data, recovery included and still unrendered. */
  toJSON(): { message: string; code: string; recovery: Record<string, unknown>[] } {
    return {
      message: this.message,
      code: this.code ?? "",
      recovery: this.recovery.map(recoveryToJSON),
    };
  }
}

/** A malformed invocation: unknown flag, missing argument, bad value. */
export class UsageError extends AxiError {
  override readonly exitCode: number = EXIT_USAGE;
}
/** Required environment configuration is missing or unusable. */
export class ConfigError extends AxiError {}
/** The system behind the tool could not be reached. */
export class ConnectionFailed extends AxiError {}
/** The credential was rejected. */
export class AuthFailed extends AxiError {}
/**
 * The credential was accepted and the caller was refused anyway. Deliberately neither an
 * `AuthFailed` nor an `ApiError`.
 */
export class Forbidden extends AxiError {}
/** The requested subject does not resolve to one thing that exists. */
export class NotFound extends AxiError {}
/** The system answered, and refused the request. */
export class ApiError extends AxiError {}
