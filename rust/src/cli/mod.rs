//! The command-line surface: flag parsing, help rendering, and the dispatcher.
//!
//! A tool declares its surface as data -- an [`AppSpec`] naming [`CommandSpec`]s and
//! [`FlagSpec`]s -- and implements [`Handlers`]; [`run`] does the rest: it resolves the optional
//! noun and aliases, answers `--help` and `--version`, refuses what the tool declares it
//! refuses, reads the global flags, parses the command's own flags and positionals into a
//! [`Parsed`], and calls the handler. Every failure is an [`crate::errors::AxiError`] whose
//! recovery is data, rendered at the output boundary by [`execute`].
//!
//! The pieces below [`run`] are public too ([`flags`]): the flag helpers a hand-written parser
//! wants (`take_flag`, `parse_optional_uint`, `require_positionals`, ...) are real runtime code
//! rather than text a generator embeds in every tool.
//!
//! # Generated code targets this seam
//!
//! A code generator (the MetaObjects one, say) has two easy things to emit against this module:
//! a `const` [`AppSpec`] holding the command table, help text and flag kinds, and a typed trait
//! with one method per command plus a small adapter implementing [`Handlers`] by matching on
//! [`CommandSpec::name`] and reading typed arguments out of [`Parsed`]. Because the spec is
//! plain data and `command` is the only required method, the generated half owns the
//! *surface* and the hand-written half owns the *behaviour*, and neither can lose a command
//! without failing to compile. `examples/hello_axi.rs` shows the adapter shape by hand.

mod dispatch;
pub mod flags;
mod help;
mod spec;

pub use dispatch::{execute, run, Handlers, Outcome};
pub use help::{command_help, top_help};
pub use spec::{AppSpec, CommandSpec, FlagKind, FlagSpec, FlagValue, Parsed, Refusal};
