//! The flag helpers every tool's parser needs, as real code.
//!
//! These are the semantics of the downstream prototype's embedded helpers, unchanged: a flag's
//! value may be `--flag value` or `--flag=value`; a value that begins with `--` is refused (use
//! `=`); only the first occurrence of a flag is read and removed; whatever starts with `-` and
//! is left over is an unknown flag. Every failure is a usage error (exit status 2) whose recovery
//! is data.

use super::spec::{FlagKind, FlagSpec, FlagValue};
use crate::errors::{AxiError, Recovery, TOOL_SLOT};
use crate::toon::is_js_space;

/// The largest integer a JavaScript number holds exactly; the limit of [`parse_optional_uint`].
pub const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

/// `String.prototype.trim`.
pub fn js_trim(s: &str) -> &str {
    s.trim_matches(is_js_space)
}

fn note(text: impl Into<String>) -> Recovery {
    // Built directly: a note may only write the tool slot, and flag names may carry anything.
    Recovery::Note { text: text.into() }
}

/// The value after the flag at `args[index]`, which must exist and must not begin with `--`.
///
/// # Errors
/// A usage error asking for `--flag=value` when the value is absent or looks like a flag.
pub fn require_flag_value(args: &[String], index: usize, flag: &str) -> Result<String, AxiError> {
    match args.get(index + 1) {
        Some(v) if !v.starts_with("--") => Ok(v.clone()),
        _ => Err(AxiError::usage(format!("{flag} requires a value"))
            .and_recover(note(format!("Pass {flag}=... if the value begins with --")))),
    }
}

/// `--flag value` or `--flag=value`: the first occurrence, removed from `args`.
///
/// # Errors
/// As [`require_flag_value`].
pub fn take_flag(args: &mut Vec<String>, flag: &str) -> Result<Option<String>, AxiError> {
    let equals = format!("{flag}=");
    for i in 0..args.len() {
        if args[i] == flag {
            let value = require_flag_value(args, i, flag)?;
            args.drain(i..i + 2);
            return Ok(Some(value));
        }
        if let Some(value) = args[i].strip_prefix(equals.as_str()) {
            let value = value.to_string();
            args.remove(i);
            return Ok(Some(value));
        }
    }
    Ok(None)
}

/// A switch: whether it is present, its first occurrence removed from `args`.
pub fn take_bool_flag(args: &mut Vec<String>, flag: &str) -> bool {
    match args.iter().position(|a| a == flag) {
        Some(i) => {
            args.remove(i);
            true
        }
        None => false,
    }
}

/// A value that is not blank (by JavaScript's `trim`).
///
/// # Errors
/// A usage error when `value` is present and blank.
pub fn require_non_empty_flag_value(
    flag: &str,
    value: Option<String>,
) -> Result<Option<String>, AxiError> {
    match value {
        Some(v) if js_trim(&v).is_empty() => {
            Err(AxiError::usage(format!("{flag} requires a value"))
                .and_recover(note(format!("Pass {flag}=... with a non-empty value"))))
        }
        other => Ok(other),
    }
}

/// A value that is not blank and holds no line break.
///
/// # Errors
/// A usage error when `value` is present and blank, or holds `\r` or `\n`.
pub fn require_non_empty_single_line(
    flag: &str,
    value: Option<String>,
) -> Result<Option<String>, AxiError> {
    match require_non_empty_flag_value(flag, value)? {
        Some(v) if v.contains(['\r', '\n']) => {
            Err(AxiError::usage(format!("{flag} must be a single line"))
                .and_recover(note(format!("Pass {flag}=... without line breaks"))))
        }
        other => Ok(other),
    }
}

/// A non-negative integer of ASCII digits no larger than [`MAX_SAFE_INTEGER`].
///
/// # Errors
/// A usage error for anything else (a sign, a fraction, an exponent, a blank).
pub fn parse_optional_uint(flag: &str, raw: Option<String>) -> Result<Option<u64>, AxiError> {
    let Some(raw) = raw else { return Ok(None) };
    let bad = || AxiError::usage(format!("{flag} must be a non-negative integer"));
    if raw.is_empty() || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return Err(bad());
    }
    match raw.parse::<u64>() {
        Ok(n) if n <= MAX_SAFE_INTEGER => Ok(Some(n)),
        _ => Err(bad()),
    }
}

/// One of `allowed`.
///
/// # Errors
/// A usage error naming the allowed words.
pub fn parse_choice(flag: &str, raw: &str, allowed: &[&str]) -> Result<String, AxiError> {
    if allowed.contains(&raw) {
        Ok(raw.to_string())
    } else {
        Err(AxiError::usage(format!(
            "{flag} must be one of {}",
            allowed.join(", ")
        )))
    }
}

/// A comma-separated list of names from `available`: blanks and repeats dropped, order kept.
///
/// # Errors
/// A usage error naming the unknown names and the sorted available ones.
pub fn parse_columns(
    flag: &str,
    raw: Option<String>,
    available: &[&str],
) -> Result<Vec<String>, AxiError> {
    let _ = flag;
    let Some(raw) = raw else {
        return Ok(Vec::new());
    };
    let mut requested: Vec<String> = Vec::new();
    for part in raw.split(',') {
        let name = js_trim(part);
        if !name.is_empty() && !requested.iter().any(|r| r == name) {
            requested.push(name.to_string());
        }
    }
    let unknown: Vec<&str> = requested
        .iter()
        .map(String::as_str)
        .filter(|n| !available.contains(n))
        .collect();
    if unknown.is_empty() {
        return Ok(requested);
    }
    let mut names: Vec<&str> = available.to_vec();
    names.sort_unstable();
    Err(AxiError::usage(format!(
        "Unknown field(s): {}. Available: {}",
        unknown.join(", "),
        names.join(", ")
    )))
}

/// Refuse any argument that still looks like a flag.
///
/// # Errors
/// A usage error naming the first one.
pub fn require_no_unknown_flags(args: &[String]) -> Result<(), AxiError> {
    match args.iter().find(|a| a.starts_with('-')) {
        Some(unknown) => Err(AxiError::usage(format!("Unknown flag: {unknown}"))
            .and_recover(note("Run the command with --help to see supported flags"))),
        None => Ok(()),
    }
}

/// The positional arguments, between `min` and `max` of them. `usage` is the usage text after the
/// tool's name; it is offered back as a note that renders with the caller's own name.
///
/// # Errors
/// A usage error for an unknown flag or the wrong number of positionals.
pub fn require_positionals(
    args: &[String],
    min: usize,
    max: usize,
    usage: &str,
) -> Result<Vec<String>, AxiError> {
    require_no_unknown_flags(args)?;
    let positionals: Vec<String> = args
        .iter()
        .filter(|a| !a.starts_with('-'))
        .cloned()
        .collect();
    if positionals.len() >= min && positionals.len() <= max {
        return Ok(positionals);
    }
    let plural = |n: usize| if n == 1 { "" } else { "s" };
    let expected = if min == max {
        if min == 0 {
            "no positional arguments".to_string()
        } else {
            format!("{min} positional argument{}", plural(min))
        }
    } else {
        format!("{min}-{max} positional arguments")
    };
    Err(
        AxiError::usage(format!("Expected {expected}, got {}", positionals.len()))
            .and_recover(note(format!("usage: {TOOL_SLOT} {usage}"))),
    )
}

/// Validate one flag's raw value against its declared kind.
///
/// # Errors
/// Whatever the kind's helper refuses.
pub fn parse_value(spec: &FlagSpec, raw: String) -> Result<FlagValue, AxiError> {
    Ok(match spec.kind {
        FlagKind::Bool => FlagValue::Bool(true),
        FlagKind::Text => FlagValue::Text(
            require_non_empty_single_line(spec.name, Some(raw))?.unwrap_or_default(),
        ),
        FlagKind::Uint => {
            FlagValue::Uint(parse_optional_uint(spec.name, Some(raw))?.unwrap_or_default())
        }
        FlagKind::Choice(words) => FlagValue::Choice(parse_choice(spec.name, &raw, words)?),
        FlagKind::Columns(available) => {
            FlagValue::Columns(parse_columns(spec.name, Some(raw), available)?)
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn take_flag_reads_both_spellings_and_removes_the_first() {
        let mut a = v(&["x", "--repo", "r", "--repo=s"]);
        assert_eq!(take_flag(&mut a, "--repo").unwrap(), Some("r".into()));
        assert_eq!(a, v(&["x", "--repo=s"]));
        assert_eq!(take_flag(&mut a, "--repo").unwrap(), Some("s".into()));
        assert_eq!(take_flag(&mut a, "--repo").unwrap(), None);
    }

    #[test]
    fn a_value_beginning_with_two_dashes_is_refused() {
        let mut a = v(&["--repo", "--x"]);
        let e = take_flag(&mut a, "--repo").unwrap_err();
        assert_eq!(e.message, "--repo requires a value");
        assert_eq!(e.exit_code(), 2);
    }

    #[test]
    fn uints_are_ascii_digits_within_the_safe_range() {
        assert_eq!(
            parse_optional_uint("--n", Some("42".into())).unwrap(),
            Some(42)
        );
        for bad in ["", "-1", "1.5", "1e3", "9007199254740992", "+1"] {
            assert!(
                parse_optional_uint("--n", Some(bad.into())).is_err(),
                "{bad}"
            );
        }
    }

    #[test]
    fn columns_drop_blanks_and_repeats_and_name_the_unknown() {
        let got = parse_columns("--fields", Some("b, a,,b".into()), &["a", "b", "c"]).unwrap();
        assert_eq!(got, v(&["b", "a"]));
        let e = parse_columns("--fields", Some("z".into()), &["b", "a"]).unwrap_err();
        assert_eq!(e.message, "Unknown field(s): z. Available: a, b");
    }

    #[test]
    fn positionals_count_and_unknown_flags() {
        assert!(require_positionals(&v(&["a"]), 1, 1, "show <id>").is_ok());
        let e = require_positionals(&v(&[]), 1, 1, "show <id>").unwrap_err();
        assert_eq!(e.message, "Expected 1 positional argument, got 0");
        assert_eq!(
            e.recovery,
            vec![Recovery::Note {
                text: "usage: {tool} show <id>".into()
            }]
        );
        let e = require_positionals(&v(&["--zzz"]), 0, 0, "x").unwrap_err();
        assert_eq!(e.message, "Unknown flag: --zzz");
    }
}
