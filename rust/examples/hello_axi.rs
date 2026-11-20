//! A tiny AXI tool: `hello-axi greet [NAME] [--shout]` and `hello-axi fail`.
//!
//! The shape every tool built on this crate has: a data-driven [`AppSpec`] (what a code
//! generator would emit), a [`Handlers`] implementation (the hand-written half), and a `main`
//! that hands both to [`execute`]. Try:
//!
//! ```text
//! cargo run --example hello_axi -- greet Ada --shout
//! cargo run --example hello_axi -- fail ; echo "exit $?"
//! cargo run --example hello_axi -- --help
//! ```

use axi_toolkit::cli::{execute, AppSpec, CommandSpec, FlagSpec, Handlers, Parsed};
use axi_toolkit::errors::{AxiError, Recovery};
use axi_toolkit::render::view::{output, Views};
use axi_toolkit::toon::Value;

const GREET_FLAGS: &[FlagSpec] = &[FlagSpec::bool("--shout")];

const APP: AppSpec = AppSpec {
    bin: "hello-axi",
    version: "0.1.0",
    noun: None,
    summary: "Greet people, the agent-friendly way.",
    epilog: "",
    commands: &[
        CommandSpec {
            flags: GREET_FLAGS,
            max_positionals: 1,
            summary: "Greet NAME (default: world)",
            ..CommandSpec::new("greet", "greet [NAME] [--shout]")
        },
        CommandSpec::new("fail", "fail"),
    ],
    globals: &[],
    refusal: None,
    help: None,
};

struct Hello;

impl Handlers for Hello {
    fn command(&mut self, command: &CommandSpec, args: &Parsed) -> Result<String, AxiError> {
        let views = Views::default();
        match command.name {
            "greet" => {
                let name = args.positional(0).unwrap_or("world");
                let text = format!("hello, {name}");
                let text = if args.bool("--shout") {
                    text.to_uppercase()
                } else {
                    text
                };
                Ok(output(vec![
                    views.detail(
                        "greeting",
                        Value::object([("text", Value::from(text.as_str()))]),
                    ),
                    views.help(&["Run `hello-axi greet --shout` to raise your voice".to_string()]),
                ]))
            }
            // A failure carries its recovery as data; the error block renders it as `help[]` lines.
            "fail" => Err(AxiError::general("this command always fails")
                .and_recover(Recovery::run(["greet"]).with_purpose("to see a command that works"))),
            other => unreachable!("the spec lists no command {other}"),
        }
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let code = execute(
        &APP,
        &argv,
        &mut Hello,
        &Views::default(),
        &mut std::io::stdout(),
    );
    std::process::exit(code);
}
