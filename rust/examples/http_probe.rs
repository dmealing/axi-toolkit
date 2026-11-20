//! `http-probe get PATH`: read credentials from the environment, call a JSON API, print the body.
//!
//! Needs the `http` feature: `PROBE_URL=https://api.example.com PROBE_TOKEN=... cargo run
//! --features http --example http_probe -- get /v1/status`. A missing variable is reported as
//! an error whose recovery says exactly which variable to set.

use axi_toolkit::cli::{execute, AppSpec, CommandSpec, Handlers, Parsed};
use axi_toolkit::envconfig::{load, CredentialSpec, ProcessEnv};
use axi_toolkit::errors::{AxiError, Recovery};
use axi_toolkit::http::Client;
use axi_toolkit::render::view::Views;

const APP: AppSpec = AppSpec {
    bin: "http-probe",
    version: "0.1.0",
    noun: None,
    summary: "GET a path from a JSON API.",
    epilog: "",
    commands: &[CommandSpec {
        min_positionals: 1,
        max_positionals: 1,
        ..CommandSpec::new("get", "get PATH")
    }],
    globals: &[],
    refusal: None,
    help: None,
};

struct Probe {
    client: Option<Client>,
}

impl Handlers for Probe {
    fn resolve_context(&mut self, _globals: &Parsed) -> Result<(), AxiError> {
        let mut spec = CredentialSpec::new(["PROBE_URL"], ["PROBE_TOKEN"]);
        spec.verify = Some(
            Recovery::run(["get", "/"]).with_purpose("to verify the connection once both are set"),
        );
        // `load` registers the token with the redactor, so nothing below can print it.
        self.client = Some(Client::from_credentials(&load(&spec, &ProcessEnv, None)?));
        Ok(())
    }

    fn command(&mut self, _command: &CommandSpec, args: &Parsed) -> Result<String, AxiError> {
        let path = args.positional(0).unwrap_or("/");
        let client = self.client.as_ref().expect("resolve_context ran first");
        client.get(path)
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let code = execute(
        &APP,
        &argv,
        &mut Probe { client: None },
        &Views::default(),
        &mut std::io::stdout(),
    );
    std::process::exit(code);
}
