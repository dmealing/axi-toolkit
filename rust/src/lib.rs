//! Shared toolkit for Agent eXperience Interface (AXI) command-line tools.
//!
//! A strict TOON encoder, errors that carry recovery as **data**, a redaction boundary,
//! environment-only credentials, a flag parser and dispatcher, and (behind features and
//! modules of their own) an HTTPS client and a subprocess helper. The crate is `std`-only
//! except for the optional `http` feature, which pulls in `ureq` over `rustls`.
//!
//! It is a peer of the Python `axi-toolkit` and its TypeScript port: the same contract, held to
//! the same conformance files (`conformance/`), with the Python library as the byte-for-byte
//! oracle for the TOON encoder and the renderers. See the README for the layout and for how a
//! tool is built on it.
//!
//! | Module | What it is |
//! | --- | --- |
//! | [`toon`] | A strict TOON encoder (spec v4.4), with the `@toon-format/toon` 2.3 dialect. |
//! | [`errors`] | [`errors::AxiError`], codes, exit statuses, fault classes, the closed recovery vocabulary. |
//! | [`render`] | Recovery intent as shell lines ([`render::cli`]) and sentences ([`render::prose`]); stdout views and truncation ([`render::view`]). |
//! | [`redact`] | Literal secrets and credential shapes, removed from anything printed. |
//! | [`envconfig`] | Environment-only credentials, URL normalisation, userinfo splitting. |
//! | [`cli`] | Flag parser, help rendering, and the [`cli::Handlers`] / [`cli::Outcome`] / [`cli::run`] dispatcher. |
//! | [`proc`] | Run a subprocess with a timeout, capture its output, redact it, keep secrets off argv. |
//! | `http` | (feature `http`) An HTTPS client with timeouts that maps failures onto [`errors::AxiError`]. |
//!
//! ```
//! use axi_toolkit::cli::{run, AppSpec, CommandSpec, Handlers, Outcome, Parsed};
//! use axi_toolkit::errors::AxiError;
//!
//! const APP: AppSpec = AppSpec {
//!     bin: "hello",
//!     version: "0.1.0",
//!     noun: None,
//!     summary: "Say hello.",
//!     epilog: "",
//!     commands: &[CommandSpec::new("greet", "greet")],
//!     globals: &[],
//!     refusal: None,
//!     help: None,
//! };
//!
//! struct Hello;
//! impl Handlers for Hello {
//!     fn command(&mut self, _: &CommandSpec, _: &Parsed) -> Result<String, AxiError> {
//!         Ok("greeting: hello".into())
//!     }
//! }
//!
//! let out = run(&APP, &["greet".to_string()], &mut Hello);
//! assert_eq!(out, Outcome::Output("greeting: hello".into()));
//! ```

pub mod cli;
pub mod envconfig;
pub mod errors;
#[cfg(feature = "http")]
pub mod http;
pub mod proc;
mod pystr;
pub mod redact;
pub mod render;
pub mod toon;
