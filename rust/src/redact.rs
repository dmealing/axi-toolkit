//! The redaction boundary: register a secret, and get it back out of anything printed.
//!
//! A set of literal secrets, a list of credential *shapes*, and one function that removes both.
//! The shapes are not a fixed list: [`Redactor::register_pattern`] is how a tool adds its own,
//! and the order they run in is fixed and documented, because that order is observable.
//!
//! **The order is: literals, then the bearer header, then registered patterns, then the JWT.**
//! Literals go first and longest-first, so an overlapping pair (`user:password`) is replaced
//! whole rather than leaving a half-redacted fragment behind. The JWT rule goes last because it
//! replaces its whole match rather than keeping a prefix, and a rule that keeps a prefix should
//! have had its chance first. `conformance/redaction.json` pins the places the order is visible.
//!
//! # Patterns without a regex engine
//!
//! This crate has no regex dependency. The two built-in shapes are matched by hand, and a tool
//! registers its own as a [`Pattern`]: a function that finds the next match and says how much of
//! it to keep. [`Pattern::keyed`] covers the common shape (`prefix` then a run of value
//! characters); anything else is a closure over [`Pattern::new`]. A match keeps its prefix and
//! redacts the rest, which is how `X-Api-Token=abc123` becomes `X-Api-Token=<redacted>`:
//! the reader needs to know *which* credential was suppressed.
//!
//! Where the Python reference's regular expressions leave a character class engine-defined
//! (`\s`, `\b`), this crate follows Python: `\s` is [`char::is_whitespace`] plus U+001C to
//! U+001F, and a word character is alphanumeric or `_`.

use crate::pystr;
use std::sync::{Mutex, MutexGuard, OnceLock};

/// Placeholder substituted for anything that looks like a credential.
pub const REDACTED: &str = "<redacted>";

/// Below this length (in characters), redacting a literal does more damage than good: a short
/// string collides with ordinary words and would corrupt unrelated output. Lowered only for
/// values already known to be credentials by where they came from -- URL userinfo, say -- rather
/// than by their shape.
pub const MIN_SECRET_LENGTH: usize = 8;

/// One match of a [`Pattern`]: `start..end` is replaced, except that `start..keep` is kept
/// (the text of capture group 1, which always begins the match).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Match {
    /// Byte offset where the match begins.
    pub start: usize,
    /// Byte offset where the kept prefix ends; equal to `start` when nothing is kept.
    pub keep: usize,
    /// Byte offset where the match ends.
    pub end: usize,
}

type Finder = dyn Fn(&str, usize) -> Option<Match> + Send + Sync;

/// A credential shape: where the next match starts and how much of it survives.
pub struct Pattern {
    id: String,
    find: Box<Finder>,
}

impl std::fmt::Debug for Pattern {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Pattern").field("id", &self.id).finish()
    }
}

impl Pattern {
    /// A pattern from a finder: given the text and a byte offset on a character boundary, the
    /// leftmost [`Match`] starting at or after that offset. `id` names the shape (its regular
    /// expression source, say); registering the same `id` twice is a no-op.
    pub fn new(
        id: impl Into<String>,
        find: impl Fn(&str, usize) -> Option<Match> + Send + Sync + 'static,
    ) -> Pattern {
        Pattern {
            id: id.into(),
            find: Box::new(find),
        }
    }

    /// The shape's identity.
    pub fn id(&self) -> &str {
        &self.id
    }

    /// One of `prefixes` (compared ASCII case-insensitively) followed by at least `min_len`
    /// characters satisfying `accept`, as many as there are. The prefix is kept, the value is
    /// redacted -- the shape of `([?&]token=)[A-Za-z0-9._~-]{8,}`.
    pub fn keyed(
        id: impl Into<String>,
        prefixes: &[&str],
        min_len: usize,
        accept: impl Fn(char) -> bool + Send + Sync + 'static,
    ) -> Pattern {
        let prefixes: Vec<String> = prefixes.iter().map(|p| (*p).to_string()).collect();
        Pattern::new(id, move |text, from| {
            for (start, _) in text[from..].char_indices().map(|(i, c)| (i + from, c)) {
                for prefix in &prefixes {
                    let tail = &text.as_bytes()[start..];
                    if tail.len() < prefix.len()
                        || !tail[..prefix.len()].eq_ignore_ascii_case(prefix.as_bytes())
                    {
                        continue;
                    }
                    let keep = start + prefix.len();
                    if let Some(end) = run_end(text, keep, min_len, &accept) {
                        return Some(Match { start, keep, end });
                    }
                }
            }
            None
        })
    }
}

/// The end of a run of at least `min` characters satisfying `accept` that starts at `from`.
fn run_end(text: &str, from: usize, min: usize, accept: &dyn Fn(char) -> bool) -> Option<usize> {
    let mut count = 0;
    let mut end = from;
    for c in text[from..].chars() {
        if !accept(c) {
            break;
        }
        count += 1;
        end += c.len_utf8();
    }
    (count >= min).then_some(end)
}

/// `[A-Za-z0-9._~-]`: the alphabet of the tokens several services issue.
pub fn is_token_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '~' | '-')
}

/// `[^&\s"'<>]`: a query-string value up to the next separator.
pub fn is_query_value_char(c: char) -> bool {
    !(c == '&' || pystr::is_space(c) || matches!(c, '"' | '\'' | '<' | '>'))
}

fn is_word(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Whether a `\b` sits immediately before the character at byte `at`, which is a word character.
fn boundary_before(text: &str, at: usize) -> bool {
    !text[..at].chars().next_back().is_some_and(is_word)
}

/// `(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}`
fn find_bearer(text: &str, from: usize) -> Option<Match> {
    for (start, _) in text[from..].char_indices().map(|(i, c)| (i + from, c)) {
        let tail = &text.as_bytes()[start..];
        if tail.len() < 6
            || !tail[..6].eq_ignore_ascii_case(b"bearer")
            || !boundary_before(text, start)
        {
            continue;
        }
        let after = start + 6;
        let spaces = text[after..].chars().take_while(|c| pystr::is_space(*c));
        let space_len: usize = spaces.map(char::len_utf8).sum();
        if space_len == 0 {
            continue;
        }
        let keep = after + space_len;
        let alphabet = |c: char| {
            c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '~' | '+' | '/' | '=' | '-')
        };
        if let Some(end) = run_end(text, keep, 8, &alphabet) {
            return Some(Match { start, keep, end });
        }
    }
    None
}

/// `\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}`
fn find_jwt(text: &str, from: usize) -> Option<Match> {
    let segment = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-';
    for (start, _) in text[from..].char_indices().map(|(i, c)| (i + from, c)) {
        if !text[start..].starts_with("eyJ") || !boundary_before(text, start) {
            continue;
        }
        let Some(first) = run_end(text, start + 3, 4, &segment) else {
            continue;
        };
        if !text[first..].starts_with('.') {
            continue;
        }
        let Some(second) = run_end(text, first + 1, 4, &segment) else {
            continue;
        };
        if !text[second..].starts_with('.') {
            continue;
        }
        if let Some(end) = run_end(text, second + 1, 4, &segment) {
            return Some(Match {
                start,
                keep: start,
                end,
            });
        }
    }
    None
}

/// Replace every match of `find`, keeping each match's prefix.
fn apply(text: &str, find: &dyn Fn(&str, usize) -> Option<Match>) -> String {
    let mut out = String::with_capacity(text.len());
    let (mut last, mut from) = (0, 0);
    while from <= text.len() {
        let Some(m) = find(text, from) else { break };
        out.push_str(&text[last..m.start]);
        out.push_str(&text[m.start..m.keep]);
        out.push_str(REDACTED);
        last = m.end;
        from = if m.end > m.start {
            m.end
        } else {
            m.end + text[m.end..].chars().next().map_or(1, char::len_utf8)
        };
    }
    out.push_str(&text[last..]);
    out
}

/// A set of literal secrets and credential shapes, and the filter over them.
///
/// A struct rather than only module state so a test can hold one in isolation, and so a caller
/// embedding two tools at once can keep their shapes apart. The module-level functions operate
/// on one shared instance, which is what a CLI wants.
#[derive(Debug, Default)]
pub struct Redactor {
    secrets: Vec<String>,
    patterns: Vec<Pattern>,
}

impl Redactor {
    /// An empty redactor: the built-in bearer and JWT shapes only.
    pub fn new() -> Redactor {
        Redactor::default()
    }

    /// Register a literal string that must never reach stdout or stderr. A value shorter than
    /// `min_length` characters, or empty, is ignored.
    pub fn register_secret(&mut self, value: &str, min_length: usize) {
        if !value.is_empty()
            && value.chars().count() >= min_length
            && !self.secrets.iter().any(|s| s == value)
        {
            self.secrets.push(value.to_string());
        }
    }

    /// Drop registered literals, keeping registered shapes.
    pub fn reset_secrets(&mut self) {
        self.secrets.clear();
    }

    /// Register a credential shape this caller's system produces. Registering the same
    /// [`Pattern::id`] twice is a no-op, so a module initialised twice does not double the work.
    pub fn register_pattern(&mut self, pattern: Pattern) {
        if self.patterns.iter().all(|p| p.id != pattern.id) {
            self.patterns.push(pattern);
        }
    }

    /// The identity of each registered shape, in the order they run.
    pub fn registered_patterns(&self) -> Vec<&str> {
        self.patterns.iter().map(|p| p.id.as_str()).collect()
    }

    /// Drop literals and shapes both.
    pub fn reset(&mut self) {
        self.secrets.clear();
        self.patterns.clear();
    }

    /// Whether `text` contains a registered literal.
    pub fn contains_secret(&self, text: &str) -> bool {
        self.secrets.iter().any(|s| text.contains(s.as_str()))
    }

    /// Remove credentials from `text` by literal match and by shape.
    pub fn redact(&self, text: &str) -> String {
        let mut secrets: Vec<&String> = self.secrets.iter().collect();
        secrets.sort_by(|a, b| {
            b.chars()
                .count()
                .cmp(&a.chars().count())
                .then_with(|| a.cmp(b))
        });
        let mut text = text.to_string();
        for secret in secrets {
            text = text.replace(secret.as_str(), REDACTED);
        }
        text = apply(&text, &find_bearer);
        for pattern in &self.patterns {
            text = apply(&text, pattern.find.as_ref());
        }
        apply(&text, &find_jwt)
    }
}

/// The instance a CLI uses: one process, one output boundary, one set of secrets.
fn shared() -> MutexGuard<'static, Redactor> {
    static SHARED: OnceLock<Mutex<Redactor>> = OnceLock::new();
    SHARED
        .get_or_init(|| Mutex::new(Redactor::new()))
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Register a literal on the shared redactor, at least [`MIN_SECRET_LENGTH`] characters long.
pub fn register_secret(value: &str) {
    shared().register_secret(value, MIN_SECRET_LENGTH);
}

/// Register a literal on the shared redactor with its own minimum length.
pub fn register_secret_min(value: &str, min_length: usize) {
    shared().register_secret(value, min_length);
}

/// Register one shape on the shared redactor.
pub fn register_pattern(pattern: Pattern) {
    shared().register_pattern(pattern);
}

/// The shapes registered on the shared redactor, in the order they run.
pub fn registered_patterns() -> Vec<String> {
    shared()
        .registered_patterns()
        .into_iter()
        .map(String::from)
        .collect()
}

/// Whether `text` contains a literal registered on the shared redactor.
pub fn contains_secret(text: &str) -> bool {
    shared().contains_secret(text)
}

/// Remove credentials from `text` using the shared redactor.
pub fn redact(text: &str) -> String {
    shared().redact(text)
}

/// Drop the shared redactor's literals.
pub fn reset_secrets() {
    shared().reset_secrets();
}

/// Drop the shared redactor's literals and shapes.
pub fn reset() {
    shared().reset();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn jwt() -> String {
        // Assembled at run time so no credential-shaped literal sits in the source.
        ["ey", "Jhbgc", ".", "eyJzdWIx", ".", "c2lnbmF0"].concat() // leakcheck: allow=jwt
    }

    #[test]
    fn a_bearer_header_keeps_its_prefix() {
        let r = Redactor::new();
        assert_eq!(
            r.redact("Authorization: Bearer abcdef123456"),
            "Authorization: Bearer <redacted>"
        );
        assert_eq!(r.redact("bearer short"), "bearer short");
        assert_eq!(r.redact("notbearer abcdef123456"), "notbearer abcdef123456");
    }

    #[test]
    fn a_jwt_is_replaced_whole() {
        let r = Redactor::new();
        assert_eq!(
            r.redact(&format!("leaked {} here", jwt())),
            "leaked <redacted> here"
        );
    }

    #[test]
    fn literals_go_longest_first() {
        let mut r = Redactor::new();
        r.register_secret("someone:example-secret", 4);
        r.register_secret("example-secret", 4);
        assert_eq!(
            r.redact("pair is someone:example-secret"),
            "pair is <redacted>"
        );
        r.register_secret("abc", 8);
        assert_eq!(r.redact("abc def"), "abc def");
    }

    #[test]
    fn a_registered_shape_keeps_its_prefix_and_runs_before_the_jwt_rule() {
        let mut r = Redactor::new();
        r.register_pattern(Pattern::keyed(
            "q",
            &["?token=", "&token="],
            1,
            is_query_value_char,
        ));
        r.register_pattern(Pattern::keyed("q", &["?x="], 1, is_query_value_char));
        assert_eq!(r.registered_patterns(), ["q"]);
        assert_eq!(
            r.redact("http://h/s?token=bearer abcdef123456"),
            "http://h/s?token=<redacted> <redacted>"
        );
        assert_eq!(
            r.redact(&format!("http://h/s?token=ab.{}", jwt())),
            "http://h/s?token=<redacted>"
        );
        assert_eq!(
            r.redact("http://h/s?TOKEN=abcdefgh1"),
            "http://h/s?TOKEN=<redacted>"
        );
    }
}
