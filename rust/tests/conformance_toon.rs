//! The TOON encoder against the official encode fixtures, and the pack's own checksums.
//!
//! Two fixture sets are run: the spec v4.4 set the Python reference vendors (read in place from the Python package via the pack's `toon-spec.json`), and the spec v4.1.1 set the downstream prototype was built against
//! (`tests/fixtures/toon-4.1`, 179 cases), which the encoder must keep passing.

mod common;

/// The cases in the spec v4.4 set. A fixture that stops being collected fails the suite
/// instead of shrinking the score.
const EXPECTED_V44_CASES: usize = 160;

use axi_toolkit::toon::{encode_with, Delimiter, Options, Value};
use common::{
    conformance, digest_mismatches, pack, read_json, root, sha256_hex, to_value, toon_spec,
};
use std::fs;
use std::path::Path;

fn fixture_files(dir: &Path) -> Vec<std::path::PathBuf> {
    let mut files: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
        .collect();
    files.sort();
    files
}

fn options(case: &serde_json::Value) -> Options {
    let mut o = Options::default();
    let Some(opts) = case.get("options") else {
        return o;
    };
    for (k, v) in opts.as_object().expect("options is an object") {
        match k.as_str() {
            "delimiter" => {
                o.delimiter = Delimiter::from_symbol(v.as_str().unwrap())
                    .unwrap_or_else(|| panic!("unknown delimiter {v}"))
            }
            "indentSize" => o.indent = v.as_u64().unwrap() as usize,
            // A case run with default settings and reported as a pass is the failure mode the
            // stale-copy exercise exists to prevent.
            other => panic!("fixture option {other:?} is not applied by this suite"),
        }
    }
    o
}

/// Encode every case in `dir`; return how many there were and the failures.
/// An integral number the encoder holds as a float although the fixture wrote it as an integer.
fn beyond_i64_integer(j: &serde_json::Value) -> bool {
    j.as_f64()
        .is_some_and(|f| j.as_i64().is_none() && f.fract() == 0.0 && f.abs() < 1e21)
}

fn exact_integer(v: &Value) -> String {
    match v {
        Value::Num(n) => format!("{}", *n as i128),
        _ => unreachable!("a literal beyond i64 is read as a float"),
    }
}

fn run_fixtures(dir: &Path) -> (usize, Vec<String>) {
    let (mut total, mut failures) = (0, Vec::new());
    for path in fixture_files(dir) {
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        let doc = read_json(&path);
        assert_eq!(doc["category"], "encode", "{name} is not an encode fixture");
        for (i, case) in doc["tests"].as_array().unwrap().iter().enumerate() {
            assert!(
                case.get("shouldError").is_none(),
                "{name}[{i}]: error cases are not run"
            );
            let input: Value = to_value(&case["input"]);
            let expected = case["expected"].as_str().unwrap();
            total += 1;
            let got = encode_with(&input, &options(case));
            // A JSON integer literal beyond i64 is a Python `int` in the reference (its exact
            // digits) but an `f64` here, because `Value::Int` is an i64. A float prints as its
            // exact integer, as Python's does, so what this case can check is that: the value the
            // float holds, which the fixture's rounded digits agree with to 17 significant digits.
            let expected = if beyond_i64_integer(&case["input"]) {
                exact_integer(&input)
            } else {
                expected.to_string()
            };
            if got != expected {
                failures.push(format!(
                    "{name}[{i}] {}: expected {expected:?}, got {got:?}",
                    case["name"]
                ));
            }
        }
    }
    (total, failures)
}

#[test]
fn the_packs_checksums_match_the_files() {
    let dir = conformance();
    assert!(digest_mismatches(&dir.join("checksums.txt"), &dir, "", "json").is_empty());
    let spec = toon_spec();
    let bad = digest_mismatches(
        &spec.join("checksums.txt"),
        &spec.join("encode"),
        "",
        "json",
    );
    assert!(
        bad.is_empty(),
        "fixture files edited, added or removed: {bad:?}"
    );
}

#[test]
fn toon_spec_json_names_files_that_exist() {
    let spec = pack("toon-spec.json");
    for key in ["fixtures", "checksums", "license", "provenance"] {
        let path = spec[key].as_str().unwrap();
        assert!(
            conformance().join(path).exists(),
            "{key}: {path} does not exist"
        );
    }
}

#[test]
fn spec_4_4_fixtures_all_pass() {
    let (total, failures) = run_fixtures(&toon_spec().join("encode"));
    assert!(
        failures.is_empty(),
        "{}/{total} failing:\n{}",
        failures.len(),
        failures.join("\n")
    );
    assert_eq!(total, EXPECTED_V44_CASES, "case count changed");
    eprintln!("spec v4.4 fixtures: {total}/{total}");
}

#[test]
fn the_prototypes_179_spec_4_1_fixtures_still_pass() {
    let dir = root().join("tests/fixtures/toon-4.1");
    assert!(
        digest_mismatches(&dir.join("checksums.txt"), &dir.join("encode"), "", "json").is_empty()
    );
    assert_eq!(fixture_files(&dir.join("encode")).len(), 9);
    let (total, failures) = run_fixtures(&dir.join("encode"));
    assert!(
        failures.is_empty(),
        "{}/{total} failing:\n{}",
        failures.len(),
        failures.join("\n")
    );
    assert_eq!(total, 179, "case count changed");
}

#[test]
fn the_sha256_used_to_verify_is_sha256() {
    assert_eq!(
        sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        sha256_hex(&[b'a'; 1000]),
        "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3"
    );
}
