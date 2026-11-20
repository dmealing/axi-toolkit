//! Run a subprocess with a timeout, capture its output, and keep secrets out of both directions.
//!
//! * **Secrets never travel on argv.** A command line is visible to every user of the machine
//!   (`ps`) and lands in shell history; [`Command::run`] refuses to start a process whose
//!   program or arguments contain a literal registered with the shared redactor
//!   ([`crate::redact`]). A secret goes to the child through [`Command::secret_env`] or
//!   [`Command::stdin`].
//! * **Captured output is redacted** before it is returned, so what the child printed can be
//!   passed straight to the output boundary.
//! * **A child never outlives its timeout.** On expiry it is killed and the partial output comes
//!   back with [`ProcError::TimedOut`].
//!
//! `std` only: the wait is a short poll, and the pipes are drained on their own threads so a
//! chatty child cannot fill one and deadlock.

use crate::errors::AxiError;
use crate::redact;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Child, Stdio};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// The default time a child may run.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);
/// The default cap on each captured stream, in bytes. Output past it is read and discarded.
pub const DEFAULT_MAX_OUTPUT: usize = 8 * 1024 * 1024;

/// The code of an error from a command line that carried a secret.
pub const CODE_SECRET_ON_ARGV: &str = "SECRET_ON_ARGV";
/// The code of an error from a program that could not be started.
pub const CODE_SPAWN_FAILED: &str = "SPAWN_FAILED";
/// The code of an error from a program that ran past its timeout.
pub const CODE_TIMED_OUT: &str = "TIMED_OUT";

/// A completed child: it ran to the end, whatever its exit status.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Output {
    /// The exit status, or `None` when a signal ended the process.
    pub status: Option<i32>,
    /// Captured standard output, lossily decoded and redacted.
    pub stdout: String,
    /// Captured standard error, lossily decoded and redacted.
    pub stderr: String,
    /// Whether either stream exceeded the cap and was cut.
    pub truncated: bool,
}

impl Output {
    /// Whether the child exited with status 0.
    pub fn success(&self) -> bool {
        self.status == Some(0)
    }
}

/// Why a child produced no [`Output`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProcError {
    /// The program or an argument contained a registered secret; nothing was started.
    SecretOnArgv {
        /// The position of the offending word: 0 is the program, 1 the first argument.
        index: usize,
    },
    /// The program could not be started (not found, not executable, ...).
    Spawn {
        /// The program as named.
        program: String,
        /// The operating system's reason, redacted.
        reason: String,
    },
    /// The child ran past its timeout and was killed.
    TimedOut {
        /// The limit it exceeded.
        timeout: Duration,
        /// What it had printed, redacted.
        stdout: String,
        /// What it had printed to stderr, redacted.
        stderr: String,
    },
}

impl std::fmt::Display for ProcError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProcError::SecretOnArgv { index } => write!(
                f,
                "word {index} of the command line holds a registered secret; pass it through the environment or stdin"
            ),
            ProcError::Spawn { program, reason } => write!(f, "could not start {program}: {reason}"),
            ProcError::TimedOut { timeout, .. } => {
                write!(f, "the command ran past its {}s timeout and was killed", timeout.as_secs_f64())
            }
        }
    }
}

impl std::error::Error for ProcError {}

impl From<ProcError> for AxiError {
    fn from(e: ProcError) -> AxiError {
        let code = match e {
            ProcError::SecretOnArgv { .. } => CODE_SECRET_ON_ARGV,
            ProcError::Spawn { .. } => CODE_SPAWN_FAILED,
            ProcError::TimedOut { .. } => CODE_TIMED_OUT,
        };
        AxiError::general(redact::redact(&e.to_string())).with_code(code)
    }
}

/// A subprocess to run. Build with [`Command::new`] and finish with [`Command::run`].
#[derive(Debug, Clone)]
pub struct Command {
    program: String,
    args: Vec<String>,
    env: Vec<(String, String)>,
    env_clear: bool,
    stdin: Option<Vec<u8>>,
    timeout: Duration,
    max_output: usize,
    cwd: Option<PathBuf>,
}

impl Command {
    /// A command running `program` (looked up on `PATH`).
    pub fn new(program: impl Into<String>) -> Command {
        Command {
            program: program.into(),
            args: Vec::new(),
            env: Vec::new(),
            env_clear: false,
            stdin: None,
            timeout: DEFAULT_TIMEOUT,
            max_output: DEFAULT_MAX_OUTPUT,
            cwd: None,
        }
    }

    /// Append one argument. Never a secret: see [`Command::secret_env`].
    #[must_use]
    pub fn arg(mut self, arg: impl Into<String>) -> Command {
        self.args.push(arg.into());
        self
    }

    /// Append several arguments.
    #[must_use]
    pub fn args<I, S>(mut self, args: I) -> Command
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        self.args.extend(args.into_iter().map(Into::into));
        self
    }

    /// Set an environment variable for the child.
    #[must_use]
    pub fn env(mut self, name: impl Into<String>, value: impl Into<String>) -> Command {
        self.env.push((name.into(), value.into()));
        self
    }

    /// Set an environment variable carrying a secret: the value is registered with the shared
    /// redactor, so it is removed from anything the child prints and refused on any argv.
    #[must_use]
    pub fn secret_env(self, name: impl Into<String>, value: impl Into<String>) -> Command {
        let value = value.into();
        redact::register_secret_min(&value, 4);
        self.env(name, value)
    }

    /// Start the child with an empty environment (plus whatever is set on the command).
    #[must_use]
    pub fn env_clear(mut self) -> Command {
        self.env_clear = true;
        self
    }

    /// Bytes written to the child's standard input, which is then closed. Without this the
    /// child's stdin is closed immediately.
    #[must_use]
    pub fn stdin(mut self, data: impl Into<Vec<u8>>) -> Command {
        self.stdin = Some(data.into());
        self
    }

    /// How long the child may run; after that it is killed. Default [`DEFAULT_TIMEOUT`].
    #[must_use]
    pub fn timeout(mut self, timeout: Duration) -> Command {
        self.timeout = timeout;
        self
    }

    /// The cap on each captured stream, in bytes. Default [`DEFAULT_MAX_OUTPUT`].
    #[must_use]
    pub fn max_output(mut self, bytes: usize) -> Command {
        self.max_output = bytes;
        self
    }

    /// Run the child in `dir`.
    #[must_use]
    pub fn current_dir(mut self, dir: impl Into<PathBuf>) -> Command {
        self.cwd = Some(dir.into());
        self
    }

    /// Start the child, wait for it up to the timeout, and return what it printed.
    ///
    /// # Errors
    /// [`ProcError::SecretOnArgv`] before anything starts, [`ProcError::Spawn`] when the program
    /// cannot be started, and [`ProcError::TimedOut`] when the child is killed at its timeout.
    pub fn run(&self) -> Result<Output, ProcError> {
        for (index, word) in std::iter::once(&self.program).chain(&self.args).enumerate() {
            if redact::contains_secret(word) {
                return Err(ProcError::SecretOnArgv { index });
            }
        }
        let mut cmd = std::process::Command::new(&self.program);
        cmd.args(&self.args)
            .stdin(if self.stdin.is_some() {
                Stdio::piped()
            } else {
                Stdio::null()
            })
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if self.env_clear {
            cmd.env_clear();
        }
        cmd.envs(self.env.iter().map(|(k, v)| (k, v)));
        if let Some(dir) = &self.cwd {
            cmd.current_dir(dir);
        }
        let mut child = cmd.spawn().map_err(|e| ProcError::Spawn {
            program: self.program.clone(),
            reason: redact::redact(&e.to_string()),
        })?;

        if let (Some(data), Some(mut pipe)) = (self.stdin.clone(), child.stdin.take()) {
            // A child that exits without reading its stdin closes the pipe; that is not ours to report.
            thread::spawn(move || {
                let _ = pipe.write_all(&data);
            });
        }
        let out = drain(child.stdout.take(), self.max_output);
        let err = drain(child.stderr.take(), self.max_output);

        let deadline = Instant::now() + self.timeout;
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) if Instant::now() >= deadline => break None,
                Ok(None) => thread::sleep(Duration::from_millis(5)),
                Err(_) => break None,
            }
        };
        let _ = child.kill_if(status.is_none());
        let _ = child.wait();
        // Whatever a grandchild still holds open must not hold this call hostage.
        let ((stdout, t1), (stderr, t2)) = (out.collect(), err.collect());
        let (stdout, stderr) = (
            redact::redact(&String::from_utf8_lossy(&stdout)),
            redact::redact(&String::from_utf8_lossy(&stderr)),
        );
        match status {
            Some(status) => Ok(Output {
                status: status.code(),
                stdout,
                stderr,
                truncated: t1 || t2,
            }),
            None => Err(ProcError::TimedOut {
                timeout: self.timeout,
                stdout,
                stderr,
            }),
        }
    }
}

/// Kill a child that has not exited. Only the direct child is killed: a grandchild it started
/// keeps running, so a command that spawns helpers should `exec` the one that matters.
trait KillIf {
    fn kill_if(&mut self, expired: bool) -> std::io::Result<()>;
}

impl KillIf for Child {
    fn kill_if(&mut self, expired: bool) -> std::io::Result<()> {
        if expired {
            self.kill()
        } else {
            Ok(())
        }
    }
}

/// A pipe being read on its own thread: what has arrived so far, and a signal that it ended.
struct Drain {
    buf: Arc<Mutex<(Vec<u8>, bool)>>,
    done: mpsc::Receiver<()>,
}

impl Drain {
    /// What was read, waiting a moment for the reader to reach the end of the stream.
    fn collect(self) -> (Vec<u8>, bool) {
        let _ = self.done.recv_timeout(Duration::from_millis(1000));
        let guard = self.buf.lock().unwrap_or_else(|p| p.into_inner());
        guard.clone()
    }
}

/// Read a pipe to the end on its own thread, keeping at most `cap` bytes.
fn drain<R: Read + Send + 'static>(pipe: Option<R>, cap: usize) -> Drain {
    let buf = Arc::new(Mutex::new((Vec::new(), false)));
    let (tx, rx) = mpsc::channel();
    let shared = Arc::clone(&buf);
    thread::spawn(move || {
        if let Some(mut pipe) = pipe {
            let mut chunk = [0u8; 8192];
            while let Ok(n) = pipe.read(&mut chunk) {
                if n == 0 {
                    break;
                }
                let mut guard = shared.lock().unwrap_or_else(|p| p.into_inner());
                let room = cap.saturating_sub(guard.0.len());
                if n > room {
                    guard.1 = true;
                }
                guard.0.extend_from_slice(&chunk[..n.min(room)]);
            }
        }
        let _ = tx.send(());
    });
    Drain { buf, done: rx }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sh(script: &str) -> Command {
        Command::new("sh").arg("-c").arg(script)
    }

    #[test]
    fn captures_stdout_stderr_and_status() {
        let out = sh("echo out; echo err >&2; exit 3").run().unwrap();
        assert_eq!(out.stdout, "out\n");
        assert_eq!(out.stderr, "err\n");
        assert_eq!(out.status, Some(3));
        assert!(!out.success());
    }

    #[test]
    fn stdin_reaches_the_child() {
        let out = Command::new("cat").stdin("from stdin").run().unwrap();
        assert_eq!(out.stdout, "from stdin");
    }

    #[test]
    fn a_child_past_its_timeout_is_killed() {
        let started = Instant::now();
        let err = sh("echo early; exec sleep 30")
            .timeout(Duration::from_millis(200))
            .run()
            .unwrap_err();
        assert!(started.elapsed() < Duration::from_secs(10));
        match err {
            ProcError::TimedOut { stdout, .. } => assert_eq!(stdout, "early\n"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_secret_in_the_environment_is_redacted_from_the_output() {
        let secret = "proc-test-secret-0123456789";
        let out = sh("echo \"$PROC_TEST_VAR\"")
            .secret_env("PROC_TEST_VAR", secret)
            .run()
            .unwrap();
        assert_eq!(out.stdout, "<redacted>\n");
    }

    #[test]
    fn a_secret_on_argv_is_refused_before_anything_starts() {
        let secret = "proc-test-argv-secret-987654";
        redact::register_secret(secret);
        let err = Command::new("echo").arg(secret).run().unwrap_err();
        assert_eq!(err, ProcError::SecretOnArgv { index: 1 });
        let axi: AxiError = err.into();
        assert_eq!(axi.code.as_deref(), Some(CODE_SECRET_ON_ARGV));
        assert!(!axi.message.contains(secret));
    }

    #[test]
    fn output_past_the_cap_is_cut_and_the_child_still_finishes() {
        let out = sh("head -c 100000 /dev/zero | tr '\\0' x")
            .max_output(1000)
            .run()
            .unwrap();
        assert_eq!(out.stdout.len(), 1000);
        assert!(out.truncated);
    }

    #[test]
    fn a_missing_program_is_a_spawn_error() {
        let err = Command::new("definitely-not-a-program-axi")
            .run()
            .unwrap_err();
        assert!(matches!(err, ProcError::Spawn { .. }));
    }
}
