//! Connection settings, read from the environment and never from a file.
//!
//! A credential passed on a command line leaks into shell history and the process table, and a
//! credential in a file leaks into commits. The environment is the only channel, and there is
//! deliberately no `--token` flag anywhere.
//!
//! What differs between systems is declared once on a [`CredentialSpec`] -- variable names and
//! aliases, whether a bare host defaults to `https` or `http`, a default port, a path suffix to
//! strip -- and what is shared is mechanism: the environment is the only source, a token that
//! cannot be an HTTP header value is rejected before anything sends it, and `user:password@` in
//! a URL is separated off and registered as a secret rather than carried into anything
//! printable. Messages, codes and recovery are held to `conformance/credentials.json`.

use crate::errors::{AxiError, Recovery};
use crate::pystr;
use crate::redact;
use std::collections::{BTreeMap, HashMap};

/// The request timeout, in seconds, a spec that names none gets.
pub const DEFAULT_TIMEOUT: f64 = 30.0;

/// The code of a configuration that names a variable that is not set.
pub const CODE_NOT_CONFIGURED: &str = "NOT_CONFIGURED";
/// The code of a token a header cannot carry.
pub const CODE_BAD_TOKEN: &str = "BAD_TOKEN";
/// The code of a base URL that is not usable.
pub const CODE_BAD_URL: &str = "BAD_URL";

/// Where variables are read from. Tests hand a map; a tool hands [`ProcessEnv`].
pub trait Environ {
    /// The value of `name`, if set and valid Unicode.
    fn get(&self, name: &str) -> Option<String>;
}

/// The process environment.
#[derive(Debug, Clone, Copy, Default)]
pub struct ProcessEnv;

impl Environ for ProcessEnv {
    fn get(&self, name: &str) -> Option<String> {
        std::env::var(name).ok()
    }
}

impl Environ for HashMap<String, String> {
    fn get(&self, name: &str) -> Option<String> {
        HashMap::get(self, name).cloned()
    }
}

impl Environ for BTreeMap<String, String> {
    fn get(&self, name: &str) -> Option<String> {
        BTreeMap::get(self, name).cloned()
    }
}

/// The scheme a bare host gets.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scheme {
    /// `http`.
    Http,
    /// `https`.
    Https,
}

impl Scheme {
    fn as_str(self) -> &'static str {
        match self {
            Scheme::Http => "http",
            Scheme::Https => "https",
        }
    }
}

/// How one tool reads its credentials from the environment.
///
/// Everything here is a fact about the system the tool talks to, which is why it is declared by
/// the tool rather than defaulted by this module. The one exception is `default_scheme`: it
/// defaults to `https` because a bare host that silently became `http://` would send the
/// credential in the clear, and a tool that wants the other answer has to say so and say why.
#[derive(Debug, Clone, PartialEq)]
pub struct CredentialSpec {
    /// Variable names for the base URL, most-preferred first. Later names are aliases.
    pub url_vars: Vec<String>,
    /// Variable names for the credential, most-preferred first.
    pub token_vars: Vec<String>,
    /// What to set each variable to, in the same order.
    pub setup: Vec<Recovery>,
    /// How to confirm the settings work once both are present -- typically the tool's own
    /// `doctor`. Kept apart from `setup` so a caller already inside `doctor` can leave it out.
    pub verify: Option<Recovery>,
    /// What to check when the credential carries a character a header cannot.
    pub token_recovery: Vec<Recovery>,
    /// The scheme a bare host gets.
    pub default_scheme: Scheme,
    /// A port appended to a host that names none.
    pub default_port: Option<u16>,
    /// A path suffix stripped from the base URL -- a common paste mistake where a tool's API
    /// root is a well-known subpath of the instance root.
    pub strip_path_suffix: String,
    /// The request timeout in seconds.
    pub default_timeout: f64,
}

impl CredentialSpec {
    /// A spec reading the URL from `url_vars` and the credential from `token_vars`.
    ///
    /// # Panics
    /// When either list is empty.
    pub fn new<U, T>(url_vars: U, token_vars: T) -> CredentialSpec
    where
        U: IntoIterator,
        U::Item: Into<String>,
        T: IntoIterator,
        T::Item: Into<String>,
    {
        let url_vars: Vec<String> = url_vars.into_iter().map(Into::into).collect();
        let token_vars: Vec<String> = token_vars.into_iter().map(Into::into).collect();
        assert!(
            !url_vars.is_empty() && !token_vars.is_empty(),
            "a credential spec names at least one URL and one token variable"
        );
        CredentialSpec {
            url_vars,
            token_vars,
            setup: Vec::new(),
            verify: None,
            token_recovery: Vec::new(),
            default_scheme: Scheme::Https,
            default_port: None,
            strip_path_suffix: String::new(),
            default_timeout: DEFAULT_TIMEOUT,
        }
    }
}

/// A resolved, ready-to-use configuration. Carries the variable names it was resolved from, so
/// a caller reporting on its own configuration does not have to ask the environment twice.
/// `Debug` never prints the token.
#[derive(Clone, PartialEq)]
pub struct Credentials {
    /// The normalised base URL, with no userinfo.
    pub base_url: String,
    /// The credential. Already registered with the shared redactor.
    pub token: String,
    /// The request timeout in seconds.
    pub timeout: f64,
    /// The variable the URL came from.
    pub url_var: String,
    /// The variable the token came from.
    pub token_var: String,
}

impl std::fmt::Debug for Credentials {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Credentials")
            .field("base_url", &self.base_url)
            .field("token", &redact::REDACTED)
            .field("timeout", &self.timeout)
            .field("url_var", &self.url_var)
            .field("token_var", &self.token_var)
            .finish()
    }
}

/// Whether `c` may not appear in a token: whitespace or a control character.
fn illegal_in_token(c: char) -> bool {
    pystr::is_space(c) || c <= '\u{1f}' || c == '\u{7f}'
}

/// The first of `names` set to something other than whitespace, and its trimmed value.
pub fn first_env(names: &[String], environ: &dyn Environ) -> Option<(String, String)> {
    names.iter().find_map(|name| {
        let value = environ.get(name)?;
        let stripped = pystr::strip(&value);
        (!stripped.is_empty()).then(|| (name.clone(), stripped.to_string()))
    })
}

/// Separate any `user:password@` prefix from a network location.
///
/// Such credentials are never sent, but they must not survive into the base URL either, because
/// a tool's own status view prints that URL and those views end up in agent transcripts.
pub fn split_userinfo(netloc: &str) -> (&str, &str) {
    match netloc.rsplit_once('@') {
        Some((userinfo, host)) => (userinfo, host),
        None => ("", netloc),
    }
}

/// The five parts of a URL, split the way Python's `urllib.parse.urlsplit` splits it.
struct Split {
    scheme: String,
    netloc: String,
    path: String,
}

fn urlsplit(url: &str) -> Option<Split> {
    let url = url.trim_start_matches(|c: char| c <= ' ');
    let url: String = url
        .chars()
        .filter(|c| !matches!(c, '\t' | '\r' | '\n'))
        .collect();
    let mut rest = url.as_str();
    let mut scheme = String::new();
    if let Some(i) = rest.find(':') {
        let name = &rest[..i];
        let mut chars = name.chars();
        if chars.next().is_some_and(|c| c.is_ascii_alphabetic())
            && name
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'))
        {
            scheme = name.to_ascii_lowercase();
            rest = &rest[i + 1..];
        }
    }
    let mut netloc = "";
    if let Some(after) = rest.strip_prefix("//") {
        let end = after.find(['/', '?', '#']).unwrap_or(after.len());
        netloc = &after[..end];
        rest = &after[end..];
        if (netloc.contains('[') && !netloc.contains(']'))
            || (netloc.contains(']') && !netloc.contains('['))
        {
            return None;
        }
    }
    let rest = rest.split('#').next().unwrap_or("");
    let path = rest.split('?').next().unwrap_or("");
    Some(Split {
        scheme,
        netloc: netloc.to_string(),
        path: path.to_string(),
    })
}

/// Accept a bare host, apply `spec`'s defaults, and drop any trailing path noise.
///
/// A `user:password@` prefix is registered as a secret with the shared redactor and removed.
///
/// # Errors
/// A [`CODE_BAD_URL`] configuration error when the result has no host or uses a scheme other
/// than `http` or `https`.
pub fn normalize_base_url(raw: &str, spec: &CredentialSpec) -> Result<String, AxiError> {
    let mut value = pystr::strip(raw).trim_end_matches('/').to_string();
    if !value.contains("://") {
        value = format!("{}://{value}", spec.default_scheme.as_str());
    }
    let bad = |message: String| {
        AxiError::config(message)
            .with_code(CODE_BAD_URL)
            .with_recovery(spec.setup.iter().take(1).cloned().collect())
    };
    let Some(parts) = urlsplit(&value).filter(|p| !p.netloc.is_empty()) else {
        return Err(bad(format!(
            "{} is not a usable URL: {}",
            spec.url_vars[0],
            pystr::repr(&value)
        )));
    };
    if parts.scheme != "http" && parts.scheme != "https" {
        return Err(bad(format!(
            "{} must use http or https, got {}",
            spec.url_vars[0],
            pystr::repr(&parts.scheme)
        )));
    }
    let mut path = parts.path.trim_end_matches('/').to_string();
    if !spec.strip_path_suffix.is_empty() && path.ends_with(&spec.strip_path_suffix) {
        path.truncate(path.len() - spec.strip_path_suffix.len());
    }
    let (userinfo, host) = split_userinfo(&parts.netloc);
    if !userinfo.is_empty() {
        // Registered before returning: from here on the value can only be printed through the
        // redacting output boundary.
        redact::register_secret_min(userinfo, 4);
        let password = userinfo.split_once(':').map_or("", |(_, p)| p);
        redact::register_secret_min(password, 4);
    }
    let mut host = host.to_string();
    if let Some(port) = spec.default_port {
        // Split at the last `]` so a bracketed IPv6 literal's own colons are not read as a port
        // that is already there.
        let after_bracket = host.rsplit(']').next().unwrap_or("");
        if !after_bracket.contains(':') {
            host = format!("{host}:{port}");
        }
    }
    let mut out = path;
    if !host.is_empty() || !out.starts_with("//") {
        if !out.is_empty() && !out.starts_with('/') {
            out.insert(0, '/');
        }
        out = format!("//{host}{out}");
    }
    Ok(format!("{}:{out}", parts.scheme))
}

/// Resolve credentials, or fail naming what is absent.
///
/// The token is registered with the shared redactor the moment it is read, so no later code path
/// can print it.
///
/// # Errors
/// A configuration error coded [`CODE_NOT_CONFIGURED`] (a variable unset or blank),
/// [`CODE_BAD_TOKEN`] (the token holds whitespace or a control character; the message names the
/// variable and never the value) or [`CODE_BAD_URL`].
pub fn load(
    spec: &CredentialSpec,
    environ: &dyn Environ,
    timeout: Option<f64>,
) -> Result<Credentials, AxiError> {
    let url = first_env(&spec.url_vars, environ);
    let token = first_env(&spec.token_vars, environ);
    let mut missing = Vec::new();
    if url.is_none() {
        missing.push(spec.url_vars[0].as_str());
    }
    if token.is_none() {
        missing.push(spec.token_vars[0].as_str());
    }
    let (Some((url_var, raw_url)), Some((token_var, token))) = (url, token) else {
        let plural = if missing.len() > 1 { "are" } else { "is" };
        return Err(AxiError::config(format!(
            "{} {plural} not set in the environment",
            missing.join(" and ")
        ))
        .with_code(CODE_NOT_CONFIGURED)
        .with_recovery(setup_recovery(spec, true)));
    };
    if token.chars().any(illegal_in_token) {
        return Err(AxiError::config(format!(
            "{} contains whitespace or a control character",
            spec.token_vars[0]
        ))
        .with_code(CODE_BAD_TOKEN)
        .with_recovery(spec.token_recovery.clone()));
    }
    redact::register_secret(&token);
    Ok(Credentials {
        base_url: normalize_base_url(&raw_url, spec)?,
        token,
        timeout: timeout.unwrap_or(spec.default_timeout),
        url_var,
        token_var,
    })
}

/// The guidance offered wherever configuration is found to be absent.
pub fn setup_recovery(spec: &CredentialSpec, include_verify: bool) -> Vec<Recovery> {
    let mut out = spec.setup.clone();
    if include_verify {
        out.extend(spec.verify.clone());
    }
    out
}

/// Which variables are set, without ever revealing the credential.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnvironmentReport {
    /// The URL variable in use, or `""`.
    pub url_var: String,
    /// Whether a URL is set.
    pub url_set: bool,
    /// The token variable in use, or `""`.
    pub token_var: String,
    /// Whether a token is set.
    pub token_set: bool,
}

/// Report which variables are set without ever revealing the credential.
pub fn describe_environment(spec: &CredentialSpec, environ: &dyn Environ) -> EnvironmentReport {
    let url = first_env(&spec.url_vars, environ);
    let token = first_env(&spec.token_vars, environ);
    EnvironmentReport {
        url_set: url.is_some(),
        url_var: url.map(|(n, _)| n).unwrap_or_default(),
        token_set: token.is_some(),
        token_var: token.map(|(n, _)| n).unwrap_or_default(),
    }
}

/// The primary variable names that are absent, in the order to report them.
pub fn missing_vars(spec: &CredentialSpec, environ: &dyn Environ) -> Vec<String> {
    let described = describe_environment(spec, environ);
    let mut missing = Vec::new();
    if !described.url_set {
        missing.push(spec.url_vars[0].clone());
    }
    if !described.token_set {
        missing.push(spec.token_vars[0].clone());
    }
    missing
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    fn spec() -> CredentialSpec {
        let mut s = CredentialSpec::new(["EX_URL", "EX_SERVER"], ["EX_TOKEN"]);
        s.setup = vec![Recovery::set_env("EX_URL", "the base URL")];
        s.strip_path_suffix = "/api".into();
        s
    }

    #[test]
    fn a_bare_host_gets_the_default_scheme_and_a_trailing_api_is_stripped() {
        let s = spec();
        assert_eq!(
            normalize_base_url("host.example.com", &s).unwrap(),
            "https://host.example.com"
        );
        assert_eq!(
            normalize_base_url("https://host.example.com/api/", &s).unwrap(),
            "https://host.example.com"
        );
        assert_eq!(
            normalize_base_url("https://proxy.example.com/prefix", &s).unwrap(),
            "https://proxy.example.com/prefix"
        );
    }

    #[test]
    fn a_default_port_is_added_unless_one_is_named() {
        let mut s = spec();
        s.default_scheme = Scheme::Http;
        s.default_port = Some(32400);
        assert_eq!(
            normalize_base_url("h.example.com", &s).unwrap(),
            "http://h.example.com:32400"
        );
        assert_eq!(
            normalize_base_url("h.example.com:1", &s).unwrap(),
            "http://h.example.com:1"
        );
        assert_eq!(
            normalize_base_url("http://[2001:db8::1]", &s).unwrap(),
            "http://[2001:db8::1]:32400"
        );
    }

    #[test]
    fn a_bad_url_names_the_variable_and_offers_the_setup() {
        let e = normalize_base_url("ftp://h.example.com", &spec()).unwrap_err();
        assert_eq!(e.message, "EX_URL must use http or https, got 'ftp'");
        assert_eq!(e.code.as_deref(), Some(CODE_BAD_URL));
        assert_eq!(e.recovery.len(), 1);
        let e = normalize_base_url("://nope", &spec()).unwrap_err();
        assert_eq!(e.message, "EX_URL is not a usable URL: '://nope'");
    }

    #[test]
    fn load_reports_what_is_missing_and_never_the_token() {
        let s = spec();
        let e = load(&s, &env(&[]), None).unwrap_err();
        assert_eq!(
            e.message,
            "EX_URL and EX_TOKEN are not set in the environment"
        );
        let e = load(
            &s,
            &env(&[("EX_URL", "h.example.com"), ("EX_TOKEN", "ab cd")]),
            None,
        )
        .unwrap_err();
        assert_eq!(
            e.message,
            "EX_TOKEN contains whitespace or a control character"
        );
        assert!(!e.message.contains("ab cd"));
        let c = load(
            &s,
            &env(&[
                ("EX_SERVER", " h.example.com "),
                ("EX_TOKEN", " probe-0123456789 "),
            ]),
            Some(5.5),
        )
        .unwrap();
        assert_eq!((c.url_var.as_str(), c.timeout), ("EX_SERVER", 5.5));
        assert!(!format!("{c:?}").contains("probe-0123456789"));
    }
}
