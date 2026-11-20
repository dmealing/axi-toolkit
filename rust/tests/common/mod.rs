//! Shared helpers for the integration tests: paths, SHA-256, and JSON-to-`Value` conversion.
#![allow(dead_code)]

use axi_toolkit::toon::Value;
use std::fs;
use std::path::{Path, PathBuf};

/// The crate root (`rust/`).
pub fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

/// `conformance/` at the repository root -- the one pack every language reads in place.
pub fn conformance() -> PathBuf {
    root().join("..").join("conformance")
}

/// The TOON spec fixtures directory the pack's `toon-spec.json` names (the Python package ships
/// them), resolved against the pack directory.
pub fn toon_spec() -> PathBuf {
    let spec = pack("toon-spec.json");
    let fixtures = spec["fixtures"].as_str().expect("fixtures path");
    conformance().join(fixtures).parent().unwrap().to_path_buf()
}

/// Read and parse one JSON file. Object key order is kept, so a comparison that is
/// order-sensitive checks the wire form's documented key order too.
pub fn read_json(path: &Path) -> serde_json::Value {
    let text = fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// One pack file by name.
pub fn pack(name: &str) -> serde_json::Value {
    read_json(&conformance().join(name))
}

/// The JSON data model as the encoder's `Value`. A number written without a fraction or
/// exponent that fits an `i64` is an integer; any other is a float.
pub fn to_value(j: &serde_json::Value) -> Value {
    use serde_json::Value as J;
    match j {
        J::Null => Value::Null,
        J::Bool(b) => Value::Bool(*b),
        J::Number(n) => match n.as_i64() {
            Some(i) => Value::Int(i),
            None => Value::Num(n.as_f64().expect("a finite number")),
        },
        J::String(s) => Value::Str(s.clone()),
        J::Array(a) => Value::Array(a.iter().map(to_value).collect()),
        J::Object(o) => Value::Object(o.iter().map(|(k, v)| (k.clone(), to_value(v))).collect()),
    }
}

/// `j[key]` as a string, panicking with the key named if it is absent or not a string.
pub fn str_of<'a>(j: &'a serde_json::Value, key: &str) -> &'a str {
    j[key]
        .as_str()
        .unwrap_or_else(|| panic!("{key} is not a string in {j}"))
}

/// SHA-256 of `data`, as lowercase hex.
pub fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for block in msg.chunks(64) {
        let mut w = [0u32; 64];
        for (i, word) in block.chunks(4).enumerate() {
            w[i] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7]
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [
                t1.wrapping_add(t2),
                v[0],
                v[1],
                v[2],
                v[3].wrapping_add(t1),
                v[4],
                v[5],
                v[6],
            ];
        }
        for i in 0..8 {
            h[i] = h[i].wrapping_add(v[i]);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

/// The names a `checksums.txt` records and the names that stand in `dir` (files with `ext`),
/// compared the way the Python pack check does: a file edited, deleted or added is the same failure.
/// Returns the names whose content no longer matches.
pub fn digest_mismatches(checksums: &Path, dir: &Path, prefix: &str, ext: &str) -> Vec<String> {
    let mut recorded = std::collections::BTreeMap::new();
    for line in fs::read_to_string(checksums).unwrap().lines() {
        if let Some((digest, name)) = line.trim().split_once(char::is_whitespace) {
            recorded.insert(
                name.trim().trim_start_matches(prefix).to_string(),
                digest.to_string(),
            );
        }
    }
    let mut actual = std::collections::BTreeMap::new();
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_some_and(|e| e == ext) {
            let name = path.file_name().unwrap().to_string_lossy().into_owned();
            actual.insert(name, sha256_hex(&fs::read(&path).unwrap()));
        }
    }
    let names: std::collections::BTreeSet<_> =
        recorded.keys().chain(actual.keys()).cloned().collect();
    names
        .into_iter()
        .filter(|n| recorded.get(n) != actual.get(n))
        .collect()
}

/// The encoder's `Value` as JSON text for the Python oracle: an `Int` is written without a
/// fraction and a `Num` always with one, so Python reads back the same number type.
pub fn to_json(v: &Value) -> serde_json::Value {
    use serde_json::Value as J;
    match v {
        Value::Null => J::Null,
        Value::Bool(b) => J::Bool(*b),
        Value::Int(i) => J::from(*i),
        Value::Num(n) => J::Number(serde_json::Number::from_f64(*n).expect("finite")),
        Value::Str(s) => J::String(s.clone()),
        Value::Array(a) => J::Array(a.iter().map(to_json).collect()),
        Value::Object(o) => J::Object(o.iter().map(|(k, v)| (k.clone(), to_json(v))).collect()),
    }
}

/// A small deterministic generator (xorshift64*), so a failing case is reproducible from its seed.
pub struct Rng(pub u64);

impl Rng {
    /// The next 64 random bits.
    pub fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    /// A number below `n`.
    pub fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
    /// One of `items`.
    pub fn pick<'a, T>(&mut self, items: &'a [T]) -> &'a T {
        &items[self.below(items.len())]
    }
    /// True one time in `n`.
    pub fn one_in(&mut self, n: usize) -> bool {
        self.below(n) == 0
    }
}
