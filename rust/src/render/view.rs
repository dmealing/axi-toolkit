//! The documents a tool prints on stdout: labelled rows and records, help lines, error blocks.
//!
//! Lifted from the downstream prototype's view module and made generic. Everything here
//! produces TOON through [`crate::toon`], with the [`Options`] (and so the [`Dialect`]) of the
//! [`Views`] that renders it; a tool that must print what the `@toon-format/toon` library prints
//! picks [`Dialect::ToonJs2`].
//!
//! The error block is the stdout half of the error contract: `error:` (the message), `code:`
//! when the error has one, and `help[N]:` carrying the rendered recovery lines.

use crate::errors::AxiError;
use crate::render::cli;
use crate::toon::{self, Dialect, Options, Value};

/// Shorten `text` to `limit` UTF-16 code units and say how much was lost and how to get it back.
///
/// Counts UTF-16 units, as a JavaScript `String.prototype.length` does, so a tool that replaces
/// a JavaScript one truncates at the same place. A cut between the halves of a surrogate pair
/// leaves what a JavaScript program's stdout would carry: U+FFFD.
pub fn truncate(text: &str, limit: usize, hint: &str) -> String {
    if text.is_empty() {
        return String::new();
    }
    let len = utf16_len(text);
    if len <= limit {
        return text.to_string();
    }
    format!(
        "{}\n... (truncated, {len} chars total - {hint})",
        slice_utf16(text, limit)
    )
}

/// `String.prototype.length`: the number of UTF-16 code units.
pub fn utf16_len(s: &str) -> usize {
    s.chars().map(char::len_utf16).sum()
}

/// `String.prototype.slice(0, n)` for text a JavaScript program then writes as UTF-8.
pub fn slice_utf16(s: &str, n: usize) -> String {
    let mut out = String::new();
    let mut units = 0;
    for c in s.chars() {
        let w = c.len_utf16();
        if units + w > n {
            if units < n {
                out.push('\u{FFFD}');
            }
            break;
        }
        out.push(c);
        units += w;
    }
    out
}

/// A renderer bound to one set of encoder options.
#[derive(Debug, Clone, Copy, Default)]
pub struct Views {
    /// The encoder options every block is rendered with.
    pub options: Options,
}

impl Views {
    /// Views that render with `options`.
    pub fn new(options: Options) -> Views {
        Views { options }
    }

    /// Views in the `@toon-format/toon` 2.3.x dialect.
    pub fn toon_js() -> Views {
        Views::new(Options {
            dialect: Dialect::ToonJs2,
            ..Options::default()
        })
    }

    fn encode(&self, value: &Value) -> String {
        toon::encode_with(value, &self.options)
    }

    /// A labelled array of rows: `label[N]{cols}:` then one line per row. Each row is a list
    /// of `(column, value)` pairs.
    pub fn list(&self, label: &str, rows: Vec<Value>) -> String {
        self.encode(&Value::Object(vec![(
            label.to_string(),
            Value::Array(rows),
        )]))
    }

    /// One labelled record.
    pub fn detail(&self, label: &str, record: Value) -> String {
        self.encode(&Value::Object(vec![(label.to_string(), record)]))
    }

    /// `label: text`.
    pub fn scalar(&self, label: &str, text: &str) -> String {
        self.encode(&Value::Object(vec![(label.to_string(), Value::from(text))]))
    }

    /// Suggestions as a one-item-per-line array (`help[N]:` then `  - item` lines), or nothing.
    pub fn help(&self, lines: &[String]) -> String {
        if lines.is_empty() {
            return String::new();
        }
        let items: Vec<String> = lines
            .iter()
            .map(|l| {
                format!(
                    "  - {}",
                    toon::encode_scalar_with(&Value::from(l.as_str()), &self.options)
                )
            })
            .collect();
        format!("help[{}]:\n{}", lines.len(), items.join("\n"))
    }

    /// The error block: `error`, `code` when there is one, and `help` when there is recovery,
    /// rendered for `tool`.
    pub fn error(&self, error: &AxiError, tool: &str) -> String {
        let mut fields = vec![("error".to_string(), Value::from(error.message.as_str()))];
        if let Some(code) = error.code.as_deref().filter(|c| !c.is_empty()) {
            fields.push(("code".to_string(), Value::from(code)));
        }
        let help = cli::lines(&error.recovery, tool);
        if !help.is_empty() {
            fields.push(("help".to_string(), Value::from(help)));
        }
        self.encode(&Value::Object(fields))
    }
}

/// The non-empty blocks, one per line group, joined by a newline.
pub fn output(blocks: Vec<String>) -> String {
    blocks
        .into_iter()
        .filter(|b| !b.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::errors::Recovery;

    #[test]
    fn truncation_names_the_size_and_the_escape_hatch() {
        let text = "x".repeat(90);
        assert_eq!(
            truncate(&text, 80, "use --full"),
            format!(
                "{}\n... (truncated, 90 chars total - use --full)",
                "x".repeat(80)
            )
        );
        assert_eq!(truncate("short", 80, "h"), "short");
        assert_eq!(truncate("", 80, "h"), "");
    }

    #[test]
    fn lengths_count_utf16_units_and_a_split_pair_leaves_the_replacement_character() {
        assert_eq!(utf16_len("a\u{1F600}b"), 4);
        assert_eq!(slice_utf16("ab\u{1F600}c", 3), "ab\u{FFFD}");
        assert_eq!(slice_utf16("ab\u{1F600}c", 4), "ab\u{1F600}");
    }

    #[test]
    fn rows_become_a_tabular_array() {
        let rows = vec![
            Value::object([("id", Value::from("a")), ("n", Value::from(1))]),
            Value::object([("id", Value::from("b")), ("n", Value::from(2))]),
        ];
        assert_eq!(
            Views::default().list("items", rows),
            "items[2]{id,n}:\n  a,1\n  b,2"
        );
    }

    #[test]
    fn the_error_block_carries_the_message_the_code_and_the_help() {
        let e = AxiError::not_found("no such thing")
            .with_code("NOT_FOUND")
            .and_recover(Recovery::run(["list"]).with_purpose("to see what exists"));
        assert_eq!(
            Views::default().error(&e, "tool"),
            "error: no such thing\ncode: NOT_FOUND\nhelp[1]: Run `tool list` to see what exists"
        );
        let bare = AxiError::general("boom");
        assert_eq!(Views::default().error(&bare, "tool"), "error: boom");
    }

    #[test]
    fn help_is_a_one_item_per_line_array() {
        let v = Views::default();
        assert_eq!(v.help(&[]), "");
        assert_eq!(
            v.help(&["a".into(), "b, c".into()]),
            "help[2]:\n  - a\n  - \"b, c\""
        );
        assert_eq!(output(vec!["a".into(), String::new(), "b".into()]), "a\nb");
    }
}
