//! The few places where a Rust string built-in and its Python counterpart differ. The rendering
//! contract and the conformance pack were written against Python, so these reproduce Python.

/// Python's `str.isspace()` for one character: Unicode White_Space plus U+001C to U+001F.
pub(crate) fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `text.strip() == ""`.
pub(crate) fn is_blank(text: &str) -> bool {
    text.chars().all(is_space)
}

/// `text.strip()`.
pub(crate) fn strip(text: &str) -> &str {
    text.trim_matches(is_space)
}

/// `text.split()`: runs of whitespace separate; leading and trailing ones vanish.
pub(crate) fn split(text: &str) -> Vec<&str> {
    text.split(is_space).filter(|w| !w.is_empty()).collect()
}

/// `text[:1].upper() + text[1:]`.
pub(crate) fn capitalise(text: &str) -> String {
    let mut chars = text.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => String::new(),
    }
}

/// Whether Python's `str.isprintable` rejects `c`. Unassigned code points cannot be told apart
/// from assigned ones without a Unicode table, so those print as themselves.
fn not_printable(c: char) -> bool {
    c != ' '
        && (c.is_control()
            || c.is_whitespace()
            || matches!(c,
                '\u{ad}' | '\u{600}'..='\u{605}' | '\u{61c}' | '\u{6dd}' | '\u{70f}'
                | '\u{200b}'..='\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2060}'..='\u{2064}'
                | '\u{2066}'..='\u{206f}' | '\u{feff}' | '\u{fff9}'..='\u{fffb}'
                | '\u{e000}'..='\u{f8ff}' | '\u{f0000}'..='\u{10ffff}')
            || (c as u32 & 0xfffe) == 0xfffe)
}

/// `repr(text)`: single quotes unless the text holds a `'` and no `"`; the backslash, the quote
/// and `\n \r \t` escaped; a non-printable character as `\xNN`, `\uNNNN` or `\UNNNNNNNN`.
pub(crate) fn repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::from(quote);
    for c in text.chars() {
        match c {
            c if c == quote || c == '\\' => {
                out.push('\\');
                out.push(c);
            }
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if not_printable(c) => {
                let code = c as u32;
                if code < 0x100 {
                    out.push_str(&format!("\\x{code:02x}"));
                } else if code < 0x10000 {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    out.push_str(&format!("\\U{code:08x}"));
                }
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn whitespace_includes_the_information_separators() {
        assert!(is_space('\u{1c}'));
        assert!(is_space('\u{a0}'));
        assert!(!is_space('x'));
        assert_eq!(split(" a\u{1f}b  c "), vec!["a", "b", "c"]);
        assert!(is_blank(" \n\u{85}"));
    }

    #[test]
    fn repr_follows_python() {
        assert_eq!(repr("https://"), "'https://'");
        assert_eq!(repr("it's"), "\"it's\"");
        assert_eq!(repr("a'b\"c"), "'a\\'b\"c'");
        assert_eq!(repr("a\nb\u{1}"), "'a\\nb\\x01'");
    }

    #[test]
    fn capitalise_leaves_the_rest_alone() {
        assert_eq!(capitalise("HA_URL x"), "HA_URL x");
        assert_eq!(capitalise("to see"), "To see");
        assert_eq!(capitalise(""), "");
    }
}
