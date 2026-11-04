/**
 * Recovery intent, rendered for a shell.
 *
 * `line` is the renderer that has to be exactly right: the bytes it emits are held to the
 * conformance pack. `parse` is its inverse, the migration aid that turns a tool's existing
 * literal into intent, and what lets the byte-for-byte claim cover a whole corpus.
 *
 * The tool's name enters here and nowhere earlier. A parsed intent that still contains the
 * name anywhere but the command it names is kept as prose with a `{tool}` slot.
 */

import {
  DEFAULT_SEPARATOR,
  note,
  type Recovery,
  retry,
  run,
  setEnv,
  TOOL_SLOT,
} from "../errors.js";
import { isBlank, pySplit } from "../internal/pystr.js";

const EXAMPLE = ", e.g. ";
const REFERENCE = "; see ";

// `.` must not cross "\n" and nothing else, as in Python: `[^\n]` rather than `.`.
const SET_ENV = /^Set ([A-Z][A-Z0-9_]*) to ([^\n]+)$/;
// The first backtick-delimited span on the line, and what sits either side of it.
const BACKTICKED = /^([^`]*)`([^`]*)`(.*)$/s;

function withTail(head: string, recovery: { purpose: string; separator: string }): string {
  if (recovery.purpose || recovery.separator !== DEFAULT_SEPARATOR) {
    return `${head}${recovery.separator}${recovery.purpose}`;
  }
  return head;
}

/** One recovery, as the line `tool` would print. */
export function line(recovery: Recovery, tool: string): string {
  switch (recovery.kind) {
    case "run":
      return withTail(`${recovery.lead} \`${[tool, ...recovery.args].join(" ")}\``, recovery);
    case "retry":
      return withTail(`${recovery.lead} \`${recovery.fragment}\``, recovery);
    case "set_env": {
      let out = `Set ${recovery.variable} to ${recovery.describes}`;
      if (recovery.example) out += `${EXAMPLE}${recovery.example}`;
      if (recovery.reference) out += `${REFERENCE}${recovery.reference}`;
      return out;
    }
    case "choose":
      return `${recovery.label}: ${recovery.values.join(", ")}`;
    case "note":
      return recovery.text.replaceAll(TOOL_SLOT, () => tool);
  }
}

/** Every recovery in order, as the lines `tool` would print. */
export function lines(recoveries: Iterable<Recovery>, tool: string): string[] {
  return [...recoveries].map((item) => line(item, tool));
}

function rpartition(text: string, separator: string): [string, string] {
  const index = text.lastIndexOf(separator);
  return [text.slice(0, index), text.slice(index + separator.length)];
}

function parseSetEnv(text: string): Recovery | null {
  const match = SET_ENV.exec(text);
  if (match === null) return null;
  const variable = match[1] as string;
  let rest = match[2] as string;
  let example = "";
  let reference = "";
  // Each spelling is looked for once, from the right.
  if (rest.includes(REFERENCE)) [rest, reference] = rpartition(rest, REFERENCE);
  if (rest.includes(EXAMPLE)) [rest, example] = rpartition(rest, EXAMPLE);
  if (rest === "") return null;
  return setEnv(variable, rest, { example, reference });
}

/** Divide what follows the closing backtick into a separator and a purpose. */
function splitTail(rest: string): [string, string] {
  if (rest === "") return [DEFAULT_SEPARATOR, ""];
  const index = rest.indexOf(" ");
  if (index === -1) return [rest, ""];
  return [rest.slice(0, index + 1), rest.slice(index + 1)];
}

function parseBackticked(text: string, tool: string): Recovery | null {
  const match = BACKTICKED.exec(text);
  if (match === null) return null;
  const [, lead = "", body = "", rest = ""] = match;
  // `foo` at the very start of a line, or glued to the preceding word: prose.
  if (!lead.endsWith(" ")) return null;
  const [separator, purpose] = splitTail(rest);
  const options = { purpose, lead: lead.slice(0, -1), separator };
  if (body === tool || body.startsWith(`${tool} `)) {
    const args = pySplit(body.slice(tool.length));
    if (args.length === 0) return null;
    return run(args, options);
  }
  if (body === "") return null;
  return retry(body, options);
}

/**
 * Whether the tool's name survives anywhere it would be baked in. A `run` may name the
 * tool in the command it names; anywhere else a literal name would make the intent belong
 * to one tool forever. Exactly these four fields are checked, as in the Python package.
 */
function namesToolOutsideCommand(recovery: Recovery, tool: string): boolean {
  const fields: string[] = [];
  if (recovery.kind === "run" || recovery.kind === "retry")
    fields.push(recovery.lead, recovery.purpose);
  if (recovery.kind === "retry") fields.push(recovery.fragment);
  if (recovery.kind === "set_env") fields.push(recovery.describes);
  return fields.some((value) => value.includes(tool));
}

/**
 * The intent that renders back to `text` for `tool`. Prose that fits no structured kind
 * becomes a note with the tool's name replaced by `{tool}`. An empty line throws.
 */
export function parse(text: string, tool: string): Recovery {
  if (isBlank(text)) throw new Error("an empty line is not a recovery");
  const structured = parseSetEnv(text) ?? parseBackticked(text, tool);
  if (structured !== null && !namesToolOutsideCommand(structured, tool)) return structured;
  return note(text.replaceAll(tool, () => TOOL_SLOT));
}

export function parseAll(texts: Iterable<string>, tool: string): Recovery[] {
  return [...texts].map((text) => parse(text, tool));
}
