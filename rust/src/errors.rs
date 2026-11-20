//! The AXI error contract: a code, a fault class, and recovery carried as data.
//!
//! **Recovery is structured intent, never a rendered line.** A tool that bakes
//! ``Run `my-tool area list` to see the areas`` into the point where the error is raised owns
//! that sentence forever. Here the same fact is
//! [`Recovery::run`]`(["area", "list"]).with_purpose("to see the areas that exist")`, and the
//! tool's name arrives when somebody renders it: [`crate::render::cli`] for a shell,
//! [`crate::render::prose`] for a caller that will never run one.
//!
//! The vocabulary is closed (`run`, `retry`, `set_env`, `choose`, `note`), and a recovery
//! survives [`Recovery::to_value`] / [`Recovery::from_value`] unchanged, so it can cross a
//! process boundary as JSON. [`Recovery::note`] is the one kind that may name a tool, as the
//! placeholder `{tool}` and never as the name; [`Recovery::mentions_tool`] is how a test proves it.
//!
//! Every behaviour here is held to `conformance/errors.json` and `conformance/render-rules.json`,
//! which the Python reference writes.
//!
//! ```
//! use axi_toolkit::errors::{AxiError, Recovery};
//! use axi_toolkit::render::cli;
//!
//! let error = AxiError::not_found("no area named 'nowhere'")
//!     .with_code("NO_SUCH_AREA")
//!     .with_recovery(vec![
//!         Recovery::run(["area", "list"]).with_purpose("to see the areas that exist"),
//!     ]);
//! assert_eq!(
//!     cli::lines(&error.recovery, "my-tool"),
//!     ["Run `my-tool area list` to see the areas that exist"]
//! );
//! assert_eq!(error.exit_code(), 1);
//! ```

use crate::toon::Value;
use std::fmt;

/// Process exit status for success.
pub const EXIT_OK: i32 = 0;
/// Process exit status for a failed command.
pub const EXIT_ERROR: i32 = 1;
/// Process exit status for a malformed invocation.
pub const EXIT_USAGE: i32 = 2;

/// The code the flag parser and dispatcher attach to a malformed invocation.
pub const CODE_VALIDATION_ERROR: &str = "VALIDATION_ERROR";
/// The code attached to a command the tool knows of and refuses.
pub const CODE_UNSUPPORTED: &str = "UNSUPPORTED";

// ------------------------------------------------------------- fault classes

/// The invocation is wrong and nothing was sent. Change the command line.
pub const CLASS_USAGE: &str = "usage";
/// This machine is not set up to talk to the system. Change the environment.
pub const CLASS_CONFIG: &str = "config";
/// The system was not reached, or was reached and is not serving. Retrying may help.
pub const CLASS_TRANSPORT: &str = "transport";
/// The credential was rejected. A new one is the fix.
pub const CLASS_AUTH: &str = "auth";
/// The credential was accepted and this account is not permitted. A new credential for the
/// same account does not help.
pub const CLASS_PERMISSION: &str = "permission";
/// Reached, permitted, and the subject does not resolve to exactly one thing that exists.
pub const CLASS_NOT_FOUND: &str = "not_found";
/// Reached, permitted, the subject exists, and this request was refused. Change the arguments.
pub const CLASS_REFUSED: &str = "refused";
/// A bug in the tool.
pub const CLASS_INTERNAL: &str = "internal";
/// The fail-closed answer for a code the caller's table does not declare. Deliberately not a
/// member of [`CLASSES`]: it is the absence of an answer, not an answer.
pub const CLASS_UNCLASSIFIED: &str = "unclassified";

/// Every class a reachable code may declare.
pub const CLASSES: [&str; 8] = [
    CLASS_USAGE,
    CLASS_CONFIG,
    CLASS_TRANSPORT,
    CLASS_AUTH,
    CLASS_PERMISSION,
    CLASS_NOT_FOUND,
    CLASS_REFUSED,
    CLASS_INTERNAL,
];

/// The class `codes` declares for `code`, or [`CLASS_UNCLASSIFIED`].
///
/// Fails closed on an unknown code rather than guessing from the kind of error it arrived on:
/// the kind is a coarser fact than the code, and a guess that is usually right is exactly what
/// a declared table exists to replace. Each tool keeps its own closed table of
/// `(code, class)` pairs.
pub fn fault_class<'a>(code: Option<&str>, codes: &[(&str, &'a str)]) -> &'a str {
    let code = code.unwrap_or("");
    codes
        .iter()
        .find(|(c, _)| *c == code)
        .map_or(CLASS_UNCLASSIFIED, |(_, class)| class)
}

// --------------------------------------------------------- the recovery vocabulary

/// The five kinds of recovery, as they appear in the `kind` field of the wire form.
pub const KINDS: [&str; 5] = ["run", "retry", "set_env", "choose", "note"];

/// The only placeholder a note may write. Substituted with the caller's own tool name.
pub const TOOL_SLOT: &str = "{tool}";

const DEFAULT_RUN_LEAD: &str = "Run";
const DEFAULT_RETRY_LEAD: &str = "Run the command again with";
const DEFAULT_SEPARATOR: &str = " ";

/// A recovery that was written wrongly: an unknown kind, a field that does not belong to its
/// kind, or a missing required one. A mistyped recovery fails where it is written rather than
/// reading as an empty one.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecoveryError(pub String);

impl fmt::Display for RecoveryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for RecoveryError {}

/// One suggested next step, as data.
///
/// Construct through [`Recovery::run`], [`Recovery::retry`], [`Recovery::set_env`],
/// [`Recovery::choose`] or [`Recovery::note`]: they are the closed vocabulary, and they set
/// the per-kind defaults the renderers reproduce.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Recovery {
    /// Run one of this tool's own commands: ``Run `<tool> <args...>` <purpose>``.
    Run {
        /// The words *after* the tool name, which is supplied by whoever renders this.
        args: Vec<String>,
        /// The trailing clause (`to see the areas that exist`).
        purpose: String,
        /// The clause before the command.
        lead: String,
        /// What joins the command to the purpose.
        separator: String,
    },
    /// Run the command that just failed again, with `fragment` added or changed.
    Retry {
        /// A flag or a path, not an invocation.
        fragment: String,
        /// The trailing clause.
        purpose: String,
        /// The clause before the fragment.
        lead: String,
        /// What joins the fragment to the purpose.
        separator: String,
    },
    /// Set an environment variable, the only channel a credential travels on.
    SetEnv {
        /// The variable name.
        variable: String,
        /// What to set it to.
        describes: String,
        /// Rendered as `, e.g. <example>`.
        example: String,
        /// Rendered as `; see <reference>`.
        reference: String,
    },
    /// Offer the set of values that would have worked: `did you mean: a, b`.
    Choose {
        /// The text before the colon.
        label: String,
        /// The acceptable values.
        values: Vec<String>,
    },
    /// Prose that is not a command. May write [`TOOL_SLOT`] and no other placeholder.
    Note {
        /// The text.
        text: String,
    },
}

impl Recovery {
    /// Run one of this tool's own commands. `args` are the words after the tool name.
    ///
    /// # Panics
    /// When `args` is empty: a run names at least one argument.
    pub fn run<I, S>(args: I) -> Recovery
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let args: Vec<String> = args.into_iter().map(Into::into).collect();
        assert!(
            !args.is_empty(),
            "a run recovery names at least one argument"
        );
        Recovery::Run {
            args,
            purpose: String::new(),
            lead: DEFAULT_RUN_LEAD.into(),
            separator: DEFAULT_SEPARATOR.into(),
        }
    }

    /// Run the command that just failed again, with `fragment` added or changed.
    ///
    /// # Panics
    /// When `fragment` is empty.
    pub fn retry(fragment: impl Into<String>) -> Recovery {
        let fragment = fragment.into();
        assert!(!fragment.is_empty(), "a retry recovery names what to add");
        Recovery::Retry {
            fragment,
            purpose: String::new(),
            lead: DEFAULT_RETRY_LEAD.into(),
            separator: DEFAULT_SEPARATOR.into(),
        }
    }

    /// Set an environment variable. Add [`Recovery::with_example`] and
    /// [`Recovery::with_reference`] for the two trailing spellings.
    ///
    /// # Panics
    /// When either argument is empty.
    pub fn set_env(variable: impl Into<String>, describes: impl Into<String>) -> Recovery {
        let (variable, describes) = (variable.into(), describes.into());
        assert!(
            !variable.is_empty() && !describes.is_empty(),
            "a set_env recovery names a variable and what to set it to"
        );
        Recovery::SetEnv {
            variable,
            describes,
            example: String::new(),
            reference: String::new(),
        }
    }

    /// Offer the set of values that would have worked.
    ///
    /// # Panics
    /// When `label` is empty or `values` is.
    pub fn choose<I, S>(label: impl Into<String>, values: I) -> Recovery
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        let label = label.into();
        let values: Vec<String> = values.into_iter().map(Into::into).collect();
        assert!(
            !label.is_empty() && !values.is_empty(),
            "a choose recovery names a label and at least one value"
        );
        Recovery::Choose { label, values }
    }

    /// Prose that is not a command: the one kind that may name the tool, and only as
    /// [`TOOL_SLOT`].
    ///
    /// # Panics
    /// When `text` is empty or holds a `{...}` placeholder other than `{tool}`.
    pub fn note(text: impl Into<String>) -> Recovery {
        let text = text.into();
        check_note(&text).unwrap_or_else(|e| panic!("{e}"));
        Recovery::Note { text }
    }

    /// A copy carrying a different trailing clause (a `run` or `retry`; any other kind is
    /// returned unchanged).
    #[must_use]
    pub fn with_purpose(mut self, text: impl Into<String>) -> Recovery {
        if let Recovery::Run { purpose, .. } | Recovery::Retry { purpose, .. } = &mut self {
            *purpose = text.into();
        }
        self
    }

    /// A copy carrying a different lead clause (a `run` or `retry`).
    #[must_use]
    pub fn with_lead(mut self, text: impl Into<String>) -> Recovery {
        if let Recovery::Run { lead, .. } | Recovery::Retry { lead, .. } = &mut self {
            *lead = text.into();
        }
        self
    }

    /// A copy joined to its purpose by `text` instead of a space (a `run` or `retry`):
    /// `": "` where the tool binds the explanation to the command with a colon.
    #[must_use]
    pub fn with_separator(mut self, text: impl Into<String>) -> Recovery {
        if let Recovery::Run { separator, .. } | Recovery::Retry { separator, .. } = &mut self {
            *separator = text.into();
        }
        self
    }

    /// A copy with a `, e.g. <example>` clause (a `set_env`).
    #[must_use]
    pub fn with_example(mut self, text: impl Into<String>) -> Recovery {
        if let Recovery::SetEnv { example, .. } = &mut self {
            *example = text.into();
        }
        self
    }

    /// A copy with a `; see <reference>` clause (a `set_env`).
    #[must_use]
    pub fn with_reference(mut self, text: impl Into<String>) -> Recovery {
        if let Recovery::SetEnv { reference, .. } = &mut self {
            *reference = text.into();
        }
        self
    }

    /// The kind's name as written in the wire form.
    pub fn kind(&self) -> &'static str {
        match self {
            Recovery::Run { .. } => "run",
            Recovery::Retry { .. } => "retry",
            Recovery::SetEnv { .. } => "set_env",
            Recovery::Choose { .. } => "choose",
            Recovery::Note { .. } => "note",
        }
    }

    /// Whether rendering this recovery will name a tool at all: true for every `run` (the
    /// command it names is one of the tool's own) and for a note that writes [`TOOL_SLOT`].
    /// A recovery for which this is false renders identically whatever tool name it is handed.
    pub fn mentions_tool(&self) -> bool {
        match self {
            Recovery::Run { .. } => true,
            Recovery::Note { text } => text.contains(TOOL_SLOT),
            _ => false,
        }
    }

    /// The JSON-shaped wire form: `kind` first, then the kind's fields in sorted order, a
    /// note's text under `text`, and a field omitted when it holds its unset value (`""`, an
    /// empty list, a `" "` separator) -- except the `lead` of a `run` or `retry`, which is
    /// always written, an empty one included, because an absent lead means the factory default.
    pub fn to_value(&self) -> Value {
        let mut out = vec![("kind".to_string(), Value::from(self.kind()))];
        match self {
            Recovery::Run {
                args,
                purpose,
                lead,
                separator,
            } => {
                out.push(("args".into(), Value::from(args.clone())));
                out.push(("lead".into(), Value::from(lead.as_str())));
                push_set(&mut out, "purpose", purpose, "");
                push_set(&mut out, "separator", separator, DEFAULT_SEPARATOR);
            }
            Recovery::Retry {
                fragment,
                purpose,
                lead,
                separator,
            } => {
                push_set(&mut out, "fragment", fragment, "");
                out.push(("lead".into(), Value::from(lead.as_str())));
                push_set(&mut out, "purpose", purpose, "");
                push_set(&mut out, "separator", separator, DEFAULT_SEPARATOR);
            }
            Recovery::SetEnv {
                variable,
                describes,
                example,
                reference,
            } => {
                push_set(&mut out, "describes", describes, "");
                push_set(&mut out, "example", example, "");
                push_set(&mut out, "reference", reference, "");
                push_set(&mut out, "variable", variable, "");
            }
            Recovery::Choose { label, values } => {
                push_set(&mut out, "label", label, "");
                out.push(("values".into(), Value::from(values.clone())));
            }
            Recovery::Note { text } => push_set(&mut out, "text", text, ""),
        }
        Value::Object(out)
    }

    /// Rebuild a recovery from [`Recovery::to_value`]'s form, or from one a person wrote.
    ///
    /// An absent `lead` on a `run` or `retry` takes the factory default rather than `""`: a
    /// hand-written `{"kind": "run", "args": ["x"]}` otherwise renders with a leading space.
    ///
    /// # Errors
    /// An unknown kind, a field that does not belong to the kind (unless it is unset), a
    /// missing required field, a wrongly typed field, or a note with a second placeholder.
    pub fn from_value(value: &Value) -> Result<Recovery, RecoveryError> {
        let Value::Object(entries) = value else {
            return Err(RecoveryError("a recovery is an object".into()));
        };
        let mut f = Fields::default();
        let mut kind = None;
        for (name, v) in entries {
            match name.as_str() {
                "kind" => kind = Some(string(name, v)?),
                "args" => f.args = strings(name, v)?,
                "values" => f.values = strings(name, v)?,
                "text" | "fragment" => f.fragment = string(name, v)?,
                "purpose" => f.purpose = string(name, v)?,
                "lead" => f.lead = Some(string(name, v)?),
                "separator" => f.separator = Some(string(name, v)?),
                "variable" => f.variable = string(name, v)?,
                "describes" => f.describes = string(name, v)?,
                "example" => f.example = string(name, v)?,
                "reference" => f.reference = string(name, v)?,
                "label" => f.label = string(name, v)?,
                other => return Err(RecoveryError(format!("unknown recovery field: {other:?}"))),
            }
        }
        let kind = kind.unwrap_or_default();
        f.build(&kind)
    }
}

/// Append `name` unless it holds its unset value.
fn push_set(out: &mut Vec<(String, Value)>, name: &str, value: &str, unset: &str) {
    if value != unset {
        out.push((name.to_string(), Value::from(value)));
    }
}

fn string(name: &str, v: &Value) -> Result<String, RecoveryError> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        _ => Err(RecoveryError(format!(
            "recovery field {name:?} is a string"
        ))),
    }
}

fn strings(name: &str, v: &Value) -> Result<Vec<String>, RecoveryError> {
    match v {
        Value::Array(items) => items.iter().map(|i| string(name, i)).collect(),
        _ => Err(RecoveryError(format!(
            "recovery field {name:?} is a list of strings"
        ))),
    }
}

fn check_note(text: &str) -> Result<(), RecoveryError> {
    if text.is_empty() {
        return Err(RecoveryError("a note recovery carries text".into()));
    }
    // Any `{...}` other than the tool slot: a note is prose with exactly one hole in it.
    let mut rest = text;
    while let Some(open) = rest.find('{') {
        let after = &rest[open..];
        if let Some(close) = after.find('}') {
            if &after[..=close] != TOOL_SLOT {
                return Err(RecoveryError(format!(
                    "a note may write {TOOL_SLOT} and no other placeholder; found one in {text:?}"
                )));
            }
            rest = &after[close + 1..];
        } else {
            break;
        }
    }
    Ok(())
}

/// Every field of the Python dataclass, for validating a wire form against the kind's table.
#[derive(Default)]
struct Fields {
    args: Vec<String>,
    fragment: String,
    purpose: String,
    lead: Option<String>,
    separator: Option<String>,
    variable: String,
    describes: String,
    example: String,
    reference: String,
    label: String,
    values: Vec<String>,
}

impl Fields {
    fn build(self, kind: &str) -> Result<Recovery, RecoveryError> {
        let allowed: &[&str] = match kind {
            "run" => &["args", "purpose", "lead", "separator"],
            "retry" => &["fragment", "purpose", "lead", "separator"],
            "set_env" => &["variable", "describes", "example", "reference"],
            "choose" => &["label", "values"],
            "note" => &["fragment"],
            other => return Err(RecoveryError(format!("unknown recovery kind: {other:?}"))),
        };
        let carried: [(&str, bool); 11] = [
            ("args", !self.args.is_empty()),
            ("fragment", !self.fragment.is_empty()),
            ("purpose", !self.purpose.is_empty()),
            ("lead", self.lead.as_deref().is_some_and(|l| !l.is_empty())),
            (
                "separator",
                self.separator
                    .as_deref()
                    .is_some_and(|s| s != DEFAULT_SEPARATOR),
            ),
            ("variable", !self.variable.is_empty()),
            ("describes", !self.describes.is_empty()),
            ("example", !self.example.is_empty()),
            ("reference", !self.reference.is_empty()),
            ("label", !self.label.is_empty()),
            ("values", !self.values.is_empty()),
        ];
        for (name, set) in carried {
            if set && !allowed.contains(&name) {
                return Err(RecoveryError(format!(
                    "{kind} recovery cannot carry {name:?}"
                )));
            }
        }
        // An empty lead on a kind that has none is "unset"; on a run or retry it is a value.
        let lead_given = self.lead.is_some();
        if lead_given && !allowed.contains(&"lead") && self.lead.as_deref() != Some("") {
            return Err(RecoveryError(format!(
                "{kind} recovery cannot carry \"lead\""
            )));
        }
        let separator = self.separator.unwrap_or_else(|| DEFAULT_SEPARATOR.into());
        Ok(match kind {
            "run" => {
                if self.args.is_empty() {
                    return Err(RecoveryError(
                        "a run recovery names at least one argument".into(),
                    ));
                }
                Recovery::Run {
                    args: self.args,
                    purpose: self.purpose,
                    lead: self.lead.unwrap_or_else(|| DEFAULT_RUN_LEAD.into()),
                    separator,
                }
            }
            "retry" => {
                if self.fragment.is_empty() {
                    return Err(RecoveryError("a retry recovery names what to add".into()));
                }
                Recovery::Retry {
                    fragment: self.fragment,
                    purpose: self.purpose,
                    lead: self.lead.unwrap_or_else(|| DEFAULT_RETRY_LEAD.into()),
                    separator,
                }
            }
            "set_env" => {
                if self.variable.is_empty() || self.describes.is_empty() {
                    return Err(RecoveryError(
                        "a set_env recovery names a variable and what to set it to".into(),
                    ));
                }
                Recovery::SetEnv {
                    variable: self.variable,
                    describes: self.describes,
                    example: self.example,
                    reference: self.reference,
                }
            }
            "choose" => {
                if self.label.is_empty() || self.values.is_empty() {
                    return Err(RecoveryError(
                        "a choose recovery names a label and at least one value".into(),
                    ));
                }
                Recovery::Choose {
                    label: self.label,
                    values: self.values,
                }
            }
            _ => {
                check_note(&self.fragment)?;
                Recovery::Note {
                    text: self.fragment,
                }
            }
        })
    }
}

// --------------------------------------------------------------- the error type

/// Which of the AXI exception classes an [`AxiError`] belongs to. The kind decides the exit
/// status ([`ErrorKind::Usage`] is 2, every other is 1) and nothing else; the fault class a
/// caller switches on comes from the error's *code*, through [`fault_class`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ErrorKind {
    /// The plain base error (`AxiError`).
    Axi,
    /// A malformed invocation: unknown flag, missing argument, bad value (`UsageError`).
    Usage,
    /// Required environment configuration is missing or unusable (`ConfigError`).
    Config,
    /// The system behind the tool could not be reached (`ConnectionFailed`).
    ConnectionFailed,
    /// The credential was rejected (`AuthFailed`).
    AuthFailed,
    /// The credential was accepted and the caller was refused anyway (`Forbidden`). Deliberately
    /// neither an auth failure (a new credential for the same account does not help) nor an API
    /// error (a refusal that never reached the subject has nothing there to explain it).
    Forbidden,
    /// The subject does not resolve to one thing that exists (`NotFound`).
    NotFound,
    /// The system answered, and refused the request (`ApiError`).
    Api,
}

impl ErrorKind {
    /// Every kind, in the order the conformance pack lists the exception classes.
    pub const ALL: [ErrorKind; 8] = [
        ErrorKind::Axi,
        ErrorKind::Usage,
        ErrorKind::Config,
        ErrorKind::ConnectionFailed,
        ErrorKind::AuthFailed,
        ErrorKind::Forbidden,
        ErrorKind::NotFound,
        ErrorKind::Api,
    ];

    /// The class name the other implementations use (`"UsageError"`).
    pub const fn name(self) -> &'static str {
        match self {
            ErrorKind::Axi => "AxiError",
            ErrorKind::Usage => "UsageError",
            ErrorKind::Config => "ConfigError",
            ErrorKind::ConnectionFailed => "ConnectionFailed",
            ErrorKind::AuthFailed => "AuthFailed",
            ErrorKind::Forbidden => "Forbidden",
            ErrorKind::NotFound => "NotFound",
            ErrorKind::Api => "ApiError",
        }
    }

    /// The kind with this class name.
    pub fn from_name(name: &str) -> Option<ErrorKind> {
        ErrorKind::ALL.into_iter().find(|k| k.name() == name)
    }

    /// The process exit status for an error of this kind.
    pub const fn exit_code(self) -> i32 {
        match self {
            ErrorKind::Usage => EXIT_USAGE,
            _ => EXIT_ERROR,
        }
    }
}

/// An error the agent should be able to read, understand and act on.
///
/// `recovery` carries the specific next steps as data: on an error, suggest the fix rather than
/// pointing at `--help`. `code` is a literal from the owning tool's closed table -- always a
/// literal, because a code built from whatever the server said (an `HTTP_404` assembled from the status) is vocabulary no
/// caller can switch on and no table can ever complete.
///
/// There is deliberately no field for rendered help lines: [`crate::render`] produces them
/// from `recovery` at the moment somebody knows which tool is asking.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AxiError {
    /// Which exception class this is; decides the exit status.
    pub kind: ErrorKind,
    /// What went wrong. Printed, so it must never carry a credential.
    pub message: String,
    /// A literal from the tool's closed code table.
    pub code: Option<String>,
    /// The next steps, unrendered.
    pub recovery: Vec<Recovery>,
}

impl AxiError {
    /// An error of `kind` with no code and no recovery.
    pub fn new(kind: ErrorKind, message: impl Into<String>) -> AxiError {
        AxiError {
            kind,
            message: message.into(),
            code: None,
            recovery: Vec::new(),
        }
    }

    /// A plain [`ErrorKind::Axi`] error.
    pub fn general(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::Axi, message)
    }

    /// A malformed invocation (exit status 2) coded [`CODE_VALIDATION_ERROR`].
    pub fn usage(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::Usage, message).with_code(CODE_VALIDATION_ERROR)
    }

    /// Missing or unusable environment configuration.
    pub fn config(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::Config, message)
    }

    /// The system could not be reached.
    pub fn connection_failed(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::ConnectionFailed, message)
    }

    /// The credential was rejected.
    pub fn auth_failed(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::AuthFailed, message)
    }

    /// The credential was accepted and the caller was refused anyway.
    pub fn forbidden(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::Forbidden, message)
    }

    /// The subject does not resolve to one thing that exists.
    pub fn not_found(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::NotFound, message)
    }

    /// The system answered, and refused the request.
    pub fn api(message: impl Into<String>) -> AxiError {
        AxiError::new(ErrorKind::Api, message)
    }

    /// A copy carrying `code`.
    #[must_use]
    pub fn with_code(mut self, code: impl Into<String>) -> AxiError {
        self.code = Some(code.into());
        self
    }

    /// A copy carrying `recovery`, replacing any already set.
    #[must_use]
    pub fn with_recovery(mut self, recovery: Vec<Recovery>) -> AxiError {
        self.recovery = recovery;
        self
    }

    /// A copy with one more recovery appended.
    #[must_use]
    pub fn and_recover(mut self, recovery: Recovery) -> AxiError {
        self.recovery.push(recovery);
        self
    }

    /// The process exit status for this error.
    pub fn exit_code(&self) -> i32 {
        self.kind.exit_code()
    }

    /// The class `codes` declares for this error's code.
    pub fn fault_class<'a>(&self, codes: &[(&str, &'a str)]) -> &'a str {
        fault_class(self.code.as_deref(), codes)
    }

    /// The error as JSON-shaped data, recovery included and still unrendered:
    /// `message`, `code` (`""` when there is none) and `recovery`.
    pub fn to_value(&self) -> Value {
        Value::Object(vec![
            ("message".into(), Value::from(self.message.as_str())),
            (
                "code".into(),
                Value::from(self.code.as_deref().unwrap_or("")),
            ),
            (
                "recovery".into(),
                Value::Array(self.recovery.iter().map(Recovery::to_value).collect()),
            ),
        ])
    }
}

impl fmt::Display for AxiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AxiError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exit_codes_follow_the_kind() {
        assert_eq!(AxiError::usage("x").exit_code(), 2);
        assert_eq!(AxiError::not_found("x").exit_code(), 1);
        assert_eq!(AxiError::general("x").exit_code(), 1);
    }

    #[test]
    fn fault_class_fails_closed() {
        let table = [("A", CLASS_AUTH)];
        assert_eq!(fault_class(Some("A"), &table), "auth");
        assert_eq!(fault_class(Some("B"), &table), CLASS_UNCLASSIFIED);
        assert_eq!(fault_class(None, &table), CLASS_UNCLASSIFIED);
        assert!(!CLASSES.contains(&CLASS_UNCLASSIFIED));
    }

    #[test]
    fn a_note_writes_only_the_tool_slot() {
        assert!(check_note("a {tool} b {tool}").is_ok());
        assert!(check_note("a {count} b").is_err());
        assert!(check_note("").is_err());
        assert!(Recovery::note("use {tool}").mentions_tool());
        assert!(!Recovery::note("plain").mentions_tool());
    }

    #[test]
    fn wire_form_round_trips() {
        let all = [
            Recovery::run(["a", "b"])
                .with_purpose("to c")
                .with_separator(": "),
            Recovery::retry("--x").with_lead("").with_purpose("now"),
            Recovery::set_env("V", "d")
                .with_example("e")
                .with_reference("r"),
            Recovery::choose("l", ["a", "b"]),
            Recovery::note("hello {tool}"),
        ];
        for r in all {
            assert_eq!(Recovery::from_value(&r.to_value()).unwrap(), r);
        }
    }
}
