//! A small blocking HTTP client for tools that call a JSON API, behind the `http` feature.
//!
//! It is the crate's only non-`std` dependency (`ureq` with `rustls`). What it adds over using
//! `ureq` directly is the agent-facing contract:
//!
//! * the bearer token is registered with the shared redactor, so it cannot reach output;
//! * plain `http://` is refused unless [`Client::allow_insecure`] is called, because a bearer
//!   token over cleartext is a leak;
//! * every failure is an [`AxiError`] of the right kind (connection, 401, 403, 404, other), with
//!   a redacted message, so the dispatcher's exit codes and fault classes come out right.
//!
//! # Error codes
//!
//! Every code this module produces is a literal from a closed set, so a tool can declare them in
//! its fault table and [`fault_class`](crate::errors::fault_class) can classify them:
//!
//! | code | when |
//! | --- | --- |
//! | [`CODE_INSECURE_URL`] | plain `http://` refused before sending |
//! | [`CODE_BAD_RESPONSE`] | a response that was not the JSON the caller expected |
//! | [`CODE_HTTP_UNAUTHORIZED`] | status 401 |
//! | [`CODE_HTTP_FORBIDDEN`] | status 403 |
//! | [`CODE_HTTP_NOT_FOUND`] | status 404 |
//! | [`CODE_HTTP_ERROR`] | any other error status |
//!
//! The status number itself is in the message, never in the code. A connection failure carries
//! no code. [`CODES`] lists the set.

use crate::envconfig::Credentials;
use crate::errors::AxiError;
use crate::redact;
use std::time::Duration;

/// The code of an error from a request that was refused before it was sent.
pub const CODE_INSECURE_URL: &str = "INSECURE_URL";
/// The code of an error from a response that was not the JSON the caller expected.
pub const CODE_BAD_RESPONSE: &str = "BAD_RESPONSE";

/// The code of an error from a 401 response.
pub const CODE_HTTP_UNAUTHORIZED: &str = "HTTP_UNAUTHORIZED";
/// The code of an error from a 403 response.
pub const CODE_HTTP_FORBIDDEN: &str = "HTTP_FORBIDDEN";
/// The code of an error from a 404 response.
pub const CODE_HTTP_NOT_FOUND: &str = "HTTP_NOT_FOUND";
/// The code of an error from any other error status.
pub const CODE_HTTP_ERROR: &str = "HTTP_ERROR";

/// Every code this module produces, for a tool to merge into its fault table.
pub const CODES: [&str; 6] = [
    CODE_INSECURE_URL,
    CODE_BAD_RESPONSE,
    CODE_HTTP_UNAUTHORIZED,
    CODE_HTTP_FORBIDDEN,
    CODE_HTTP_NOT_FOUND,
    CODE_HTTP_ERROR,
];

/// A blocking client bound to one base URL and one bearer token.
#[derive(Debug, Clone)]
pub struct Client {
    base_url: String,
    token: String,
    timeout: Duration,
    allow_insecure: bool,
    headers: Vec<(String, String)>,
}

impl Client {
    /// A client for `base_url` sending `token` as a bearer credential. The token is registered
    /// with the shared redactor.
    pub fn new(base_url: impl Into<String>, token: impl Into<String>) -> Client {
        let token = token.into();
        redact::register_secret(&token);
        Client {
            base_url: base_url.into().trim_end_matches('/').to_string(),
            token,
            timeout: Duration::from_secs(10),
            allow_insecure: false,
            headers: Vec::new(),
        }
    }

    /// A client from [`envconfig::load`](crate::envconfig::load)'s result.
    pub fn from_credentials(c: &Credentials) -> Client {
        Client::new(c.base_url.clone(), c.token.clone())
            .timeout(Duration::from_secs_f64(c.timeout.max(0.001)))
    }

    /// The request timeout (connect, send and read each). Default 10 seconds.
    #[must_use]
    pub fn timeout(mut self, timeout: Duration) -> Client {
        self.timeout = timeout;
        self
    }

    /// Permit plain `http://` base URLs, for a local service or a test.
    #[must_use]
    pub fn allow_insecure(mut self) -> Client {
        self.allow_insecure = true;
        self
    }

    /// Send an extra header with every request.
    #[must_use]
    pub fn header(mut self, name: impl Into<String>, value: impl Into<String>) -> Client {
        self.headers.push((name.into(), value.into()));
        self
    }

    /// `GET path` and return the response body.
    ///
    /// # Errors
    /// An [`AxiError`] of kind connection-failed, auth-failed, forbidden, not-found or api.
    pub fn get(&self, path: &str) -> Result<String, AxiError> {
        self.request("GET", path, None)
    }

    /// `POST path` with a JSON body and return the response body.
    ///
    /// # Errors
    /// As [`Client::get`].
    pub fn post_json(&self, path: &str, body: &str) -> Result<String, AxiError> {
        self.request("POST", path, Some(body))
    }

    fn request(&self, method: &str, path: &str, body: Option<&str>) -> Result<String, AxiError> {
        // RFC 3986: a scheme is case-insensitive, so `HTTP://` is the same cleartext as `http://`.
        let cleartext = self
            .base_url
            .get(..7)
            .is_some_and(|p| p.eq_ignore_ascii_case("http://"));
        if cleartext && !self.allow_insecure {
            return Err(
                AxiError::config("refusing to send a credential over plain http")
                    .with_code(CODE_INSECURE_URL),
            );
        }
        let url = format!("{}/{}", self.base_url, path.trim_start_matches('/'));
        let agent = ureq::AgentBuilder::new()
            .timeout(self.timeout)
            .redirects(0)
            .build();
        let mut req = agent
            .request(method, &url)
            .set("Authorization", &format!("Bearer {}", self.token))
            .set("Accept", "application/json");
        for (k, v) in &self.headers {
            req = req.set(k, v);
        }
        let sent = match body {
            Some(b) => req.set("Content-Type", "application/json").send_string(b),
            None => req.call(),
        };
        match sent {
            Ok(resp) => resp.into_string().map_err(|e| {
                AxiError::connection_failed(clean(&format!(
                    "reading the response from {url} failed: {e}"
                )))
            }),
            Err(ureq::Error::Status(code, resp)) => {
                let detail = resp.into_string().unwrap_or_default();
                Err(status_error(code, &url, &detail))
            }
            Err(e) => Err(AxiError::connection_failed(clean(&format!(
                "could not reach {url}: {e}"
            )))),
        }
    }
}

fn clean(text: &str) -> String {
    redact::redact(text)
}

fn status_error(code: u16, url: &str, detail: &str) -> AxiError {
    let snippet: String = clean(detail.trim()).chars().take(200).collect();
    let tail = if snippet.is_empty() {
        String::new()
    } else {
        format!(": {snippet}")
    };
    let message = format!("{url} answered {code}{tail}");
    match code {
        401 => AxiError::auth_failed(message).with_code(CODE_HTTP_UNAUTHORIZED),
        403 => AxiError::forbidden(message).with_code(CODE_HTTP_FORBIDDEN),
        404 => AxiError::not_found(message).with_code(CODE_HTTP_NOT_FOUND),
        _ => AxiError::api(message).with_code(CODE_HTTP_ERROR),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::errors::ErrorKind;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;

    /// Serve one canned response; return the base URL and a handle yielding the request text.
    fn serve(response: &'static str) -> (String, thread::JoinHandle<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let handle = thread::spawn(move || {
            let (mut s, _) = listener.accept().unwrap();
            let mut buf = [0u8; 4096];
            let n = s.read(&mut buf).unwrap();
            s.write_all(response.as_bytes()).unwrap();
            String::from_utf8_lossy(&buf[..n]).into_owned()
        });
        (url, handle)
    }

    const OK: &str =
        "HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}";

    #[test]
    fn a_get_sends_the_bearer_token_and_returns_the_body() {
        let (url, req) = serve(OK);
        let body = Client::new(url, "http-test-token-abcdef")
            .allow_insecure()
            .get("/v1/x")
            .unwrap();
        assert_eq!(body, "{\"ok\":true}");
        let req = req.join().unwrap();
        assert!(req.starts_with("GET /v1/x "), "{req}");
        assert!(req.contains("Bearer http-test-token-abcdef"));
    }

    #[test]
    fn plain_http_is_refused_by_default() {
        let err = Client::new("http://127.0.0.1:1", "http-test-token-abcdef")
            .get("/")
            .unwrap_err();
        assert_eq!(err.code.as_deref(), Some(CODE_INSECURE_URL));
    }

    #[test]
    fn statuses_map_to_error_kinds() {
        for (status, kind, code) in [
            (
                "401 Unauthorized",
                ErrorKind::AuthFailed,
                CODE_HTTP_UNAUTHORIZED,
            ),
            ("403 Forbidden", ErrorKind::Forbidden, CODE_HTTP_FORBIDDEN),
            ("404 Not Found", ErrorKind::NotFound, CODE_HTTP_NOT_FOUND),
            ("500 Internal Server Error", ErrorKind::Api, CODE_HTTP_ERROR),
            ("418 I'm a teapot", ErrorKind::Api, CODE_HTTP_ERROR),
        ] {
            let resp: &'static str = Box::leak(
                format!("HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    .into_boxed_str(),
            );
            let (url, h) = serve(resp);
            let err = Client::new(url, "http-test-token-abcdef")
                .allow_insecure()
                .get("/")
                .unwrap_err();
            h.join().unwrap();
            assert_eq!(err.kind, kind, "{status}");
            assert_eq!(err.code.as_deref(), Some(code), "{status}");
        }
    }

    #[test]
    fn the_literal_codes_are_the_closed_set() {
        assert_eq!(CODE_HTTP_UNAUTHORIZED, "HTTP_UNAUTHORIZED");
        assert_eq!(CODE_HTTP_FORBIDDEN, "HTTP_FORBIDDEN");
        assert_eq!(CODE_HTTP_NOT_FOUND, "HTTP_NOT_FOUND");
        assert_eq!(CODE_HTTP_ERROR, "HTTP_ERROR");
        let mut seen = std::collections::HashSet::new();
        assert!(CODES.iter().all(|c| seen.insert(*c)), "codes are distinct");
    }

    #[test]
    fn every_http_code_is_classifiable_once_a_tool_declares_it() {
        use crate::errors::{fault_class, CLASS_AUTH, CLASS_NOT_FOUND, CLASS_UNCLASSIFIED};
        let table = [
            (CODE_HTTP_UNAUTHORIZED, CLASS_AUTH),
            (CODE_HTTP_FORBIDDEN, CLASS_AUTH),
            (CODE_HTTP_NOT_FOUND, CLASS_NOT_FOUND),
            (CODE_HTTP_ERROR, "api"),
        ];
        for (status, code) in [
            (401, CODE_HTTP_UNAUTHORIZED),
            (403, CODE_HTTP_FORBIDDEN),
            (404, CODE_HTTP_NOT_FOUND),
            (500, CODE_HTTP_ERROR),
            (418, CODE_HTTP_ERROR),
        ] {
            let err = status_error(status, "https://host.example.com/x", "");
            assert_eq!(err.code.as_deref(), Some(code));
            assert_ne!(err.fault_class(&table), CLASS_UNCLASSIFIED, "{status}");
        }
        assert_eq!(fault_class(Some("HTTP_404"), &table), CLASS_UNCLASSIFIED);
    }

    #[test]
    fn the_cleartext_guard_ignores_scheme_case() {
        for base in [
            "HTTP://127.0.0.1:1",
            "Http://127.0.0.1:1",
            "hTTp://127.0.0.1:1",
        ] {
            let err = Client::new(base, "http-test-token-abcdef")
                .get("/")
                .unwrap_err();
            assert_eq!(err.code.as_deref(), Some(CODE_INSECURE_URL), "{base}");
        }
    }

    #[test]
    fn an_uppercase_https_scheme_is_not_refused() {
        // The guard passes; the request then fails to connect (nothing listens), not as cleartext.
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("HTTPS://{}", l.local_addr().unwrap());
        drop(l);
        let err = Client::new(url, "http-test-token-abcdef")
            .timeout(Duration::from_millis(500))
            .get("/")
            .unwrap_err();
        assert_ne!(err.code.as_deref(), Some(CODE_INSECURE_URL));
    }

    #[test]
    fn a_mixed_case_scheme_is_allowed_when_insecure_is_permitted() {
        let (url, req) = serve(OK);
        let url = url.replacen("http://", "HtTp://", 1);
        let body = Client::new(url, "http-test-token-abcdef")
            .allow_insecure()
            .get("/")
            .unwrap();
        assert_eq!(body, "{\"ok\":true}");
        req.join().unwrap();
    }

    #[test]
    fn a_token_echoed_by_the_server_never_reaches_the_message() {
        let token = "http-echoed-token-123456";
        let resp: &'static str = Box::leak(
            format!("HTTP/1.1 401 Unauthorized\r\nContent-Length: {}\r\nConnection: close\r\n\r\nbad {token}", 4 + token.len()).into_boxed_str(),
        );
        let (url, h) = serve(resp);
        let err = Client::new(url, token)
            .allow_insecure()
            .get("/")
            .unwrap_err();
        h.join().unwrap();
        assert!(!err.message.contains(token), "{}", err.message);
        assert!(err.message.contains("<redacted>"));
    }

    #[test]
    fn an_unreachable_host_is_a_connection_failure() {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", l.local_addr().unwrap());
        drop(l);
        let err = Client::new(url, "http-test-token-abcdef")
            .allow_insecure()
            .get("/")
            .unwrap_err();
        assert_eq!(err.kind, ErrorKind::ConnectionFailed);
    }
}
