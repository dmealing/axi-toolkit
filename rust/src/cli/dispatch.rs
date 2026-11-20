//! The dispatcher: argv in, an [`Outcome`] out, with the handlers behind a seam.

use super::flags::{
    parse_value, require_flag_value, require_positionals, take_bool_flag, take_flag,
};
use super::help::{command_help, top_help};
use super::spec::{AppSpec, CommandSpec, FlagKind, FlagSpec, FlagValue, Parsed};
use crate::errors::{AxiError, ErrorKind, Recovery, CODE_UNSUPPORTED};
use crate::redact;
use crate::render::view::Views;
use std::io::Write;

/// What a run produced. `Output` and `Failure` are rendered by the caller (an output gets a
/// trailing newline); `Verbatim` is printed exactly as given.
#[derive(Debug, Clone, PartialEq)]
pub enum Outcome {
    /// A command's document; printed with a trailing newline.
    Output(String),
    /// Text printed exactly as given (help, version).
    Verbatim(String),
    /// A failure; printed as an error block on stdout, with the error's exit status.
    Failure(AxiError),
}

impl Outcome {
    /// The text to write to stdout and the process exit status, for the tool named by `spec`.
    pub fn render(&self, spec: &AppSpec, views: &Views) -> (String, i32) {
        match self {
            Outcome::Output(s) => (format!("{s}\n"), 0),
            Outcome::Verbatim(s) => (s.clone(), 0),
            Outcome::Failure(e) => (format!("{}\n", views.error(e, spec.bin)), e.exit_code()),
        }
    }
}

/// The hand-written half of a tool: what each command does.
pub trait Handlers {
    /// The document for a bare invocation (no command), or `None` to print the top-level help.
    fn home(&mut self) -> Option<Result<String, AxiError>> {
        None
    }

    /// Called once the global flags are read and before the command's own are, so context
    /// (configuration, a backend) can be resolved -- and a failure there reported -- first.
    ///
    /// # Errors
    /// Whatever fails to resolve; it is reported like any command failure.
    fn resolve_context(&mut self, _globals: &Parsed) -> Result<(), AxiError> {
        Ok(())
    }

    /// Run one command. `command` is the canonical spec (aliases already resolved) and `args`
    /// holds its parsed flags and positionals.
    ///
    /// # Errors
    /// The command's failure, rendered as an error block.
    fn command(&mut self, command: &CommandSpec, args: &Parsed) -> Result<String, AxiError>;
}

fn refusal(spec: &AppSpec, command: &str) -> Option<AxiError> {
    let r = spec.refusal?;
    r.commands.contains(&command).then(|| {
        AxiError::new(ErrorKind::Axi, r.message.replace("{command}", command))
            .with_code(CODE_UNSUPPORTED)
            .and_recover(Recovery::Note {
                text: r.suggestion.to_string(),
            })
    })
}

/// Run one invocation: `argv` excludes the program name.
pub fn run<H: Handlers>(spec: &AppSpec, argv: &[String], handlers: &mut H) -> Outcome {
    match run_inner(spec, argv, handlers) {
        Ok(outcome) => outcome,
        Err(e) => Outcome::Failure(e),
    }
}

fn run_inner<H: Handlers>(
    spec: &AppSpec,
    argv: &[String],
    handlers: &mut H,
) -> Result<Outcome, AxiError> {
    // The noun is optional: `tool task show x` is `tool show x`.
    let argv = match (spec.noun, argv.first()) {
        (Some(noun), Some(first)) if first == noun => &argv[1..],
        _ => argv,
    };
    if argv.len() == 1 && argv[0] == "--help" {
        return Ok(Outcome::Verbatim(format!("{}\n", top_help(spec))));
    }
    if argv.len() == 1 && matches!(argv[0].as_str(), "-v" | "-V" | "--version") {
        return Ok(Outcome::Verbatim(format!("{}\n", spec.version)));
    }
    let Some(word) = argv.first() else {
        return match handlers.home() {
            Some(result) => Ok(Outcome::Output(result?)),
            None => Ok(Outcome::Verbatim(format!("{}\n", top_help(spec)))),
        };
    };
    if word.starts_with('-') {
        return Err(AxiError::usage("Flags must come after the command")
            .and_recover(Recovery::run(["<command>", "[args]", "[flags]"]))
            .and_recover(
                Recovery::retry(word.as_str())
                    .with_lead("Move")
                    .with_purpose("after the command instead of before it"),
            ));
    }
    let args = &argv[1..];
    let implemented = spec.find(word);
    if args.iter().any(|a| a == "--help") {
        if let Some(command) = implemented {
            return Ok(Outcome::Verbatim(format!(
                "{}\n",
                command_help(spec, command)
            )));
        }
    }
    if let Some(error) = refusal(spec, word) {
        return Err(error);
    }
    let Some(command) = implemented else {
        return Err(
            AxiError::usage(format!("Unknown command: {word}")).and_recover(
                Recovery::retry("--help")
                    .with_lead("Run")
                    .with_purpose("to see available commands"),
            ),
        );
    };
    let (globals, rest) = parse_globals(spec.globals, args)?;
    handlers.resolve_context(&globals)?;
    let parsed = parse_command(command, &rest)?;
    Ok(Outcome::Output(handlers.command(command, &parsed)?))
}

/// Remove the global flags from `args`; the rest is the command's own.
///
/// # Errors
/// A flag without a value, or a value its kind refuses.
pub fn parse_globals(
    globals: &'static [FlagSpec],
    args: &[String],
) -> Result<(Parsed, Vec<String>), AxiError> {
    let mut parsed = Parsed::default();
    let mut stripped = Vec::new();
    let mut i = 0;
    'args: while i < args.len() {
        let arg = args[i].as_str();
        for flag in globals {
            if flag.kind == FlagKind::Bool && arg == flag.name {
                set(&mut parsed, flag.name, FlagValue::Bool(true));
                i += 1;
                continue 'args;
            }
            if flag.kind == FlagKind::Bool {
                continue;
            }
            if arg == flag.name {
                let value = require_flag_value(args, i, flag.name)?;
                set(&mut parsed, flag.name, parse_value(flag, value)?);
                i += 2;
                continue 'args;
            }
            if let Some(value) = arg
                .strip_prefix(flag.name)
                .and_then(|r| r.strip_prefix('='))
            {
                set(
                    &mut parsed,
                    flag.name,
                    parse_value(flag, value.to_string())?,
                );
                i += 1;
                continue 'args;
            }
        }
        stripped.push(args[i].clone());
        i += 1;
    }
    Ok((parsed, stripped))
}

/// Later occurrences of a global flag overwrite earlier ones.
fn set(parsed: &mut Parsed, name: &'static str, value: FlagValue) {
    parsed.flags.retain(|(n, _)| *n != name);
    parsed.flags.push((name, value));
}

/// Read a command's arguments (global flags already removed), flag by flag in the order the
/// spec lists them, then the positionals.
///
/// # Errors
/// An unknown flag, a refused value, or the wrong number of positionals.
pub fn parse_command(command: &CommandSpec, raw: &[String]) -> Result<Parsed, AxiError> {
    let mut args: Vec<String> = raw.to_vec();
    let mut parsed = Parsed::default();
    for flag in command.flags {
        if flag.kind == FlagKind::Bool {
            if take_bool_flag(&mut args, flag.name) {
                parsed.flags.push((flag.name, FlagValue::Bool(true)));
            }
        } else if let Some(value) = take_flag(&mut args, flag.name)? {
            parsed.flags.push((flag.name, parse_value(flag, value)?));
        }
    }
    parsed.positionals = require_positionals(
        &args,
        command.min_positionals,
        command.max_positionals,
        command.usage,
    )?;
    Ok(parsed)
}

/// Run one invocation and write its stdout, through the redaction boundary.
///
/// Returns the process exit status. A closed pipe is not an error here.
pub fn execute<H: Handlers>(
    spec: &AppSpec,
    argv: &[String],
    handlers: &mut H,
    views: &Views,
    stdout: &mut impl Write,
) -> i32 {
    let (text, code) = run(spec, argv, handlers).render(spec, views);
    let _ = stdout.write_all(redact::redact(&text).as_bytes());
    let _ = stdout.flush();
    code
}
