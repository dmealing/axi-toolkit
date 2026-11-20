//! Recovery intent, rendered for a shell.
//!
//! This is the renderer that has to be exactly right: a tool's own suite asserts its help and
//! recovery text, so a line that reads *slightly* differently is a diff those suites fail on.
//! `conformance/recovery.json` holds it to account against every literal recovery line two
//! source tools emit, byte for byte, and [`parse`] -- the inverse -- is what makes that claim
//! cover the whole corpus.
//!
//! The one rule that governs both directions: **the tool's name enters here and nowhere
//! earlier.** A parsed intent that still contains the name anywhere but the command it names is
//! kept as prose with a `{tool}` slot, so the resulting intent is one a sibling tool could
//! render as its own.

use crate::errors::{Recovery, RecoveryError, TOOL_SLOT};
use crate::pystr;

const DEFAULT_SEPARATOR: &str = " ";
const EXAMPLE: &str = ", e.g. ";
const REFERENCE: &str = "; see ";

/// One recovery, as the line `tool` would print.
pub fn line(recovery: &Recovery, tool: &str) -> String {
    match recovery {
        Recovery::Run {
            args,
            purpose,
            lead,
            separator,
        } => {
            let mut command = String::from(tool);
            for a in args {
                command.push(' ');
                command.push_str(a);
            }
            with_tail(format!("{lead} `{command}`"), purpose, separator)
        }
        Recovery::Retry {
            fragment,
            purpose,
            lead,
            separator,
        } => with_tail(format!("{lead} `{fragment}`"), purpose, separator),
        Recovery::SetEnv {
            variable,
            describes,
            example,
            reference,
        } => {
            let mut out = format!("Set {variable} to {describes}");
            if !example.is_empty() {
                out.push_str(EXAMPLE);
                out.push_str(example);
            }
            if !reference.is_empty() {
                out.push_str(REFERENCE);
                out.push_str(reference);
            }
            out
        }
        Recovery::Choose { label, values } => format!("{label}: {}", values.join(", ")),
        Recovery::Note { text } => text.replace(TOOL_SLOT, tool),
    }
}

/// Every recovery in order, as the lines `tool` would print.
pub fn lines(recoveries: &[Recovery], tool: &str) -> Vec<String> {
    recoveries.iter().map(|r| line(r, tool)).collect()
}

/// Append the trailing clause, if this recovery has one. The separator is carried rather than
/// assumed because the tools use two (a space, and `": "`), and it is appended whenever it is not
/// the default even with an empty purpose, which is what lets a line ending in bare punctuation
/// round-trip.
fn with_tail(head: String, purpose: &str, separator: &str) -> String {
    if !purpose.is_empty() || separator != DEFAULT_SEPARATOR {
        format!("{head}{separator}{purpose}")
    } else {
        head
    }
}

/// The intent that renders back to `text` for `tool`.
///
/// Succeeds for any line a tool would actually print: prose that fits no structured kind becomes
/// a note carrying the same bytes with the tool's name replaced by [`TOOL_SLOT`].
///
/// # Errors
/// A blank line, because an empty suggestion is worse than none -- it occupies the slot that
/// should have held the fix -- and prose that writes a `{...}` placeholder a note may not.
pub fn parse(text: &str, tool: &str) -> Result<Recovery, RecoveryError> {
    if pystr::is_blank(text) {
        return Err(RecoveryError("an empty line is not a recovery".into()));
    }
    let structured = parse_set_env(text).or_else(|| parse_backticked(text, tool));
    if let Some(r) = structured {
        if !names_tool_outside_command(&r, tool) {
            return Ok(r);
        }
    }
    let replaced = text.replace(tool, TOOL_SLOT);
    crate::errors::Recovery::from_value(&crate::toon::Value::object([
        ("kind", "note"),
        ("text", replaced.as_str()),
    ]))
}

/// [`parse`] over several lines.
///
/// # Errors
/// The first line [`parse`] refuses.
pub fn parse_all(texts: &[String], tool: &str) -> Result<Vec<Recovery>, RecoveryError> {
    texts.iter().map(|t| parse(t, tool)).collect()
}

/// `Set <VAR> to <describes>`, with the two trailing spellings the source tools use.
fn parse_set_env(text: &str) -> Option<Recovery> {
    let rest = text.strip_prefix("Set ")?;
    let var_len = {
        let mut chars = rest.char_indices();
        match chars.next() {
            Some((_, c)) if c.is_ascii_uppercase() => {}
            _ => return None,
        }
        chars
            .find(|(_, c)| !(c.is_ascii_uppercase() || c.is_ascii_digit() || *c == '_'))
            .map_or(rest.len(), |(i, _)| i)
    };
    let variable = &rest[..var_len];
    let mut rest = rest[var_len..].strip_prefix(" to ")?;
    if rest.is_empty() || rest.contains('\n') {
        return None;
    }
    let (mut example, mut reference) = ("", "");
    // Each spelling is looked for once, from the right: a reference is a URL and may itself
    // contain ", e.g. " in no realistic case, while a describes clause routinely contains a comma.
    if let Some((head, tail)) = rest.rsplit_once(REFERENCE) {
        rest = head;
        reference = tail;
    }
    if let Some((head, tail)) = rest.rsplit_once(EXAMPLE) {
        rest = head;
        example = tail;
    }
    if rest.is_empty() {
        return None;
    }
    Some(Recovery::SetEnv {
        variable: variable.into(),
        describes: rest.into(),
        example: example.into(),
        reference: reference.into(),
    })
}

/// The first backtick-delimited span on the line, and what sits either side of it.
fn parse_backticked(text: &str, tool: &str) -> Option<Recovery> {
    let open = text.find('`')?;
    let close = open + 1 + text[open + 1..].find('`')?;
    let (lead, body, rest) = (&text[..open], &text[open + 1..close], &text[close + 1..]);
    // `foo` at the very start of a line, or one glued to the preceding word: no lead clause to
    // carry, so this is prose rather than a suggestion to run.
    let lead = lead.strip_suffix(' ')?;
    let (separator, purpose) = split_tail(rest);
    if body == tool || body.strip_prefix(tool).is_some_and(|r| r.starts_with(' ')) {
        let args: Vec<String> = pystr::split(&body[tool.len()..])
            .into_iter()
            .map(String::from)
            .collect();
        if args.is_empty() {
            return None;
        }
        return Some(Recovery::Run {
            args,
            purpose: purpose.into(),
            lead: lead.into(),
            separator: separator.into(),
        });
    }
    if body.is_empty() {
        return None;
    }
    Some(Recovery::Retry {
        fragment: body.into(),
        purpose: purpose.into(),
        lead: lead.into(),
        separator: separator.into(),
    })
}

/// Divide what follows the closing backtick into a separator and a purpose.
fn split_tail(rest: &str) -> (&str, &str) {
    if rest.is_empty() {
        return (DEFAULT_SEPARATOR, "");
    }
    match rest.find(' ') {
        None => (rest, ""),
        Some(i) => (&rest[..=i], &rest[i + 1..]),
    }
}

/// Whether the tool's name survives anywhere it would be baked in. A `run` may name the tool in
/// the command it names; anywhere else a literal name would make the intent belong to one tool
/// forever.
fn names_tool_outside_command(recovery: &Recovery, tool: &str) -> bool {
    let values: Vec<&str> = match recovery {
        Recovery::Run { lead, purpose, .. } => vec![lead, purpose],
        Recovery::Retry {
            fragment,
            purpose,
            lead,
            ..
        } => vec![lead, purpose, fragment],
        Recovery::SetEnv { describes, .. } => vec![describes],
        Recovery::Choose { .. } => vec![],
        Recovery::Note { text } => vec![text],
    };
    values.into_iter().any(|v| v.contains(tool))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_run_renders_with_the_callers_name() {
        let r = Recovery::run(["area", "list"]).with_purpose("to see each area's id");
        assert_eq!(line(&r, "t1"), "Run `t1 area list` to see each area's id");
        assert_eq!(line(&r, "t2"), "Run `t2 area list` to see each area's id");
    }

    #[test]
    fn parse_is_the_inverse_of_line() {
        for text in [
            "Run `example-axi doctor`.",
            "Raise the limit with `example-axi --timeout 60 <command>`",
            "Run the command again with `--limit 50`",
            "Set HA_URL to your base URL, e.g. export HA_URL=https://host.example.com",
            "Retry the command; a dropped connection is often a one-off",
            " `--x`",
        ] {
            let r = parse(text, "example-axi").unwrap();
            assert_eq!(line(&r, "example-axi"), text);
        }
        assert!(parse("  ", "t").is_err());
    }

    #[test]
    fn prose_that_names_the_tool_keeps_a_slot() {
        let r = parse("usage: example-axi [command]", "example-axi").unwrap();
        assert_eq!(r, Recovery::note("usage: {tool} [command]"));
    }
}
