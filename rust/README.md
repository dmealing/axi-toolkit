# axi-toolkit (Rust)

The shared toolkit for **Agent eXperience Interface** (AXI) command-line tools, in Rust. It is a
peer of the Python `axi-toolkit` and its TypeScript port: the same contract, judged by the same
conformance files, so a tool written in any of the three prints the same bytes.

It gives a tool the parts every agent-facing CLI needs and gets subtly wrong when each copies them:

* a strict **TOON** encoder, for compact, token-cheap output;
* **errors that carry recovery as data** (what to run, what to set, what to choose), rendered as
  shell lines or as prose by whoever prints them;
* a **redaction boundary**, so a credential cannot reach stdout;
* **environment-only credentials** with URL normalisation and precise, actionable failures;
* a **flag parser, help renderer and dispatcher** with one seam for the hand-written half of a tool;
* an optional **HTTP client** and a **subprocess helper** that keep secrets off the wire and off argv.

`std` only, except the optional `http` feature (`ureq` over `rustls`). No `unsafe`
(`#![forbid(unsafe_code)]` via the lint table). No regex engine.

```sh
cargo add axi-toolkit            # or a path/git dependency; the crate is not yet published
cargo add axi-toolkit --features http
```

## Crate layout

| Module | What it is |
| --- | --- |
| `toon` | The TOON encoder: tabular, keyed-tabular, list and inline forms. Two dialects: the Python reference's spec v4.4 (`Dialect::Spec`) and the `@toon-format/toon` 2.3 library (`Dialect::ToonJs2`), for a tool replacing a JavaScript one. |
| `errors` | `AxiError` and its kinds, codes, exit statuses (0 / 1 / 2), fault classes, and `Recovery`, the closed vocabulary of next steps: `run`, `retry`, `set_env`, `choose`, `note`. |
| `render` | `render::cli` turns a `Recovery` into a shell line and parses it back; `render::prose` turns it into a sentence; `render::view` builds stdout documents (lists, details, help, error blocks) and truncates at a UTF-16 length so it matches a JavaScript tool. |
| `redact` | Literal secrets and credential shapes removed from any text: literals (longest first), bearer tokens, registered patterns, JWTs. |
| `envconfig` | Credentials from the environment only: first-set variable wins, base URL normalised, userinfo split out and registered as a secret, failures that say exactly which variable to set. |
| `cli` | `AppSpec` / `CommandSpec` / `FlagSpec` (data), the flag-parsing helpers, help text, and the dispatcher: the `Handlers` trait, `Outcome`, `run` and `execute`. |
| `proc` | Run a subprocess with a timeout and an output cap, redact what it prints, and refuse any argv that holds a registered secret. |
| `http` | (feature `http`) A blocking client: bearer token registered as a secret, plain `http://` (any scheme case) refused unless allowed, every failure an `AxiError` of the right kind. Error codes are a closed set of literals a tool declares in its fault table; `http::CODES` lists them and the module docs say when each is produced. |

## How a tool is built

A tool has a data half and a hand-written half, and the toolkit owns everything between them.

1. **Describe the tool as data**: a `const AppSpec` listing commands, flags, positionals and help.
2. **Implement `Handlers`**: `command(&CommandSpec, &Parsed) -> Result<String, AxiError>` does the
   work and returns a document, or an error carrying its recovery. Optionally `resolve_context`
   (load configuration once, before the command's own flags are read) and `home` (a bare invocation).
3. **Call `execute`** from `main`: it parses argv, dispatches, renders errors as blocks with the
   right exit status, and passes stdout through the redactor.

```rust
use axi_toolkit::cli::{execute, AppSpec, CommandSpec, Handlers, Parsed};
use axi_toolkit::errors::AxiError;
use axi_toolkit::render::view::Views;

const APP: AppSpec = AppSpec {
    bin: "hello-axi", version: "0.1.0", noun: None, summary: "Say hello.", epilog: "",
    commands: &[CommandSpec::new("greet", "greet")],
    globals: &[], refusal: None, help: None,
};

struct Hello;
impl Handlers for Hello {
    fn command(&mut self, _: &CommandSpec, _: &Parsed) -> Result<String, AxiError> {
        Ok("greeting: hello".into())
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    std::process::exit(execute(&APP, &argv, &mut Hello, &Views::default(), &mut std::io::stdout()));
}
```

Runnable examples: `examples/hello_axi.rs` (flags, positionals, a failure with recovery) and
`examples/http_probe.rs` (environment credentials plus the HTTP client; needs `--features http`).

```sh
cargo run --example hello_axi -- greet Ada --shout
PROBE_URL=https://api.example.com PROBE_TOKEN=... cargo run --features http --example http_probe -- get /v1/status
```

### Recovery is data

A failure never carries a pre-formatted "try this". It carries `Recovery` values: *run these
words*, *set this variable*, *choose one of these*. They contain no tool name; a `{tool}` slot is
filled when printed. The same value renders as `Run `my-axi doctor` to verify the connection` on a
terminal and as a sentence in prose, and `render::cli::parse` is the inverse of `line`. That is
what lets one error definition serve a CLI, an MCP server and a test.

### Where generated code plugs in

The crate has no code generator, but it is shaped for one. Everything a generator knows
statically (command names, aliases, flags and their kinds, positional counts, usage, examples,
help text, the recovery attached to each known failure) is `const` data in an `AppSpec`.
Everything it cannot know (what a command does) is behind a single trait method. Generated code
therefore:

* emits the `AppSpec` / `CommandSpec` / `FlagSpec` constants, and
* emits a typed adapter that implements `Handlers::command`: `match command.name`, pull typed
  values out of `Parsed` (`args.uint("--limit")`, `args.positional(0)`), call the hand-written
  function for that command, and return its `Result<String, AxiError>`.

The hand-written functions never see argv, help, exit codes or redaction. `Outcome`
(`Output` / `Verbatim` / `Failure`) is what `run` returns when a caller wants the result without
printing it, such as a test or an embedding host; `execute` is `run` plus rendering and the
redaction boundary.

## The conformance story

The Python library is the reference. It writes a language-neutral **conformance pack**: JSON files
describing recovery rendering, errors and exit codes, credential handling, redaction and the TOON
fixtures. Every implementation runs the same files.

* The repository's root `conformance/` is read **in place** (`../conformance` from this
  directory); there is no copy to refresh. Its `checksums.txt` is verified by the tests. The
  pack's sample tool names are illustrative fixtures and are kept exactly as written.
* The official TOON spec v4.4 encode fixtures (160 cases) are found through the pack's
  `toon-spec.json`, which points into the Python package that ships them, with their checksums,
  licence and provenance. `tests/fixtures/toon-4.1/` holds the older spec v4.1.1 set
  (179 cases) a downstream Rust prototype was built against; the encoder must keep passing it.
* `tests/conformance_toon.rs` runs both fixture sets, asserts the case counts so a fixture that
  stops being collected fails instead of shrinking the score, and verifies every checksum, so a
  fixture edited to make a failing encoder pass is a visible failure. It carries its own
  SHA-256; `serde_json` is a dev-dependency only.
* `tests/conformance_contract.rs` runs recovery (every source line must parse, render back
  byte for byte, and render as prose), render rules, errors, credentials and redaction.
* `tests/differential.rs` asks the Python library itself, over thousands of generated values and
  recoveries, and requires identical bytes. It is opt-in:

  ```sh
  AXI_PYTHON_REFERENCE=<repo-root>/python cargo test --test differential
  ```

  Without the variable the tests report a skip and pass. `tests/oracle/oracle.py` is the small
  script that runs the reference.

### Known divergences, on purpose

* **Exponent form.** Python (and spec v4.4) write `1e-07`; the JavaScript library writes `1e-7`.
  `Dialect::Spec` matches Python, `Dialect::ToonJs2` matches JavaScript.
* **Large integral floats.** Python (and spec v4.4) write `2**63` as its exact integer,
  `9223372036854775808`; the JavaScript library writes its shortest round-trip digits,
  `9223372036854776000`. `Dialect::Spec` matches Python, `Dialect::ToonJs2` matches JavaScript.
* **Truncation unit.** `render::view::truncate` counts UTF-16 code units, as JavaScript's
  `String.length` does, so it cuts where the TypeScript tools cut. A cut inside a surrogate pair
  leaves U+FFFD, as it would on a JavaScript stdout.
* **Regular expressions.** The pack declares redaction patterns as ECMAScript regexes. This crate
  has no regex engine, so a tool registers a `redact::Pattern` (a keyed prefix plus a value
  character class, or a closure); the conformance test maps each pack pattern to its Rust shape
  and fails on one it does not know.
* **Help text** ends with a newline when printed, like any other output.

## Development

```sh
cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-features
RUSTDOCFLAGS="-D warnings" cargo doc --no-deps --all-features
```

The `Cargo.toml` declares a one-member workspace so the crate builds on its own even when
checked out inside a larger tree.

## Licence

MIT; see `LICENSE`. The TOON fixtures are MIT under their own licence file.
