"""Connection settings, read from the environment and never from a file.

Both source tools open their configuration module with the same paragraph, and it is
the right one: a credential passed on a command line leaks into shell history and the
process table, and a credential in a file leaks into commits. The environment is the
only channel, and there is deliberately no ``--token`` flag anywhere.

The two copies were not identical, and the differences are real rather than
accidental: different variable names and aliases, one defaulting a bare host to
``https`` and the other to ``http``, one adding a default port and the other stripping
a mistakenly-pasted ``/api`` suffix. Every one of those is a property of the system
behind the tool, so none of them can be decided here. They live on a
:class:`CredentialSpec` the tool declares once, and this module reproduces each tool's
present behaviour under its own spec -- messages, codes and recovery included, byte
for byte, which ``tests/conformance`` asserts against both.

Three mechanisms are genuinely shared and are the reason this module exists at all:
the environment is the only source, a token that cannot be an HTTP header value is
rejected before anything sends it, and ``user:password@`` in a URL is separated off
and registered as a secret rather than carried into anything printable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .errors import ConfigError, Recovery
from .redact import register_secret

__all__ = [
    "DEFAULT_TIMEOUT",
    "ILLEGAL_TOKEN",
    "CredentialSpec",
    "Credentials",
    "describe_environment",
    "first_env",
    "load",
    "missing_vars",
    "normalize_base_url",
    "setup_recovery",
    "split_userinfo",
]

DEFAULT_TIMEOUT = 30.0

#: Anything a token must not contain. A header value cannot carry a line break, and an
#: HTTP client raises a ``ValueError`` embedding the whole ``Bearer ...`` header when it
#: finds one -- which is a credential inside a traceback. So the check happens at the
#: point the value is read, not at the point it is encoded.
ILLEGAL_TOKEN = re.compile(r"[\s\x00-\x1f\x7f]")

_SCHEMES = ("http", "https")


@dataclass(frozen=True)
class CredentialSpec:
    """How one tool reads its credentials from the environment.

    Everything here is a fact about the system the tool talks to, which is why it is
    declared by the tool rather than defaulted by this module. The one exception is
    ``default_scheme``: it defaults to ``https`` because a bare host that silently
    became ``http://`` would send the credential in the clear, and a tool that wants
    the other answer has to say so and say why.
    """

    #: Variable names for the base URL, most-preferred first. Later names are aliases
    #: accepted so an existing shell environment keeps working.
    url_vars: tuple
    #: Variable names for the credential, most-preferred first.
    token_vars: tuple
    #: What to set each variable to. One per variable, in the same order.
    setup: tuple = ()
    #: How to confirm the settings work once both are present -- typically the tool's
    #: own ``doctor``. Kept apart from ``setup`` so a caller already inside ``doctor``
    #: can leave it out rather than telling the user to run what they are running.
    verify: Recovery | None = None
    #: What to check when the credential carries a character a header cannot.
    token_recovery: tuple = ()
    #: The scheme a bare host gets. ``https`` unless the system genuinely serves plain
    #: HTTP on a local network, in which case defaulting to TLS fails every first run.
    default_scheme: str = "https"
    #: A port appended to a host that names none. ``None`` where a missing port means
    #: the default for the scheme.
    default_port: int | None = None
    #: A path suffix stripped from the base URL -- a common paste mistake where a tool's
    #: API root is a well-known subpath of the instance root.
    strip_path_suffix: str = ""
    default_timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.url_vars or not self.token_vars:
            raise ValueError("a credential spec names at least one URL and one token variable")
        if self.default_scheme not in _SCHEMES:
            raise ValueError(
                f"default_scheme must be one of {_SCHEMES}, got {self.default_scheme!r}"
            )


@dataclass(frozen=True)
class Credentials:
    """A resolved, ready-to-use configuration.

    Carries the variable names it was resolved from, which the source tools threw away
    and then re-read the environment to recover. A caller reporting on its own
    configuration should not have to ask twice.
    """

    base_url: str
    token: str
    timeout: float = DEFAULT_TIMEOUT
    url_var: str = ""
    token_var: str = ""


def first_env(names: tuple, environ) -> tuple:
    """The first of ``names`` set to something other than whitespace, and its value."""
    for name in names:
        value = environ.get(name)
        if value and value.strip():
            return name, value.strip()
    return None, None


def split_userinfo(netloc: str) -> tuple:
    """Separate any ``user:password@`` prefix from a network location.

    Such credentials are never sent -- these tools authenticate with their own token --
    but they must not survive into the base URL either, because a tool's own status
    view prints that URL and those views end up in agent transcripts.
    """
    if "@" not in netloc:
        return "", netloc
    userinfo, _, host = netloc.rpartition("@")
    return userinfo, host


def normalize_base_url(raw: str, spec: CredentialSpec) -> str:
    """Accept a bare host, apply ``spec``'s defaults, and drop any trailing path noise."""
    value = raw.strip().rstrip("/")
    if "://" not in value:
        value = f"{spec.default_scheme}://{value}"
    parts = urlsplit(value)
    if not parts.netloc:
        raise ConfigError(
            f"{spec.url_vars[0]} is not a usable URL: {value!r}",
            recovery=spec.setup[:1],
            code="BAD_URL",
        )
    if parts.scheme not in _SCHEMES:
        raise ConfigError(
            f"{spec.url_vars[0]} must use http or https, got {parts.scheme!r}",
            recovery=spec.setup[:1],
            code="BAD_URL",
        )
    path = parts.path.rstrip("/")
    if spec.strip_path_suffix and path.endswith(spec.strip_path_suffix):
        path = path[: -len(spec.strip_path_suffix)]
    userinfo, host = split_userinfo(parts.netloc)
    if userinfo:
        # Registered before returning: from here on the value can only be printed
        # through the redacting output boundary.
        register_secret(userinfo, min_length=4)
        _, _, password = userinfo.partition(":")
        register_secret(password, min_length=4)
    if spec.default_port and ":" not in host.rsplit("]", 1)[-1]:
        # ``rsplit("]")`` so a bracketed IPv6 literal's own colons are not read as a
        # port that is already there.
        host = f"{host}:{spec.default_port}"
    return urlunsplit((parts.scheme, host, path, "", ""))


def load(spec: CredentialSpec, environ=None, *, timeout: float | None = None) -> Credentials:
    """Resolve credentials, or raise :class:`ConfigError` naming what is absent."""
    environ = os.environ if environ is None else environ
    url_var, raw_url = first_env(spec.url_vars, environ)
    token_var, token = first_env(spec.token_vars, environ)

    missing = []
    if not raw_url:
        missing.append(spec.url_vars[0])
    if not token:
        missing.append(spec.token_vars[0])
    if missing:
        names = " and ".join(missing)
        plural = "are" if len(missing) > 1 else "is"
        raise ConfigError(
            f"{names} {plural} not set in the environment",
            recovery=setup_recovery(spec),
            code="NOT_CONFIGURED",
        )

    if ILLEGAL_TOKEN.search(token):
        # The message names the variable and never the value: a rejected credential is
        # still a credential, and an error message is printed.
        raise ConfigError(
            f"{spec.token_vars[0]} contains whitespace or a control character",
            recovery=spec.token_recovery,
            code="BAD_TOKEN",
        )

    # Registered at the moment it is read, so no later code path can print it.
    register_secret(token)
    return Credentials(
        base_url=normalize_base_url(raw_url, spec),
        token=token,
        timeout=spec.default_timeout if timeout is None else timeout,
        url_var=url_var or "",
        token_var=token_var or "",
    )


def setup_recovery(spec: CredentialSpec, *, include_verify: bool = True) -> tuple:
    """The guidance offered wherever configuration is found to be absent."""
    if include_verify and spec.verify is not None:
        return (*spec.setup, spec.verify)
    return tuple(spec.setup)


def missing_vars(spec: CredentialSpec, environ=None) -> list:
    """The primary variable names that are absent, in the order to report them."""
    described = describe_environment(spec, environ)
    missing = []
    if not described["url_set"]:
        missing.append(spec.url_vars[0])
    if not described["token_set"]:
        missing.append(spec.token_vars[0])
    return missing


def describe_environment(spec: CredentialSpec, environ=None) -> dict:
    """Report which variables are set without ever revealing the credential."""
    environ = os.environ if environ is None else environ
    url_var, raw_url = first_env(spec.url_vars, environ)
    token_var, token = first_env(spec.token_vars, environ)
    return {
        "url_var": url_var or "",
        "url_set": bool(raw_url),
        "token_var": token_var or "",
        "token_set": bool(token),
    }
