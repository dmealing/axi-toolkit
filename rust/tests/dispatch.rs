//! The dispatcher end to end: argv in, bytes and an exit status out.

use axi_toolkit::cli::{execute, run, AppSpec, CommandSpec, FlagSpec, Handlers, Outcome, Parsed};
use axi_toolkit::errors::{AxiError, Recovery};
use axi_toolkit::redact;
use axi_toolkit::render::view::Views;

const SHOW_FLAGS: &[FlagSpec] = &[FlagSpec::bool("--full"), FlagSpec::uint("--limit")];
const APP: AppSpec = AppSpec {
    bin: "demo-axi",
    version: "1.2.3",
    noun: Some("item"),
    summary: "A demo tool.",
    epilog: "",
    commands: &[
        CommandSpec {
            aliases: &["get"],
            flags: SHOW_FLAGS,
            min_positionals: 1,
            max_positionals: 1,
            ..CommandSpec::new("show", "show <id> [--full] [--limit <n>]")
        },
        CommandSpec::new("leak", "leak"),
        CommandSpec::new("boom", "boom"),
    ],
    globals: &[FlagSpec::text("--profile", "<name>")],
    refusal: None,
    help: None,
};

#[derive(Default)]
struct Demo {
    profile: Option<String>,
}

impl Handlers for Demo {
    fn resolve_context(&mut self, globals: &Parsed) -> Result<(), AxiError> {
        self.profile = globals.text("--profile").map(str::to_string);
        Ok(())
    }
    fn command(&mut self, command: &CommandSpec, args: &Parsed) -> Result<String, AxiError> {
        match command.name {
            "show" => Ok(format!(
                "id: {}\nfull: {}\nlimit: {}\nprofile: {}",
                args.positional(0).unwrap(),
                args.bool("--full"),
                args.uint("--limit")
                    .map_or("none".into(), |n| n.to_string()),
                self.profile.as_deref().unwrap_or("none"),
            )),
            "leak" => Ok("token: leaky-dispatch-secret-12345".into()),
            _ => Err(AxiError::not_found("no such thing")
                .and_recover(Recovery::run(["show", "1"]).with_purpose("to see one that exists"))),
        }
    }
}

fn argv(words: &[&str]) -> Vec<String> {
    words.iter().map(|w| w.to_string()).collect()
}

fn exec(words: &[&str]) -> (String, i32) {
    let mut out = Vec::new();
    let code = execute(
        &APP,
        &argv(words),
        &mut Demo::default(),
        &Views::default(),
        &mut out,
    );
    (String::from_utf8(out).unwrap(), code)
}

#[test]
fn flags_positionals_aliases_and_the_optional_noun() {
    let want = "id: 7\nfull: true\nlimit: 3\nprofile: work\n";
    assert_eq!(
        exec(&["show", "7", "--full", "--limit", "3", "--profile", "work"]),
        (want.into(), 0)
    );
    assert_eq!(
        exec(&["item", "get", "--profile=work", "7", "--limit=3", "--full"]),
        (want.into(), 0)
    );
}

#[test]
fn help_and_version_are_verbatim_with_a_trailing_newline() {
    let (help, code) = exec(&["--help"]);
    assert_eq!(code, 0);
    assert!(help.starts_with("usage: demo-axi "), "{help}");
    assert!(help.ends_with('\n'));
    assert_eq!(exec(&["--version"]), ("1.2.3\n".into(), 0));
    assert!(exec(&["show", "--help"]).0.contains("show <id>"));
    // A bare invocation with no home view prints the help.
    assert_eq!(exec(&[]).0, help);
}

#[test]
fn usage_errors_exit_2_and_say_why() {
    for words in [
        &["nope"][..],
        &["show"],
        &["show", "1", "--limit", "x"],
        &["--full", "show"],
        &["show", "1", "--wat"],
    ] {
        let (out, code) = exec(words);
        assert_eq!(code, 2, "{words:?}: {out}");
        assert!(out.starts_with("error: "), "{out}");
    }
}

#[test]
fn a_command_failure_is_an_error_block_with_its_recovery_and_exit_1() {
    let (out, code) = exec(&["boom"]);
    assert_eq!(code, 1);
    assert!(out.contains("error: no such thing"), "{out}");
    assert!(
        out.contains("Run `demo-axi show 1` to see one that exists"),
        "{out}"
    );
}

#[test]
fn stdout_is_redacted_at_the_boundary() {
    redact::register_secret("leaky-dispatch-secret-12345");
    let (out, code) = exec(&["leak"]);
    assert_eq!((out.as_str(), code), ("token: <redacted>\n", 0));
}

#[test]
fn run_returns_the_outcome_without_printing() {
    let outcome = run(&APP, &argv(&["show", "1"]), &mut Demo::default());
    assert!(matches!(outcome, Outcome::Output(_)));
    let outcome = run(&APP, &argv(&["boom"]), &mut Demo::default());
    assert!(matches!(outcome, Outcome::Failure(e) if e.exit_code() == 1));
}
