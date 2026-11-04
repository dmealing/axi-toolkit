/**
 * Recovery intent, rendered as a sentence for a caller that is not a shell.
 *
 * The same recovery the CLI renderer turns into ``Run `hass-axi area list` to see each
 * area's id`` becomes ``To see each area's id, use hass-axi's `area list` command.``
 * Every sentence names the tool that owns the command; the name arrives as an argument.
 */

import { DEFAULT_RETRY_LEAD, DEFAULT_RUN_LEAD, type Recovery, TOOL_SLOT } from "../errors.js";
import { capitalise } from "../internal/pystr.js";

const TERMINATORS = ".!?:";

/** End the sentence, unless the author already did. */
function terminate(text: string): string {
  const last = text.slice(-1);
  return last !== "" && TERMINATORS.includes(last) ? text : `${text}.`;
}

/** The purpose clause, always joined with a plain space: prose owes nothing to the shell separator. */
function tail(purpose: string): string {
  return purpose ? ` ${purpose}` : "";
}

/** One recovery, as a sentence naming `tool`. */
export function sentence(recovery: Recovery, tool: string): string {
  switch (recovery.kind) {
    case "run": {
      const command = recovery.args.join(" ");
      if (recovery.lead !== DEFAULT_RUN_LEAD) {
        return terminate(
          `${capitalise(recovery.lead)} ${tool}'s \`${command}\`${tail(recovery.purpose)}`,
        );
      }
      if (recovery.purpose) {
        return terminate(`${capitalise(recovery.purpose)}, use ${tool}'s \`${command}\` command`);
      }
      return terminate(`Use ${tool}'s \`${command}\` command`);
    }
    case "retry":
      if (recovery.lead === DEFAULT_RETRY_LEAD) {
        return terminate(
          `Run the same ${tool} command again with \`${recovery.fragment}\`${tail(recovery.purpose)}`,
        );
      }
      return terminate(
        `${capitalise(recovery.lead)} \`${recovery.fragment}\`${tail(recovery.purpose)}, then run it again with ${tool}`,
      );
    case "set_env": {
      let out = `${tool} reads ${recovery.variable} from the environment: set it to ${recovery.describes}`;
      if (recovery.example) out += `, e.g. ${recovery.example}`;
      if (recovery.reference) out += `; see ${recovery.reference}`;
      return terminate(out);
    }
    case "choose":
      // No tool named: the values are the system's vocabulary, not the tool's.
      return terminate(`${capitalise(recovery.label)}: ${recovery.values.join(", ")}`);
    case "note":
      return terminate(recovery.text.replaceAll(TOOL_SLOT, tool));
  }
}

/** Every recovery in order, each as a sentence naming `tool`. */
export function sentences(recoveries: Iterable<Recovery>, tool: string): string[] {
  return [...recoveries].map((item) => sentence(item, tool));
}
