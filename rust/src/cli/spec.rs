//! The data a tool declares and the value a parse produces.

/// What a flag's value is, and so how it is validated.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FlagKind {
    /// A switch with no value. Only its first occurrence is read.
    Bool,
    /// `--flag value` or `--flag=value`: non-empty and on a single line.
    Text,
    /// A non-negative integer no larger than 2^53 - 1 (a JavaScript safe integer).
    Uint,
    /// One of a closed set of words.
    Choice(&'static [&'static str]),
    /// A comma-separated list of names, each from the closed set; blanks and repeats dropped.
    Columns(&'static [&'static str]),
}

/// One flag a command (or the whole tool) accepts.
#[derive(Debug, Clone, Copy)]
pub struct FlagSpec {
    /// The flag with its dashes: `"--state"`.
    pub name: &'static str,
    /// What its value is.
    pub kind: FlagKind,
    /// The placeholder shown in help (`"<name>"`); empty to derive one from the kind.
    pub placeholder: &'static str,
}

impl FlagSpec {
    /// A switch.
    pub const fn bool(name: &'static str) -> FlagSpec {
        FlagSpec {
            name,
            kind: FlagKind::Bool,
            placeholder: "",
        }
    }

    /// A single-line text value shown as `placeholder`.
    pub const fn text(name: &'static str, placeholder: &'static str) -> FlagSpec {
        FlagSpec {
            name,
            kind: FlagKind::Text,
            placeholder,
        }
    }

    /// A non-negative integer.
    pub const fn uint(name: &'static str) -> FlagSpec {
        FlagSpec {
            name,
            kind: FlagKind::Uint,
            placeholder: "<n>",
        }
    }

    /// One of `words`.
    pub const fn choice(name: &'static str, words: &'static [&'static str]) -> FlagSpec {
        FlagSpec {
            name,
            kind: FlagKind::Choice(words),
            placeholder: "",
        }
    }

    /// A list of names drawn from `available`.
    pub const fn columns(name: &'static str, available: &'static [&'static str]) -> FlagSpec {
        FlagSpec {
            name,
            kind: FlagKind::Columns(available),
            placeholder: "<a,b,c>",
        }
    }
}

/// A command a tool implements.
#[derive(Debug, Clone, Copy)]
pub struct CommandSpec {
    /// The canonical name, which [`crate::cli::Handlers::command`] receives.
    pub name: &'static str,
    /// Other words that name the same command.
    pub aliases: &'static [&'static str],
    /// The usage text after the tool's name: `"show <id> [--full]"`.
    pub usage: &'static str,
    /// A line or two of description for `--help`.
    pub summary: &'static str,
    /// The flags the command takes, read in this order.
    pub flags: &'static [FlagSpec],
    /// The fewest positional arguments.
    pub min_positionals: usize,
    /// The most positional arguments.
    pub max_positionals: usize,
    /// Example invocations after the tool's name, shown in `--help`.
    pub examples: &'static [&'static str],
    /// Help text printed verbatim instead of the generated page.
    pub help: Option<&'static str>,
}

impl CommandSpec {
    /// A command taking no flags and no positionals; chain the struct fields for more.
    pub const fn new(name: &'static str, usage: &'static str) -> CommandSpec {
        CommandSpec {
            name,
            aliases: &[],
            usage,
            summary: "",
            flags: &[],
            min_positionals: 0,
            max_positionals: 0,
            examples: &[],
            help: None,
        }
    }

    /// Whether `word` names this command.
    pub fn answers_to(&self, word: &str) -> bool {
        self.name == word || self.aliases.contains(&word)
    }
}

/// Commands the tool knows of and deliberately refuses: a partial port of another tool says so
/// instead of failing as "unknown command".
#[derive(Debug, Clone, Copy)]
pub struct Refusal {
    /// The refused command words.
    pub commands: &'static [&'static str],
    /// The message, with `{command}` standing for the word typed.
    pub message: &'static str,
    /// Where to go instead, as one line of advice.
    pub suggestion: &'static str,
}

/// A whole tool's surface.
#[derive(Debug, Clone, Copy)]
pub struct AppSpec {
    /// The tool's name, as it appears in recovery lines and usage.
    pub bin: &'static str,
    /// What `--version` prints.
    pub version: &'static str,
    /// A noun that may precede the command (`tool task show x` is `tool show x`).
    pub noun: Option<&'static str>,
    /// A line of description for the top-level `--help`.
    pub summary: &'static str,
    /// Lines after the flags in the top-level `--help`.
    pub epilog: &'static str,
    /// The implemented commands.
    pub commands: &'static [CommandSpec],
    /// Flags read before a command's own, wherever they sit after the command word. Only
    /// [`FlagKind::Bool`] and the value kinds are read; each is shown `(after command)`.
    pub globals: &'static [FlagSpec],
    /// Commands refused with [`crate::errors::CODE_UNSUPPORTED`].
    pub refusal: Option<Refusal>,
    /// Top-level help printed verbatim instead of the generated page.
    pub help: Option<&'static str>,
}

impl AppSpec {
    /// The command a word names.
    pub fn find(&self, word: &str) -> Option<&CommandSpec> {
        self.commands.iter().find(|c| c.answers_to(word))
    }
}

/// One parsed flag value.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FlagValue {
    /// A switch that was present.
    Bool(bool),
    /// A [`FlagKind::Text`] value.
    Text(String),
    /// A [`FlagKind::Uint`] value.
    Uint(u64),
    /// A [`FlagKind::Choice`] value, one of the declared words.
    Choice(String),
    /// A [`FlagKind::Columns`] value: names in the order given, without repeats.
    Columns(Vec<String>),
}

/// The result of parsing: the flags that were given, in declaration order, and the positionals.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Parsed {
    pub(crate) flags: Vec<(&'static str, FlagValue)>,
    pub(crate) positionals: Vec<String>,
}

impl Parsed {
    /// The value of `name` (with dashes), if it was given.
    pub fn get(&self, name: &str) -> Option<&FlagValue> {
        self.flags.iter().find(|(n, _)| *n == name).map(|(_, v)| v)
    }

    /// Whether the switch `name` was present.
    pub fn bool(&self, name: &str) -> bool {
        matches!(self.get(name), Some(FlagValue::Bool(true)))
    }

    /// The text or choice value of `name`.
    pub fn text(&self, name: &str) -> Option<&str> {
        match self.get(name) {
            Some(FlagValue::Text(s) | FlagValue::Choice(s)) => Some(s),
            _ => None,
        }
    }

    /// The integer value of `name`.
    pub fn uint(&self, name: &str) -> Option<u64> {
        match self.get(name) {
            Some(FlagValue::Uint(n)) => Some(*n),
            _ => None,
        }
    }

    /// The names listed by the columns flag `name`; empty when it was not given.
    pub fn columns(&self, name: &str) -> &[String] {
        match self.get(name) {
            Some(FlagValue::Columns(c)) => c,
            _ => &[],
        }
    }

    /// The positional arguments, in order.
    pub fn positionals(&self) -> &[String] {
        &self.positionals
    }

    /// The `i`th positional argument.
    pub fn positional(&self, i: usize) -> Option<&str> {
        self.positionals.get(i).map(String::as_str)
    }
}
