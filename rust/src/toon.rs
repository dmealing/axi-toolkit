//! A strict, std-only encoder for TOON (Token-Oriented Object Notation).
//!
//! TOON is the wire format every AXI CLI prints on stdout. The encoder covers objects, inline
//! primitive arrays, tabular arrays, keyed tabular objects and list form for the JSON data
//! model, and follows spec v4.4 in its default [`Dialect::Spec`]. Encoding happens at the output
//! boundary only: command logic stays on plain data and builds a [`Value`] at the end.
//!
//! The encoder was lifted from the downstream Rust prototype and brought level with the Python
//! `axi_toolkit.toon` module, which is the byte-for-byte reference (`tests/differential.rs`
//! compares the two on generated inputs).
//!
//! ```
//! use axi_toolkit::toon::{encode, Value};
//!
//! let doc = Value::Object(vec![
//!     ("count".into(), Value::Int(2)),
//!     ("tags".into(), Value::Array(vec!["a".into(), "b c".into()])),
//! ]);
//! assert_eq!(encode(&doc), "count: 2\ntags[2]: a,b c");
//! ```

/// A JSON-shaped value. Object keys keep insertion order.
///
/// Integers are `i64`; a larger integer must be passed as [`Value::Num`] or [`Value::Str`].
/// An object holding the same key twice encodes both entries and is not a JSON object: do not
/// build one.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    /// JSON `null`.
    Null,
    /// JSON `true` / `false`.
    Bool(bool),
    /// A JSON number written without a fraction or exponent.
    Int(i64),
    /// Any other JSON number. Non-finite values encode as `null`.
    Num(f64),
    /// A JSON string.
    Str(String),
    /// A JSON array.
    Array(Vec<Value>),
    /// A JSON object, as ordered entries.
    Object(Vec<(String, Value)>),
}

impl From<&str> for Value {
    fn from(s: &str) -> Value {
        Value::Str(s.to_string())
    }
}

impl From<String> for Value {
    fn from(s: String) -> Value {
        Value::Str(s)
    }
}

impl From<bool> for Value {
    fn from(b: bool) -> Value {
        Value::Bool(b)
    }
}

impl From<i64> for Value {
    fn from(n: i64) -> Value {
        Value::Int(n)
    }
}

impl From<f64> for Value {
    fn from(n: f64) -> Value {
        Value::Num(n)
    }
}

impl<T: Into<Value>> From<Vec<T>> for Value {
    fn from(items: Vec<T>) -> Value {
        Value::Array(items.into_iter().map(Into::into).collect())
    }
}

impl<T: Into<Value>> From<Option<T>> for Value {
    fn from(v: Option<T>) -> Value {
        v.map_or(Value::Null, Into::into)
    }
}

impl Value {
    /// An object from `(key, value)` pairs, in the order given.
    pub fn object<K: Into<String>, V: Into<Value>>(
        entries: impl IntoIterator<Item = (K, V)>,
    ) -> Value {
        Value::Object(
            entries
                .into_iter()
                .map(|(k, v)| (k.into(), v.into()))
                .collect(),
        )
    }

    /// The value stored under `key` when this is an object.
    pub fn get(&self, key: &str) -> Option<&Value> {
        match self {
            Value::Object(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }
}

/// Delimiter used between array values and tabular cells.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Delimiter {
    /// `,` — the default, spelled by omission in a bracket segment.
    Comma,
    /// A tab.
    Tab,
    /// `|`.
    Pipe,
}

impl Delimiter {
    /// The delimiter character.
    pub fn ch(self) -> char {
        match self {
            Delimiter::Comma => ',',
            Delimiter::Tab => '\t',
            Delimiter::Pipe => '|',
        }
    }

    /// The delimiter named by its character (`","`, `"\t"` or `"|"`).
    pub fn from_symbol(s: &str) -> Option<Delimiter> {
        match s {
            "," => Some(Delimiter::Comma),
            "\t" => Some(Delimiter::Tab),
            "|" => Some(Delimiter::Pipe),
            _ => None,
        }
    }

    /// The symbol shown inside a bracket segment; comma is spelled by omission.
    fn symbol(self) -> &'static str {
        match self {
            Delimiter::Comma => "",
            Delimiter::Tab => "\t",
            Delimiter::Pipe => "|",
        }
    }
}

/// Which encoder's rules to follow where they differ.
///
/// The spec's own rules and the ones the `@toon-format/toon` 2.3.x library ships differ in a
/// few places, and a tool that must print what that library prints needs the second set.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Dialect {
    /// Spec v4.4 and the Python `axi_toolkit.toon` module: a string starting with `#` is quoted,
    /// a leading `+` makes a string numeric-like, padding means a space or tab, and a float
    /// outside the canonical decimal range prints with Python's exponent form (`1e-07`).
    #[default]
    Spec,
    /// `@toon-format/toon` 2.3.x: `#` is not special, `+1` is not numeric-like, padding is
    /// anything JavaScript's `String.prototype.trim` strips, and an exponent has no zero padding
    /// (`1e-7`).
    ToonJs2,
}

/// Encoder options.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Options {
    /// Spaces per nesting level.
    pub indent: usize,
    /// The document delimiter, declared on every header the encoder emits.
    pub delimiter: Delimiter,
    /// Which dialect's quoting and number rules apply.
    pub dialect: Dialect,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            indent: 2,
            delimiter: Delimiter::Comma,
            dialect: Dialect::Spec,
        }
    }
}

/// JavaScript's `\s` set, which `String.prototype.trim` strips.
pub fn is_js_space(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{b}' | '\u{c}' | '\r' | ' ' | '\u{a0}' | '\u{1680}' | '\u{2000}'
            ..='\u{200a}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202f}'
                | '\u{205f}'
                | '\u{3000}'
                | '\u{feff}'
    )
}

/// Encode with default options. No trailing newline.
pub fn encode(value: &Value) -> String {
    encode_with(value, &Options::default())
}

/// Encode with explicit options. No trailing newline.
pub fn encode_with(value: &Value, opts: &Options) -> String {
    Encoder { opts: *opts }.root(value).join("\n")
}

/// Encode one primitive as it would appear as a field value (comma delimiter).
/// Non-primitives encode as `null`.
pub fn encode_scalar(value: &Value) -> String {
    encode_scalar_with(value, &Options::default())
}

/// [`encode_scalar`] with explicit options.
pub fn encode_scalar_with(value: &Value, opts: &Options) -> String {
    Encoder { opts: *opts }.primitive(value)
}

/// Header columns: a name plus, for a nested-uniform column, its own columns.
type Fields = Vec<Field>;

struct Field {
    name: String,
    nested: Option<Fields>,
}

fn is_primitive(v: &Value) -> bool {
    !matches!(v, Value::Array(_) | Value::Object(_))
}

fn lookup<'a>(obj: &'a [(String, Value)], name: &str) -> &'a Value {
    obj.iter()
        .find(|(k, _)| k == name)
        .map(|(_, v)| v)
        .unwrap_or(&Value::Null)
}

fn is_bare_key(s: &str) -> bool {
    let mut chars = s.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => {}
        _ => return false,
    }
    chars.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '.')
}

/// Section 7.2: would this string be read back as a number?
fn is_numeric_like(s: &str, dialect: Dialect) -> bool {
    let b = s.as_bytes();
    let mut i = 0;
    let signs: &[u8] = match dialect {
        Dialect::Spec => b"+-",
        Dialect::ToonJs2 => b"-",
    };
    if i < b.len() && signs.contains(&b[i]) {
        i += 1;
    }
    let digits = |i: &mut usize| {
        let start = *i;
        while *i < b.len() && b[*i].is_ascii_digit() {
            *i += 1;
        }
        *i > start
    };
    if !digits(&mut i) {
        return false;
    }
    if i < b.len() && b[i] == b'.' {
        i += 1;
        if !digits(&mut i) {
            return false;
        }
    }
    if i < b.len() && (b[i] == b'e' || b[i] == b'E') {
        i += 1;
        if i < b.len() && (b[i] == b'+' || b[i] == b'-') {
            i += 1;
        }
        if !digits(&mut i) {
            return false;
        }
    }
    i == b.len()
}

fn quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Section 2: canonical decimal form for 0 and 1e-6 <= |x| < 1e21; exponent form outside.
fn format_number(v: f64, dialect: Dialect) -> String {
    if !v.is_finite() {
        return "null".to_string();
    }
    if v == 0.0 {
        return "0".to_string();
    }
    let a = v.abs();
    if (1e-6..1e21).contains(&a) {
        // An integral value prints as its exact integer, as the Python reference does
        // (`str(int(v))`): Display would pad the shortest digits with zeros instead, which
        // differs from the exact value from 2^53 up (2^63 is 9223372036854775808, not
        // ...776000). |v| < 1e21 < 2^70, so the i128 conversion is exact.
        // The JavaScript dialect keeps the shortest digits (`String(2**63)` is
        // `9223372036854776000`), so only the Spec dialect takes this branch.
        if dialect == Dialect::Spec && v.fract() == 0.0 {
            #[allow(clippy::cast_possible_truncation)]
            return (v as i128).to_string();
        }
        // Otherwise Display prints the shortest round-tripping digits and never an exponent.
        return format!("{v}");
    }
    // Exponent notation is permitted outside the canonical range. Rust prints `1.5e-7`; the
    // Python reference prints a signed exponent of at least two digits (`1.5e-07`, `1e+22`),
    // JavaScript a signed one with no padding (`1.5e-7`, `1e+22`).
    let s = format!("{v:e}");
    let Some((mantissa, exp)) = s.split_once('e') else {
        return s;
    };
    let (sign, digits) = match exp.strip_prefix('-') {
        Some(d) => ('-', d),
        None => ('+', exp),
    };
    match dialect {
        Dialect::Spec => format!("{mantissa}e{sign}{digits:0>2}"),
        Dialect::ToonJs2 => format!("{mantissa}e{sign}{digits}"),
    }
}

struct Encoder {
    opts: Options,
}

impl Encoder {
    fn delim(&self) -> char {
        self.opts.delimiter.ch()
    }

    fn pad(&self, depth: usize) -> String {
        " ".repeat(self.opts.indent * depth)
    }

    fn primitive(&self, v: &Value) -> String {
        match v {
            Value::Null => "null".into(),
            Value::Bool(true) => "true".into(),
            Value::Bool(false) => "false".into(),
            Value::Int(i) => i.to_string(),
            Value::Num(n) => format_number(*n, self.opts.dialect),
            Value::Str(s) => self.string(s),
            _ => "null".into(),
        }
    }

    fn string(&self, s: &str) -> String {
        if self.needs_quote(s) {
            quote(s)
        } else {
            s.to_string()
        }
    }

    fn needs_quote(&self, s: &str) -> bool {
        let padded = match self.opts.dialect {
            Dialect::Spec => s.starts_with([' ', '\t']) || s.ends_with([' ', '\t']),
            Dialect::ToonJs2 => s.starts_with(is_js_space) || s.ends_with(is_js_space),
        };
        let hash = self.opts.dialect == Dialect::Spec && s.starts_with('#');
        s.is_empty()
            || padded
            || matches!(s, "true" | "false" | "null")
            || is_numeric_like(s, self.opts.dialect)
            || s.chars().any(|c| {
                matches!(c, ':' | '"' | '\\' | '[' | ']' | '{' | '}')
                    || (c as u32) < 0x20
                    || c == self.delim()
            })
            || hash
            || s.starts_with('-')
    }

    fn key(&self, name: &str) -> String {
        if is_bare_key(name) {
            name.to_string()
        } else {
            quote(name)
        }
    }

    fn bracket(&self, len: usize, keyed: bool) -> String {
        let marker = if keyed {
            format!("{len}:")
        } else {
            len.to_string()
        };
        format!("[{marker}{}]", self.opts.delimiter.symbol())
    }

    fn field_list(&self, fields: &Fields) -> String {
        let d = self.delim().to_string();
        fields
            .iter()
            .map(|f| match &f.nested {
                None => self.key(&f.name),
                Some(n) => format!("{}{{{}}}", self.key(&f.name), self.field_list(n)),
            })
            .collect::<Vec<_>>()
            .join(&d)
    }

    fn tabular_fields(&self, items: &[&Value]) -> Option<Fields> {
        if items.is_empty() {
            return None;
        }
        let mut objs = Vec::with_capacity(items.len());
        for item in items {
            match item {
                Value::Object(o) if !o.is_empty() => objs.push(o),
                _ => return None,
            }
        }
        let first = objs[0];
        let same_keys = |o: &[(String, Value)]| {
            o.len() == first.len()
                && o.iter().all(|(k, _)| first.iter().any(|(k2, _)| k2 == k))
                && first.iter().all(|(k, _)| o.iter().any(|(k2, _)| k2 == k))
        };
        if !objs.iter().all(|o| same_keys(o)) {
            return None;
        }
        let mut fields = Fields::new();
        for (name, _) in first {
            let column: Vec<&Value> = objs.iter().map(|o| lookup(o, name)).collect();
            if column.iter().all(|v| is_primitive(v)) {
                fields.push(Field {
                    name: name.clone(),
                    nested: None,
                });
            } else {
                fields.push(Field {
                    name: name.clone(),
                    nested: Some(self.tabular_fields(&column)?),
                });
            }
        }
        Some(fields)
    }

    fn keyed_fields(&self, obj: &[(String, Value)]) -> Option<Fields> {
        if obj.len() < 2 {
            return None;
        }
        let vals: Vec<&Value> = obj.iter().map(|(_, v)| v).collect();
        self.tabular_fields(&vals)
    }

    fn cells(&self, obj: &[(String, Value)], fields: &Fields, out: &mut Vec<String>) {
        for f in fields {
            let v = lookup(obj, &f.name);
            match (&f.nested, v) {
                (None, v) => out.push(self.primitive(v)),
                (Some(n), Value::Object(o)) => self.cells(o, n, out),
                _ => {}
            }
        }
    }

    fn row(&self, v: &Value, fields: &Fields) -> String {
        let mut cells = Vec::new();
        if let Value::Object(o) = v {
            self.cells(o, fields, &mut cells);
        }
        cells.join(&self.delim().to_string())
    }

    fn keyed_block(
        &self,
        head_prefix: &str,
        obj: &[(String, Value)],
        fields: &Fields,
        depth: usize,
    ) -> Vec<String> {
        let mut lines = vec![format!(
            "{head_prefix}{}{{{}}}:",
            self.bracket(obj.len(), true),
            self.field_list(fields)
        )];
        for (k, v) in obj {
            lines.push(format!(
                "{}{}: {}",
                self.pad(depth + 1),
                self.key(k),
                self.row(v, fields)
            ));
        }
        lines
    }

    fn root(&self, v: &Value) -> Vec<String> {
        match v {
            Value::Object(o) => {
                if o.is_empty() {
                    return Vec::new();
                }
                if let Some(f) = self.keyed_fields(o) {
                    return self.keyed_block("", o, &f, 0);
                }
                self.object_body(o, 0)
            }
            Value::Array(a) => self.array(None, a, 0, true),
            // Section 7.2: a root primitive starting with U+FEFF is quoted, or a reader would
            // strip it as a byte-order mark. Only the root: elsewhere it is content.
            Value::Str(s) if s.starts_with('\u{feff}') => vec![quote(s)],
            _ => vec![self.primitive(v)],
        }
    }

    fn object_body(&self, obj: &[(String, Value)], depth: usize) -> Vec<String> {
        obj.iter()
            .flat_map(|(k, v)| self.field(k, v, depth))
            .collect()
    }

    fn field(&self, name: &str, v: &Value, depth: usize) -> Vec<String> {
        let pad = self.pad(depth);
        let key = self.key(name);
        match v {
            Value::Array(a) => self.array(Some(&key), a, depth, true),
            Value::Object(o) => {
                if o.is_empty() {
                    return vec![format!("{pad}{key}:")];
                }
                if let Some(f) = self.keyed_fields(o) {
                    return self.keyed_block(&format!("{pad}{key}"), o, &f, depth);
                }
                let mut lines = vec![format!("{pad}{key}:")];
                lines.extend(self.object_body(o, depth + 1));
                lines
            }
            _ => vec![format!("{pad}{key}: {}", self.primitive(v))],
        }
    }

    fn array(
        &self,
        key: Option<&str>,
        items: &[Value],
        depth: usize,
        allow_tabular: bool,
    ) -> Vec<String> {
        let pad = self.pad(depth);
        let prefix = key.unwrap_or("");
        if items.is_empty() {
            return vec![match key {
                Some(k) => format!("{pad}{k}: []"),
                None => format!("{pad}[]"),
            }];
        }
        let bracket = self.bracket(items.len(), false);
        if items.iter().all(is_primitive) {
            let vals: Vec<String> = items.iter().map(|i| self.primitive(i)).collect();
            return vec![format!(
                "{pad}{prefix}{bracket}: {}",
                vals.join(&self.delim().to_string())
            )];
        }
        if allow_tabular {
            let refs: Vec<&Value> = items.iter().collect();
            if let Some(fields) = self.tabular_fields(&refs) {
                let mut lines = vec![format!(
                    "{pad}{prefix}{bracket}{{{}}}:",
                    self.field_list(&fields)
                )];
                for item in items {
                    lines.push(format!(
                        "{}{}",
                        self.pad(depth + 1),
                        self.row(item, &fields)
                    ));
                }
                return lines;
            }
        }
        let mut lines = vec![format!("{pad}{prefix}{bracket}:")];
        for item in items {
            lines.extend(self.list_item(item, depth + 1));
        }
        lines
    }

    fn list_item(&self, v: &Value, depth: usize) -> Vec<String> {
        let pad = self.pad(depth);
        match v {
            Value::Array(a) => {
                if a.is_empty() {
                    return vec![format!("{pad}- {}:", self.bracket(0, false))];
                }
                self.hyphenate(self.array(None, a, depth, false), depth, depth)
            }
            Value::Object(o) => {
                let Some((first, first_v)) = o.first() else {
                    return vec![format!("{pad}-")];
                };
                let mut lines =
                    self.hyphenate(self.field(first, first_v, depth + 1), depth, depth + 1);
                for (k, val) in &o[1..] {
                    lines.extend(self.field(k, val, depth + 1));
                }
                lines
            }
            _ => vec![format!("{pad}- {}", self.primitive(v))],
        }
    }

    /// Move the first line onto a `- ` marker at `marker_depth`.
    fn hyphenate(&self, lines: Vec<String>, marker_depth: usize, head_depth: usize) -> Vec<String> {
        let mut it = lines.into_iter();
        let head = it.next().unwrap_or_default();
        let rest = &head[self.pad(head_depth).len()..];
        let mut out = vec![format!("{}- {rest}", self.pad(marker_depth))];
        out.extend(it);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(x: &str) -> String {
        encode_scalar(&Value::Str(x.into()))
    }

    fn js(s: &str) -> String {
        let opts = Options {
            dialect: Dialect::ToonJs2,
            ..Options::default()
        };
        encode_scalar_with(&Value::Str(s.to_string()), &opts)
    }

    #[test]
    fn large_integral_floats_print_as_exact_integers_like_python() {
        let n = |v: f64| encode_scalar(&Value::Num(v));
        assert_eq!(n(9_007_199_254_740_992.0), "9007199254740992");
        assert_eq!(n(9_007_199_254_740_994.0), "9007199254740994");
        assert_eq!(n(1e16), "10000000000000000");
        assert_eq!(n(2f64.powi(63)), "9223372036854775808");
        assert_eq!(n(-2f64.powi(63)), "-9223372036854775808");
        assert_eq!(n(1e20), "100000000000000000000");
        assert_eq!(n(9.999_999_999_999_998e20), "999999999999999737856");
        assert_eq!(n(1e21), "1e+21");
        assert_eq!(n(-1e21), "-1e+21");
        assert_eq!(n(f64::MAX), "1.7976931348623157e+308");
        assert_eq!(n(f64::MIN), "-1.7976931348623157e+308");
        assert_eq!(n(-0.0), "0");
    }

    #[test]
    fn the_js_dialect_keeps_shortest_digits_for_large_integral_floats() {
        let opts = Options {
            dialect: Dialect::ToonJs2,
            ..Options::default()
        };
        let n = |v: f64| encode_scalar_with(&Value::Num(v), &opts);
        assert_eq!(n(2f64.powi(63)), "9223372036854776000");
        assert_eq!(n(1e20), "100000000000000000000");
    }

    #[test]
    fn plain_strings_stay_bare() {
        assert_eq!(s("hello world"), "hello world");
        assert_eq!(s("a-b"), "a-b");
        assert_eq!(s("é"), "é");
    }

    #[test]
    fn reserved_and_numeric_like_are_quoted() {
        for v in [
            "", "true", "false", "null", "42", "-3.5", "1e5", "+7", "1E-2",
        ] {
            assert_eq!(s(v), format!("\"{v}\""), "{v}");
        }
        assert_eq!(s("1.2.3"), "1.2.3");
        assert_eq!(s("1."), "1.");
    }

    #[test]
    fn structural_and_edge_chars_are_quoted() {
        assert_eq!(s("a:b"), "\"a:b\"");
        assert_eq!(s(" x"), "\" x\"");
        assert_eq!(s("x "), "\"x \"");
        assert_eq!(s("-x"), "\"-x\"");
        assert_eq!(s("#x"), "\"#x\"");
        assert_eq!(s("a,b"), "\"a,b\"");
        assert_eq!(s("[x]"), "\"[x]\"");
        assert_eq!(s("a\nb"), "\"a\\nb\"");
        assert_eq!(s("a\u{1}b"), "\"a\\u0001b\"");
        assert_eq!(s("q\"b\\"), "\"q\\\"b\\\\\"");
    }

    #[test]
    fn delimiter_quoting_is_delimiter_aware() {
        let v = Value::Array(vec!["a|b".into(), "c,d".into()]);
        let o = Options {
            delimiter: Delimiter::Pipe,
            ..Options::default()
        };
        assert_eq!(encode_with(&v, &o), "[2|]: \"a|b\"|c,d");
    }

    #[test]
    fn keys_quote_unless_bare() {
        let v = Value::object([("ok_key.1", 1), ("a b", 2), ("1x", 3)]);
        assert_eq!(encode(&v), "ok_key.1: 1\n\"a b\": 2\n\"1x\": 3");
    }

    #[test]
    fn numbers() {
        let n = |x: f64| encode_scalar(&Value::Num(x));
        assert_eq!(n(1.0), "1");
        assert_eq!(n(-0.0), "0");
        assert_eq!(n(1.5), "1.5");
        assert_eq!(n(1e-6), "0.000001");
        assert_eq!(n(1e20), "100000000000000000000");
        assert_eq!(n(1e21), "1e+21");
        assert_eq!(n(1e-7), "1e-07");
        assert_eq!(n(1.5e-10), "1.5e-10");
        assert_eq!(n(1.25e300), "1.25e+300");
        assert_eq!(n(f64::NAN), "null");
        assert_eq!(n(f64::INFINITY), "null");
        assert_eq!(encode_scalar(&Value::Int(-5)), "-5");
    }

    #[test]
    fn the_js_dialect_does_not_pad_the_exponent() {
        let opts = Options {
            dialect: Dialect::ToonJs2,
            ..Options::default()
        };
        assert_eq!(encode_scalar_with(&Value::Num(1e-7), &opts), "1e-7");
        assert_eq!(encode_scalar_with(&Value::Num(1e21), &opts), "1e+21");
    }

    #[test]
    fn empty_object_root_is_empty() {
        assert_eq!(encode(&Value::Object(vec![])), "");
    }

    #[test]
    fn a_root_string_starting_with_a_bom_is_quoted() {
        assert_eq!(encode(&Value::Str("\u{feff}8".into())), "\"\u{feff}8\"");
        assert_eq!(encode(&Value::object([("k", "\u{feff}x")])), "k: \u{feff}x");
    }

    #[test]
    fn the_js_library_does_not_quote_a_leading_hash_or_plus_number() {
        assert_eq!(js("## Intent"), "## Intent");
        assert_eq!(js("+1"), "+1");
        assert_eq!(s("#x"), "\"#x\"");
        assert_eq!(s("+1"), "\"+1\"");
    }

    #[test]
    fn the_js_library_pads_with_every_trimmed_character() {
        assert_eq!(js("\u{a0}x"), "\"\u{a0}x\"");
        assert_eq!(js("x\u{feff}"), "\"x\u{feff}\"");
        assert_eq!(js("\u{85}x"), "\u{85}x");
    }
}
