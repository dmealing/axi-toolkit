//! The pack's contract files -- errors, render rules, recovery lines, credentials and
//! redaction -- run through the Rust implementation. Every expected value comes from
//! `conformance/*.json`, which the Python reference writes; nothing is typed in here.

mod common;

use axi_toolkit::envconfig::{self, CredentialSpec, Scheme};
use axi_toolkit::errors::{self, AxiError, ErrorKind, Recovery};
use axi_toolkit::redact::{self, Pattern, Redactor};
use axi_toolkit::render::{cli, prose};
use axi_toolkit::toon::Value;
use common::{pack, str_of, to_value};
use std::collections::HashMap;

fn recovery(j: &serde_json::Value) -> Recovery {
    Recovery::from_value(&to_value(j)).unwrap_or_else(|e| panic!("{j}: {e}"))
}

fn recoveries(j: &serde_json::Value) -> Vec<Recovery> {
    j.as_array().unwrap().iter().map(recovery).collect()
}

fn strings(j: &serde_json::Value) -> Vec<String> {
    j.as_array()
        .unwrap()
        .iter()
        .map(|s| s.as_str().unwrap().to_string())
        .collect()
}

#[test]
fn errors_json() {
    let p = pack("errors.json");
    assert_eq!(p["exit_codes"]["EXIT_OK"], errors::EXIT_OK);
    assert_eq!(p["exit_codes"]["EXIT_ERROR"], errors::EXIT_ERROR);
    assert_eq!(p["exit_codes"]["EXIT_USAGE"], errors::EXIT_USAGE);
    assert_eq!(strings(&p["kinds"]), errors::KINDS);
    assert_eq!(str_of(&p, "tool_slot"), errors::TOOL_SLOT);
    assert_eq!(strings(&p["classes"]), errors::CLASSES);
    assert_eq!(str_of(&p, "unclassified"), errors::CLASS_UNCLASSIFIED);

    for e in p["exceptions"].as_array().unwrap() {
        let kind = ErrorKind::from_name(str_of(e, "name")).unwrap_or_else(|| panic!("{e}"));
        assert_eq!(
            kind.exit_code() as i64,
            e["exit_code"].as_i64().unwrap(),
            "{e}"
        );
    }
    assert_eq!(
        p["exceptions"].as_array().unwrap().len(),
        ErrorKind::ALL.len()
    );

    let table: Vec<(String, String)> = p["fault_classes"]["table"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
        .collect();
    let table: Vec<(&str, &str)> = table
        .iter()
        .map(|(a, b)| (a.as_str(), b.as_str()))
        .collect();
    for c in p["fault_classes"]["cases"].as_array().unwrap() {
        assert_eq!(
            errors::fault_class(c["code"].as_str(), &table),
            str_of(c, "expected"),
            "{c}"
        );
    }

    for c in p["error_dicts"].as_array().unwrap() {
        let kind = ErrorKind::from_name(str_of(c, "exception")).unwrap();
        let mut e =
            AxiError::new(kind, str_of(c, "message")).with_recovery(recoveries(&c["recovery"]));
        if let Some(code) = c["code"].as_str() {
            e = e.with_code(code);
        }
        assert_eq!(e.to_value(), to_value(&c["expected"]), "{}", c["name"]);
    }
}

fn check_renders(r: &Recovery, renders: &serde_json::Value, what: &str) {
    for (tool, expected) in renders.as_object().unwrap() {
        assert_eq!(
            cli::line(r, tool),
            str_of(expected, "line"),
            "{what} / {tool}"
        );
        assert_eq!(
            prose::sentence(r, tool),
            str_of(expected, "sentence"),
            "{what} / {tool}"
        );
    }
}

#[test]
fn render_rules_json() {
    let p = pack("render-rules.json");
    for c in p["cases"].as_array().unwrap() {
        let r = recovery(&c["recovery"]);
        assert_eq!(r.to_value(), to_value(&c["recovery"]), "{}", c["name"]);
        assert_eq!(
            r.mentions_tool(),
            c["mentions_tool"].as_bool().unwrap(),
            "{}",
            c["name"]
        );
        check_renders(&r, &c["renders"], str_of(c, "name"));
        // The name is not baked in: a recovery that mentions the tool renders differently for
        // another one, and one that does not renders identically.
        let (a, b) = (cli::line(&r, "one-tool"), cli::line(&r, "two-tool"));
        assert_eq!(a != b, r.mentions_tool(), "{}", c["name"]);
    }
    for c in p["hand_written"].as_array().unwrap() {
        let r = recovery(&c["input"]);
        assert_eq!(r.to_value(), to_value(&c["recovery"]), "{}", c["name"]);
        check_renders(&r, &c["renders"], str_of(c, "name"));
    }
    for c in p["rejected"].as_array().unwrap() {
        assert!(
            Recovery::from_value(&to_value(&c["input"])).is_err(),
            "{} was accepted",
            c["name"]
        );
    }
    for c in p["parse"].as_array().unwrap() {
        let (tool, line) = (str_of(c, "tool"), str_of(c, "line"));
        let r = cli::parse(line, tool).unwrap();
        assert_eq!(r.to_value(), to_value(&c["intent"]), "{line:?}");
        assert_eq!(cli::line(&r, tool), str_of(c, "renders_back"), "{line:?}");
    }
    for line in p["parse_refused"].as_array().unwrap() {
        assert!(
            cli::parse(line.as_str().unwrap(), "example-axi").is_err(),
            "{line}"
        );
    }
}

#[test]
fn recovery_json_every_source_line_round_trips_byte_for_byte() {
    let p = pack("recovery.json");
    let sibling = str_of(&p, "sibling");
    let entries = p["entries"].as_array().unwrap();
    assert!(entries.len() >= 300, "the corpus shrank: {}", entries.len());
    for e in entries {
        let (tool, line) = (str_of(e, "tool"), str_of(e, "line"));
        let r = cli::parse(line, tool).unwrap_or_else(|err| panic!("{line:?}: {err}"));
        assert_eq!(r.to_value(), to_value(&e["intent"]), "{line:?}");
        assert_eq!(cli::line(&r, tool), line);
        assert_eq!(prose::sentence(&r, tool), str_of(e, "sentence"), "{line:?}");
        assert_eq!(
            cli::line(&r, sibling),
            str_of(&e["other"], "line"),
            "{line:?}"
        );
        assert_eq!(
            prose::sentence(&r, sibling),
            str_of(&e["other"], "sentence"),
            "{line:?}"
        );
    }
}

fn spec_from(j: &serde_json::Value) -> CredentialSpec {
    let mut s = CredentialSpec::new(strings(&j["url_vars"]), strings(&j["token_vars"]));
    s.setup = recoveries(&j["setup"]);
    s.verify = Some(recovery(&j["verify"]));
    s.token_recovery = recoveries(&j["token_recovery"]);
    s.default_scheme = match str_of(j, "default_scheme") {
        "http" => Scheme::Http,
        "https" => Scheme::Https,
        other => panic!("scheme {other}"),
    };
    s.default_port = j["default_port"].as_u64().map(|p| p as u16);
    s.strip_path_suffix = str_of(j, "strip_path_suffix").to_string();
    s.default_timeout = j["default_timeout"].as_f64().unwrap();
    s
}

fn environ(j: &serde_json::Value) -> HashMap<String, String> {
    j.as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_string()))
        .collect()
}

#[test]
fn credentials_json() {
    let p = pack("credentials.json");
    assert_eq!(
        p["constants"]["default_timeout"].as_f64().unwrap(),
        envconfig::DEFAULT_TIMEOUT
    );
    let codes = strings(&p["constants"]["error_codes"]);
    assert_eq!(
        codes,
        [
            envconfig::CODE_BAD_TOKEN,
            envconfig::CODE_BAD_URL,
            envconfig::CODE_NOT_CONFIGURED
        ]
    );
    for (tool, t) in p["tools"].as_object().unwrap() {
        let spec = spec_from(&t["spec"]);
        for c in t["normalized_urls"].as_array().unwrap() {
            let got = envconfig::normalize_base_url(str_of(c, "raw"), &spec).unwrap();
            assert_eq!(got, str_of(c, "expected"), "{tool} {c}");
        }
        for c in t["failures"].as_array().unwrap() {
            let err = match str_of(c, "operation") {
                "load" => envconfig::load(&spec, &environ(&c["environ"]), None).unwrap_err(),
                "normalize_base_url" => {
                    envconfig::normalize_base_url(str_of(c, "raw"), &spec).unwrap_err()
                }
                other => panic!("operation {other}"),
            };
            let want = &c["expected"];
            let name = format!("{tool} {}", c["name"]);
            assert_eq!(err.kind, ErrorKind::Config, "{name}");
            assert_eq!(err.message, str_of(want, "message"), "{name}");
            assert_eq!(err.code.as_deref(), want["code"].as_str(), "{name}");
            assert_eq!(
                Value::Array(err.recovery.iter().map(Recovery::to_value).collect()),
                to_value(&want["recovery"]),
                "{name}"
            );
            assert_eq!(
                cli::lines(&err.recovery, tool),
                strings(&want["lines"]),
                "{name}"
            );
        }
        for c in t["loads"].as_array().unwrap() {
            let got =
                envconfig::load(&spec, &environ(&c["environ"]), c["timeout"].as_f64()).unwrap();
            let want = &c["expected"];
            assert_eq!(got.base_url, str_of(want, "base_url"), "{tool} {c}");
            assert_eq!(got.token, str_of(want, "token"));
            assert_eq!(got.timeout, want["timeout"].as_f64().unwrap());
            assert_eq!(got.url_var, str_of(want, "url_var"));
            assert_eq!(got.token_var, str_of(want, "token_var"));
        }
        for c in t["describes"].as_array().unwrap() {
            let env = environ(&c["environ"]);
            let d = envconfig::describe_environment(&spec, &env);
            let want = &c["describe_environment"];
            assert_eq!(d.url_var, str_of(want, "url_var"), "{tool} {c}");
            assert_eq!(d.url_set, want["url_set"].as_bool().unwrap());
            assert_eq!(d.token_var, str_of(want, "token_var"));
            assert_eq!(d.token_set, want["token_set"].as_bool().unwrap());
            assert_eq!(
                envconfig::missing_vars(&spec, &env),
                strings(&c["missing_vars"])
            );
        }
    }
}

/// The Rust shape for each regular expression the pack declares. A source this table does not
/// know is a failure: a refreshed pack must not pass by the new pattern going unchecked.
fn pattern_for(source: &str, flags: &str) -> Pattern {
    assert!(flags.contains('i') && flags.contains('u'), "flags {flags}");
    match source {
        r#"([?&](?:token|access_token|authsig)=)[^&\s"'<>]+"# => Pattern::keyed(
            source,
            &[
                "?token=",
                "&token=",
                "?access_token=",
                "&access_token=",
                "?authsig=",
                "&authsig=",
            ],
            1,
            redact::is_query_value_char,
        ),
        r"(X-Plex-Token=)[A-Za-z0-9._~-]{4,}" => {
            Pattern::keyed(source, &["X-Plex-Token="], 4, redact::is_token_char)
        }
        r"([?&]token=)[A-Za-z0-9._~-]{8,}" => {
            Pattern::keyed(source, &["?token=", "&token="], 8, redact::is_token_char)
        }
        r#"(X-Plex-Token['"]?\s*[:=]\s*['"]?)[A-Za-z0-9._~-]{8,}"# => header_pattern(source),
        other => panic!("no Rust shape for the pack's pattern {other}"),
    }
}

/// A shape `Pattern::keyed` cannot express: the header name, an optional quote, a separator and
/// optional spaces, then the value. Written by hand to show what a tool's own shape looks like.
fn header_pattern(source: &str) -> Pattern {
    Pattern::new(source, |text, from| {
        let lower = text.to_ascii_lowercase();
        let mut at = from;
        while let Some(i) = lower[at..].find("x-plex-token") {
            let start = at + i;
            let mut j = start + "x-plex-token".len();
            let skip = |j: &mut usize, f: &dyn Fn(char) -> bool| {
                while let Some(c) = text[*j..].chars().next().filter(|c| f(*c)) {
                    *j += c.len_utf8();
                }
            };
            if matches!(text[j..].chars().next(), Some('\'' | '"')) {
                j += 1;
            }
            skip(&mut j, &|c| c.is_whitespace());
            if matches!(text[j..].chars().next(), Some(':' | '=')) {
                j += 1;
                skip(&mut j, &|c| c.is_whitespace());
                if matches!(text[j..].chars().next(), Some('\'' | '"')) {
                    j += 1;
                }
                let keep = j;
                let end = text[keep..]
                    .char_indices()
                    .find(|(_, c)| !redact::is_token_char(*c))
                    .map_or(text.len(), |(k, _)| keep + k);
                if text[keep..end].chars().count() >= 8 {
                    return Some(redact::Match { start, keep, end });
                }
            }
            at = start + 1;
        }
        None
    })
}

fn b64url(text: &str) -> String {
    const A: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in text.as_bytes().chunks(3) {
        let n = chunk.iter().fold(0u32, |a, b| a << 8 | *b as u32) << (8 * (3 - chunk.len()));
        for k in 0..=chunk.len() {
            out.push(A[(n >> (18 - 6 * k) & 63) as usize] as char);
        }
    }
    out
}

fn fragment(p: &serde_json::Value, name: &str) -> String {
    let r = &p["fragments"][name];
    if let Some(parts) = r.get("join") {
        return strings(parts).concat();
    }
    format!(
        "{}.{}.{}",
        b64url(str_of(r, "header")),
        b64url(str_of(r, "payload")),
        str_of(r, "signature")
    )
}

#[test]
fn redaction_json() {
    let p = pack("redaction.json");
    assert_eq!(str_of(&p, "redacted"), redact::REDACTED);
    assert_eq!(
        p["min_secret_length"].as_u64().unwrap() as usize,
        redact::MIN_SECRET_LENGTH
    );
    assert_eq!(
        strings(&p["order"]),
        ["literals", "bearer", "registered", "token"]
    );
    for (tool, t) in p["tools"].as_object().unwrap() {
        let mut r = Redactor::new();
        for s in t["secrets"].as_array().unwrap() {
            r.register_secret(
                str_of(s, "value"),
                s["min_length"].as_u64().unwrap() as usize,
            );
        }
        for pat in t["patterns"].as_array().unwrap() {
            r.register_pattern(pattern_for(str_of(pat, "source"), str_of(pat, "flags")));
        }
        for c in t["cases"].as_array().unwrap() {
            let input: String = c["input"]
                .as_array()
                .unwrap()
                .iter()
                .map(|piece| match piece.as_str() {
                    Some(s) => s.to_string(),
                    None => fragment(&p, str_of(piece, "ref")),
                })
                .collect();
            assert_eq!(
                r.redact(&input),
                str_of(c, "expected"),
                "{tool} {}",
                c["name"]
            );
        }
    }
}
