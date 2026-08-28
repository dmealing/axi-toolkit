"""Environment-only credentials, under each tool's own spec.

The byte-for-byte reproduction of both tools' messages, recovery and URL normalisation
is generated -- those are captured facts. This file states the mechanisms in the open:
the environment is the only channel, a token that cannot be an HTTP header value is
refused before anything sends it, userinfo never survives into anything printable, and
a spec that says nothing sensible is refused when it is built rather than when it is
used.
"""

from __future__ import annotations

import pytest

from axi_toolkit import envconfig, redact
from axi_toolkit.envconfig import Credentials, CredentialSpec
from axi_toolkit.errors import ConfigError, note, run, set_env
from axi_toolkit.render import cli

TOKEN = "probe-" + "0123456789abcdef"

SPEC = CredentialSpec(
    url_vars=("EXAMPLE_URL", "EXAMPLE_SERVER"),
    token_vars=("EXAMPLE_TOKEN", "EXAMPLE_API_TOKEN"),
    setup=(
        set_env(
            "EXAMPLE_URL", "the base URL", example="export EXAMPLE_URL=https://host.example.com"
        ),
        set_env("EXAMPLE_TOKEN", "an access token"),
    ),
    verify=run(("doctor",), purpose="to verify the connection once both are set"),
    token_recovery=(note("An access token is a single unbroken string; check for a line break"),),
    strip_path_suffix="/api",
)


@pytest.fixture(autouse=True)
def _clean_boundary():
    redact.reset_secrets()
    yield
    redact.reset_secrets()


# -------------------------------------------------------------- reading the env


def test_the_primary_variables_are_read():
    resolved = envconfig.load(
        SPEC, {"EXAMPLE_URL": "https://host.example.com", "EXAMPLE_TOKEN": TOKEN}
    )
    assert resolved == Credentials(
        base_url="https://host.example.com",
        token=TOKEN,
        timeout=30.0,
        url_var="EXAMPLE_URL",
        token_var="EXAMPLE_TOKEN",
    )


def test_an_alias_is_accepted_and_the_primary_wins_over_it():
    aliased = envconfig.load(
        SPEC, {"EXAMPLE_SERVER": "https://alias.example.com", "EXAMPLE_TOKEN": TOKEN}
    )
    assert aliased.base_url == "https://alias.example.com"
    assert aliased.url_var == "EXAMPLE_SERVER"

    both = envconfig.load(
        SPEC,
        {
            "EXAMPLE_URL": "https://primary.example.com",
            "EXAMPLE_SERVER": "https://alias.example.com",
            "EXAMPLE_TOKEN": TOKEN,
        },
    )
    assert both.base_url == "https://primary.example.com"


def test_the_resolved_configuration_says_which_variables_it_came_from():
    """The source tools threw this away and re-read the environment to recover it."""
    resolved = envconfig.load(
        SPEC, {"EXAMPLE_SERVER": "https://host.example.com", "EXAMPLE_API_TOKEN": TOKEN}
    )
    assert (resolved.url_var, resolved.token_var) == ("EXAMPLE_SERVER", "EXAMPLE_API_TOKEN")


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "EXAMPLE_URL and EXAMPLE_TOKEN are"),
        ({"EXAMPLE_URL": "https://host.example.com"}, "EXAMPLE_TOKEN is"),
        ({"EXAMPLE_TOKEN": TOKEN}, "EXAMPLE_URL is"),
        ({"EXAMPLE_URL": "   ", "EXAMPLE_TOKEN": TOKEN}, "EXAMPLE_URL is"),
    ],
)
def test_what_is_absent_is_named(environ, expected):
    with pytest.raises(ConfigError) as caught:
        envconfig.load(SPEC, environ)
    assert expected in caught.value.message
    assert caught.value.code == "NOT_CONFIGURED"
    assert caught.value.recovery


def test_the_recovery_for_an_absent_variable_is_data_not_a_rendered_line():
    with pytest.raises(ConfigError) as caught:
        envconfig.load(SPEC, {})
    assert [item.kind for item in caught.value.recovery] == ["set_env", "set_env", "run"]
    assert cli.lines(caught.value.recovery, "example-axi")[-1] == (
        "Run `example-axi doctor` to verify the connection once both are set"
    )


def test_the_verify_step_can_be_left_out_by_a_caller_already_inside_it():
    """`doctor` telling you to run `doctor` is noise in the one place it is read."""
    assert len(envconfig.setup_recovery(SPEC)) == 3
    assert len(envconfig.setup_recovery(SPEC, include_verify=False)) == 2


def test_missing_vars_reports_the_primary_names_in_order():
    assert envconfig.missing_vars(SPEC, {}) == ["EXAMPLE_URL", "EXAMPLE_TOKEN"]
    assert envconfig.missing_vars(SPEC, {"EXAMPLE_URL": "https://host.example.com"}) == [
        "EXAMPLE_TOKEN"
    ]


def test_the_environment_report_never_reveals_the_credential():
    described = envconfig.describe_environment(
        SPEC, {"EXAMPLE_URL": "https://host.example.com", "EXAMPLE_TOKEN": TOKEN}
    )
    assert described == {
        "url_var": "EXAMPLE_URL",
        "url_set": True,
        "token_var": "EXAMPLE_TOKEN",
        "token_set": True,
    }
    assert TOKEN not in repr(described)


# ------------------------------------------------------------- the token guard


@pytest.mark.parametrize("bad", [" ", "\n", "\t", "\r", "\x00", "\x7f"])
def test_a_token_that_cannot_be_a_header_value_is_refused_before_use(bad):
    """An HTTP client raises a ValueError embedding the whole header when it finds one.

    That is a credential inside a traceback, so the check happens where the value is
    read rather than where it is encoded.
    """
    with pytest.raises(ConfigError) as caught:
        envconfig.load(
            SPEC, {"EXAMPLE_URL": "https://host.example.com", "EXAMPLE_TOKEN": f"abc{bad}def"}
        )
    assert caught.value.code == "BAD_TOKEN"


def test_the_rejection_message_names_the_variable_and_never_the_value():
    """A rejected credential is still a credential, and an error message is printed."""
    with pytest.raises(ConfigError) as caught:
        envconfig.load(
            SPEC, {"EXAMPLE_URL": "https://host.example.com", "EXAMPLE_TOKEN": "abc def"}
        )
    assert "EXAMPLE_TOKEN" in caught.value.message
    assert "abc" not in caught.value.message


def test_reading_a_token_registers_it_as_a_secret():
    envconfig.load(SPEC, {"EXAMPLE_URL": "https://host.example.com", "EXAMPLE_TOKEN": TOKEN})
    assert redact.redact(f"leaked {TOKEN}") == "leaked <redacted>"


# ------------------------------------------------------------ URL normalisation


def test_a_bare_host_takes_the_specs_scheme():
    assert envconfig.normalize_base_url("host.example.com", SPEC) == "https://host.example.com"
    plain = CredentialSpec(url_vars=("U",), token_vars=("T",), default_scheme="http")
    assert envconfig.normalize_base_url("host.example.com", plain) == "http://host.example.com"


def test_an_explicit_scheme_is_always_honoured():
    assert (
        envconfig.normalize_base_url("http://host.example.com", SPEC) == "http://host.example.com"
    )


def test_a_default_port_is_added_only_when_the_host_names_none():
    ported = CredentialSpec(
        url_vars=("U",), token_vars=("T",), default_scheme="http", default_port=32400
    )
    assert (
        envconfig.normalize_base_url("host.example.com", ported) == "http://host.example.com:32400"
    )
    assert (
        envconfig.normalize_base_url("host.example.com:8443", ported)
        == "http://host.example.com:8443"
    )


def test_an_ipv6_literals_own_colons_are_not_mistaken_for_a_port():
    ported = CredentialSpec(
        url_vars=("U",), token_vars=("T",), default_scheme="http", default_port=32400
    )
    assert (
        envconfig.normalize_base_url("http://[2001:db8::1]", ported) == "http://[2001:db8::1]:32400"
    )
    assert (
        envconfig.normalize_base_url("http://[2001:db8::1]:32400", ported)
        == "http://[2001:db8::1]:32400"
    )


def test_a_declared_path_suffix_is_stripped_and_others_are_kept():
    """A base URL already pointing at the API root is a common paste mistake."""
    assert (
        envconfig.normalize_base_url("https://host.example.com/api", SPEC)
        == "https://host.example.com"
    )
    assert (
        envconfig.normalize_base_url("https://proxy.example.com/prefix", SPEC)
        == "https://proxy.example.com/prefix"
    )


def test_trailing_slashes_and_surrounding_whitespace_are_trimmed():
    assert (
        envconfig.normalize_base_url("  https://host.example.com/  ", SPEC)
        == "https://host.example.com"
    )


@pytest.mark.parametrize("raw", ["", "://nope"])
def test_an_unusable_url_is_refused_by_name(raw):
    with pytest.raises(ConfigError) as caught:
        envconfig.normalize_base_url(raw, SPEC)
    assert caught.value.code == "BAD_URL"
    assert "EXAMPLE_URL" in caught.value.message


def test_a_scheme_that_is_not_http_or_https_is_refused():
    with pytest.raises(ConfigError, match="http or https"):
        envconfig.normalize_base_url("ftp://host.example.com", SPEC)


# ------------------------------------------------------------------- userinfo


def test_url_credentials_are_stripped_and_registered_as_secrets():
    """A tool's own status view prints the base URL, and those views reach transcripts."""
    resolved = envconfig.normalize_base_url("https://someone:example-secret@host.example.com", SPEC)
    assert resolved == "https://host.example.com"
    assert redact.redact("password is example-secret") == "password is <redacted>"
    assert redact.redact("pair is someone:example-secret") == "pair is <redacted>"


def test_split_userinfo_takes_the_last_at_sign():
    """A password may itself contain an @, and the host is what follows the last one."""
    assert envconfig.split_userinfo("host.example.com") == ("", "host.example.com")
    assert envconfig.split_userinfo("a:b@host.example.com") == ("a:b", "host.example.com")
    assert envconfig.split_userinfo("a:b@c@host.example.com") == ("a:b@c", "host.example.com")


# ------------------------------------------------------------------ the spec


def test_a_spec_that_names_no_variable_is_refused_when_it_is_built():
    with pytest.raises(ValueError, match="at least one URL and one token"):
        CredentialSpec(url_vars=(), token_vars=("T",))
    with pytest.raises(ValueError, match="at least one URL and one token"):
        CredentialSpec(url_vars=("U",), token_vars=())


def test_a_spec_cannot_default_to_a_scheme_the_loader_would_then_refuse():
    with pytest.raises(ValueError, match="default_scheme"):
        CredentialSpec(url_vars=("U",), token_vars=("T",), default_scheme="ftp")


def test_first_env_skips_whitespace_only_values():
    assert envconfig.first_env(("A", "B"), {"A": "  ", "B": "value"}) == ("B", "value")
    assert envconfig.first_env(("A",), {}) == (None, None)


def test_a_timeout_argument_overrides_the_specs_default():
    spec = CredentialSpec(url_vars=("U",), token_vars=("T",), default_timeout=5.0)
    environ = {"U": "https://host.example.com", "T": TOKEN}
    assert envconfig.load(spec, environ).timeout == 5.0
    assert envconfig.load(spec, environ, timeout=90.0).timeout == 90.0
