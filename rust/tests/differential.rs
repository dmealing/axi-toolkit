//! Differential tests: the Rust encoder and renderers against the Python reference, over
//! generated inputs, byte for byte.
//!
//! The conformance pack pins the contract's corners; this reaches the space between them. It
//! needs a checkout of the Python library, so it is opt-in: set `AXI_PYTHON_REFERENCE` to the
//! `python/` directory of this repository (the one holding `src/axi_toolkit`) and a `python3` (3.10+) must run.
//! Without the variable each test says it was skipped and passes.

mod common;

use axi_toolkit::errors::Recovery;
use axi_toolkit::render::{cli, prose};
use axi_toolkit::toon::{encode_with, Delimiter, Options, Value};
use common::{root, str_of, to_json, Rng};
use serde_json::json;
use std::io::Write;
use std::process::{Command, Stdio};

/// How many cases of each kind. Large enough to hit the rare quoting branches.
const CASES: usize = 3000;

fn reference() -> Option<String> {
    std::env::var("AXI_PYTHON_REFERENCE")
        .ok()
        .filter(|s| !s.is_empty())
}

fn ask_python(checkout: &str, request: &serde_json::Value) -> serde_json::Value {
    let script = root().join("tests/oracle/oracle.py");
    let mut child = Command::new("python3")
        .arg(script)
        .env("PYTHONPATH", format!("{checkout}/src"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("python3 starts");
    let mut stdin = child.stdin.take().unwrap();
    let body = request.to_string();
    let writer = std::thread::spawn(move || drop(stdin.write_all(body.as_bytes())));
    let out = child.wait_with_output().unwrap();
    writer.join().unwrap();
    assert!(out.status.success(), "the oracle failed");
    serde_json::from_slice(&out.stdout).unwrap()
}

const WORDS: &[&str] = &[
    "",
    " ",
    "a",
    "plain",
    "two words",
    "-",
    "- item",
    "null",
    "true",
    "false",
    "42",
    "-3.5",
    "1e5",
    "007",
    "0x1F",
    "a,b",
    "a|b",
    "a\tb",
    "x:y",
    "key: v",
    "\"q\"",
    "back\\slash",
    "line\nbreak",
    "cr\rlf",
    "[x]",
    "{y}",
    "#hash",
    "+1",
    "trailing ",
    " leading",
    "é",
    "日本語",
    "😀",
    "\u{feff}bom",
    "\u{a0}nbsp",
    "\u{2028}",
    "\u{7f}",
    "\u{1}ctl",
    "_under",
    "dot.key",
    "9lives",
    "Key",
    "a-b",
    "a b",
];

fn word(r: &mut Rng) -> String {
    if r.one_in(4) {
        let n = 1 + r.below(8);
        (0..n)
            .map(|_| char::from_u32(32 + r.below(95) as u32).unwrap())
            .collect()
    } else {
        r.pick(WORDS).to_string()
    }
}

fn key(r: &mut Rng) -> String {
    if r.one_in(2) {
        r.pick(&["id", "name", "tags", "a", "b.c", "_x", "k1", "Z"])
            .to_string()
    } else {
        word(r)
    }
}

fn scalar(r: &mut Rng) -> Value {
    match r.below(7) {
        0 => Value::Null,
        1 => Value::Bool(r.one_in(2)),
        2 => Value::Int(
            r.pick(&[
                0,
                1,
                -1,
                42,
                1_000_000,
                i64::MAX,
                i64::MIN + 1,
                123_456_789_012,
            ])
            .to_owned(),
        ),
        3 => Value::Num(*r.pick(&[
            0.5,
            -0.0,
            1.0,
            2.75,
            1e-7,
            1e-6,
            1.5e-5,
            1e21,
            1e20,
            9_007_199_254_740_992.0,
            9_007_199_254_740_994.0,
            1e16,
            1e17,
            (2f64.powi(63)),
            -(2f64.powi(63)),
            9.999_999_999_999_998e20,
            -1e21,
            -1.5e300,
            f64::MAX,
            f64::MIN,
            1.2345e25,
            -2.5e-10,
            123456.789,
            0.1 + 0.2,
        ])),
        _ => Value::Str(word(r)),
    }
}

fn value(r: &mut Rng, depth: usize) -> Value {
    if depth == 0 {
        return scalar(r);
    }
    match r.below(6) {
        0 | 1 => scalar(r),
        2 => Value::Array((0..r.below(5)).map(|_| scalar(r)).collect()),
        3 => {
            // Rows that often share their keys, so the tabular and keyed-tabular forms occur.
            let mut keys: Vec<String> = (0..1 + r.below(3)).map(|_| key(r)).collect();
            keys.dedup();
            keys.sort();
            keys.dedup();
            let rows = (0..1 + r.below(4))
                .map(|_| {
                    let ks: Vec<&String> = keys.iter().filter(|_| !r.one_in(12)).collect();
                    Value::Object(
                        ks.into_iter()
                            .map(|k| {
                                (
                                    k.clone(),
                                    if r.one_in(9) {
                                        value(r, depth - 1)
                                    } else {
                                        scalar(r)
                                    },
                                )
                            })
                            .collect(),
                    )
                })
                .collect();
            Value::Array(rows)
        }
        4 => Value::Array((0..r.below(4)).map(|_| value(r, depth - 1)).collect()),
        _ => {
            let mut seen = Vec::new();
            let mut fields = Vec::new();
            for _ in 0..r.below(5) {
                let k = key(r);
                if !seen.contains(&k) {
                    seen.push(k.clone());
                    fields.push((k, value(r, depth - 1)));
                }
            }
            Value::Object(fields)
        }
    }
}

#[test]
fn the_toon_encoder_matches_python_on_generated_values() {
    let Some(checkout) = reference() else {
        eprintln!("skipped: AXI_PYTHON_REFERENCE is not set");
        return;
    };
    let mut r = Rng(0x9E37_79B9_7F4A_7C15);
    let mut cases = Vec::new();
    for _ in 0..CASES {
        let delimiter = *r.pick(&[Delimiter::Comma, Delimiter::Tab, Delimiter::Pipe]);
        let indent = *r.pick(&[1usize, 2, 2, 4]);
        cases.push((value(&mut r, 3), delimiter, indent));
    }
    let request = json!({"toon": cases.iter().map(|(v, d, i)| json!({
        "value": to_json(v),
        "delimiter": match d { Delimiter::Comma => ",", Delimiter::Tab => "\t", Delimiter::Pipe => "|" },
        "indent": i,
    })).collect::<Vec<_>>()});
    let answer = ask_python(&checkout, &request);
    let theirs = answer["toon"].as_array().unwrap();
    assert_eq!(theirs.len(), cases.len());
    let mut bad = Vec::new();
    for (n, ((v, delimiter, indent), want)) in cases.iter().zip(theirs).enumerate() {
        let opts = Options {
            indent: *indent,
            delimiter: *delimiter,
            ..Options::default()
        };
        let got = encode_with(v, &opts);
        if got != want.as_str().unwrap() {
            bad.push(format!(
                "#{n}: {}\n  rust:   {got:?}\n  python: {want}",
                to_json(v)
            ));
        }
    }
    assert!(
        bad.is_empty(),
        "{} of {} differ:\n{}",
        bad.len(),
        cases.len(),
        bad.iter().take(5).cloned().collect::<Vec<_>>().join("\n")
    );
}

fn recovery(r: &mut Rng) -> Recovery {
    let words = |r: &mut Rng| -> Vec<String> { (0..1 + r.below(3)).map(|_| nonblank(r)).collect() };
    let mut rec = match r.below(5) {
        0 => Recovery::run(words(r)),
        1 => Recovery::retry(nonblank(r)),
        2 => Recovery::set_env(*r.pick(&["HA_TOKEN", "X_URL", "A1"]), nonblank(r)),
        3 => Recovery::choose(nonblank(r), words(r)),
        _ => Recovery::note(
            ["Check the {tool} logs", "Nothing to do", "Try again later."][r.below(3)],
        ),
    };
    if r.one_in(2) {
        rec = rec.with_purpose(nonblank(r));
    }
    if r.one_in(4) {
        rec = rec.with_lead(*r.pick(&["Run", "Raise the limit with", "Use"]));
    }
    if r.one_in(4) {
        rec = rec.with_separator(*r.pick(&[": ", " ", " - "]));
    }
    if r.one_in(3) {
        rec = rec.with_example(nonblank(r));
    }
    if r.one_in(3) {
        rec = rec.with_reference(nonblank(r));
    }
    rec
}

fn nonblank(r: &mut Rng) -> String {
    loop {
        let w = word(r);
        if !w.trim().is_empty() && !w.contains('{') && !w.contains('\n') && !w.contains('\r') {
            return w;
        }
    }
}

#[test]
fn the_recovery_renderers_match_python_on_generated_recoveries() {
    let Some(checkout) = reference() else {
        eprintln!("skipped: AXI_PYTHON_REFERENCE is not set");
        return;
    };
    let mut r = Rng(0xD1B5_4A32_D192_ED03);
    let mut cases = Vec::new();
    for _ in 0..CASES {
        // Builders that reject an odd combination are a Rust-side contract: skip that draw.
        if let Ok(rec) = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| recovery(&mut r)))
        {
            cases.push(rec);
        }
    }
    assert!(cases.len() > CASES / 2);
    let request = json!({"recovery": cases.iter().map(|c| json!({
        "recovery": to_json(&c.to_value()), "tool": "one-axi", "other": "two-axi",
    })).collect::<Vec<_>>()});
    let answer = ask_python(&checkout, &request);
    let theirs = answer["recovery"].as_array().unwrap();
    assert_eq!(theirs.len(), cases.len());
    let mut bad = Vec::new();
    for (n, (c, want)) in cases.iter().zip(theirs).enumerate() {
        for (slot, tool) in [("tool", "one-axi"), ("other", "two-axi")] {
            let (line, sentence) = (cli::line(c, tool), prose::sentence(c, tool));
            if line != str_of(&want[slot], "line") || sentence != str_of(&want[slot], "sentence") {
                bad.push(format!(
                    "#{n} {}\n  rust:   {line:?} / {sentence:?}\n  python: {} / {}",
                    to_json(&c.to_value()),
                    want[slot]["line"],
                    want[slot]["sentence"]
                ));
            }
        }
        // parse is the inverse of line, in both implementations.
        let back = cli::parse(&cli::line(c, "one-axi"), "one-axi").map(|p| to_json(&p.to_value()));
        if back.as_ref().ok() != Some(&want["parsed_back"]) {
            bad.push(format!(
                "#{n} parse: rust {back:?} python {}",
                want["parsed_back"]
            ));
        }
    }
    assert!(
        bad.is_empty(),
        "{} differ:\n{}",
        bad.len(),
        bad.iter().take(5).cloned().collect::<Vec<_>>().join("\n")
    );
}
