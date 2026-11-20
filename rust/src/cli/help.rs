//! Help pages generated from a spec, in the compact shape the AXI tools print.

use super::spec::{AppSpec, CommandSpec, FlagKind, FlagSpec};

/// How a flag reads in a help page: `--blocked`, `--repo <name>`, `--state <a|b>`.
fn flag_text(flag: &FlagSpec) -> String {
    match flag.kind {
        FlagKind::Bool => flag.name.to_string(),
        FlagKind::Choice(words) if flag.placeholder.is_empty() => {
            format!("{} <{}>", flag.name, words.join("|"))
        }
        _ if flag.placeholder.is_empty() => format!("{} <value>", flag.name),
        _ => format!("{} {}", flag.name, flag.placeholder),
    }
}

/// The top-level help: usage, the commands (with their aliases), the flags every command takes,
/// and the epilog. No trailing newline.
///
/// ```text
/// usage: tool <command> [args] [flags]
/// A line of description.
/// commands[2]:
///   show (alias view), list
/// flags[2]:
///   --file <path> (after command), --help, -v/-V/--version
/// ```
pub fn top_help(spec: &AppSpec) -> String {
    if let Some(text) = spec.help {
        return text.to_string();
    }
    let mut lines = vec![format!("usage: {} <command> [args] [flags]", spec.bin)];
    if !spec.summary.is_empty() {
        lines.push(spec.summary.to_string());
    }
    let commands: Vec<String> = spec
        .commands
        .iter()
        .map(|c| match c.aliases {
            [] => c.name.to_string(),
            [one] => format!("{} (alias {one})", c.name),
            many => format!("{} (aliases {})", c.name, many.join(", ")),
        })
        .collect();
    lines.push(format!("commands[{}]:", commands.len()));
    lines.push(format!("  {}", commands.join(", ")));
    let mut flags: Vec<String> = spec
        .globals
        .iter()
        .map(|f| format!("{} (after command)", flag_text(f)))
        .collect();
    flags.push("--help".to_string());
    flags.push("-v/-V/--version".to_string());
    lines.push(format!("flags[{}]:", flags.len()));
    lines.push(format!("  {}", flags.join(", ")));
    if !spec.epilog.is_empty() {
        lines.push(spec.epilog.to_string());
    }
    lines.join("\n")
}

/// One command's help: usage, aliases, summary, flags and examples. No trailing newline.
pub fn command_help(spec: &AppSpec, command: &CommandSpec) -> String {
    if let Some(text) = command.help {
        return text.to_string();
    }
    let mut lines = vec![format!("usage: {} {}", spec.bin, command.usage)];
    if !command.aliases.is_empty() {
        lines.push(format!("aliases: {}", command.aliases.join(", ")));
    }
    if !command.summary.is_empty() {
        lines.push(command.summary.to_string());
    }
    if !command.flags.is_empty() {
        lines.push("flags:".to_string());
        let flags: Vec<String> = command.flags.iter().map(flag_text).collect();
        lines.push(format!("  {}", flags.join(", ")));
    }
    if !command.examples.is_empty() {
        lines.push("examples:".to_string());
        for example in command.examples {
            lines.push(format!("  {} {example}", spec.bin));
        }
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    const SHOW: CommandSpec = CommandSpec {
        aliases: &["view"],
        flags: &[FlagSpec::bool("--full")],
        min_positionals: 1,
        max_positionals: 1,
        examples: &["show a-1", "show a-1 --full"],
        ..CommandSpec::new("show", "show <id> [--full]")
    };
    const APP: AppSpec = AppSpec {
        bin: "tool",
        version: "1.0.0",
        noun: None,
        summary: "Read things.",
        epilog: "",
        commands: &[SHOW],
        globals: &[FlagSpec::text("--file", "<path>")],
        refusal: None,
        help: None,
    };

    #[test]
    fn the_top_page_lists_commands_and_flags() {
        assert_eq!(
            top_help(&APP),
            "usage: tool <command> [args] [flags]\nRead things.\ncommands[1]:\n  show (alias view)\n\
             flags[3]:\n  --file <path> (after command), --help, -v/-V/--version"
        );
    }

    #[test]
    fn a_command_page_lists_flags_and_examples() {
        assert_eq!(
            command_help(&APP, &SHOW),
            "usage: tool show <id> [--full]\naliases: view\nflags:\n  --full\nexamples:\n  tool show a-1\n  tool show a-1 --full"
        );
    }
}
