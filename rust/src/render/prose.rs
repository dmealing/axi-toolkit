//! Recovery intent, rendered as a sentence for a caller that is not a shell.
//!
//! The same [`Recovery`] the CLI renderer turns into ``Run `example-axi area list` to see each
//! area's id`` becomes, here, ``To see each area's id, use example-axi's `area list` command.`` --
//! the form a caller embedding this crate wants when it has to tell a person, or a model, what
//! went wrong and what to do about it. A programmatic caller cannot run the shell line, and
//! handing it one invites it to claim it did; a sentence naming the tool says who owns the fix
//! without implying the caller is about to execute it.

use crate::errors::{Recovery, TOOL_SLOT};
use crate::pystr;

const DEFAULT_RUN_LEAD: &str = "Run";
const DEFAULT_RETRY_LEAD: &str = "Run the command again with";
const TERMINATORS: &str = ".!?:";

/// One recovery, as a sentence naming `tool`.
pub fn sentence(recovery: &Recovery, tool: &str) -> String {
    match recovery {
        Recovery::Run {
            args,
            purpose,
            lead,
            ..
        } => {
            let command = args.join(" ");
            if lead != DEFAULT_RUN_LEAD {
                return terminate(format!(
                    "{} {tool}'s `{command}`{}",
                    pystr::capitalise(lead),
                    tail(purpose)
                ));
            }
            if !purpose.is_empty() {
                return terminate(format!(
                    "{}, use {tool}'s `{command}` command",
                    pystr::capitalise(purpose)
                ));
            }
            terminate(format!("Use {tool}'s `{command}` command"))
        }
        Recovery::Retry {
            fragment,
            purpose,
            lead,
            ..
        } => {
            if lead == DEFAULT_RETRY_LEAD {
                return terminate(format!(
                    "Run the same {tool} command again with `{fragment}`{}",
                    tail(purpose)
                ));
            }
            terminate(format!(
                "{} `{fragment}`{}, then run it again with {tool}",
                pystr::capitalise(lead),
                tail(purpose)
            ))
        }
        Recovery::SetEnv {
            variable,
            describes,
            example,
            reference,
        } => {
            let mut out =
                format!("{tool} reads {variable} from the environment: set it to {describes}");
            if !example.is_empty() {
                out.push_str(&format!(", e.g. {example}"));
            }
            if !reference.is_empty() {
                out.push_str(&format!("; see {reference}"));
            }
            terminate(out)
        }
        // No tool named: the values are the system's vocabulary, not the tool's.
        Recovery::Choose { label, values } => terminate(format!(
            "{}: {}",
            pystr::capitalise(label),
            values.join(", ")
        )),
        Recovery::Note { text } => terminate(text.replace(TOOL_SLOT, tool)),
    }
}

/// Every recovery in order, each as a sentence naming `tool`.
pub fn sentences(recoveries: &[Recovery], tool: &str) -> Vec<String> {
    recoveries.iter().map(|r| sentence(r, tool)).collect()
}

/// The purpose clause, always joined with a plain space: the CLI renderer carries the source
/// tool's own separator so it can reproduce a line byte for byte, but prose is writing a new
/// sentence, and a colon that bound an explanation to a shell command reads as a stray one here.
fn tail(purpose: &str) -> String {
    if purpose.is_empty() {
        String::new()
    } else {
        format!(" {purpose}")
    }
}

/// End the sentence, unless the author already did (or there is no sentence).
fn terminate(text: String) -> String {
    match text.chars().last() {
        None => text,
        Some(c) if TERMINATORS.contains(c) => text,
        Some(_) => text + ".",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_run_with_a_purpose_leads_with_it() {
        let r = Recovery::run(["area", "list"]).with_purpose("to see each area's id");
        assert_eq!(
            sentence(&r, "example-axi"),
            "To see each area's id, use example-axi's `area list` command."
        );
    }

    #[test]
    fn a_choice_names_no_tool() {
        let r = Recovery::choose("did you mean", ["a", "b"]);
        assert_eq!(sentence(&r, "x"), "Did you mean: a, b.");
    }
}
