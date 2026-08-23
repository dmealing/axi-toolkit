"""How each source tool would declare itself, in this package's vocabulary.

These are the *subject* declarations: what a tool passes to
:mod:`axi_core.envconfig` and :mod:`axi_core.redact` once it takes this package. They
live in the conformance suite rather than in ``src/`` because they belong to the two
tools, not to the library -- and because their whole job here is to be judged against
what those tools actually do today.

Nothing in this file is an expected value. Every expectation is in
``capture.json``, machine-written by running the tools' own code.
"""

from __future__ import annotations

from axi_core.envconfig import CredentialSpec
from axi_core.errors import note, run, set_env

__all__ = ["HA", "HA_PATTERNS", "PATTERNS", "PLEX", "PLEX_PATTERNS", "SPECS"]


HA = CredentialSpec(
    # The `hass-cli` spellings are accepted as fallbacks so an existing Home Assistant
    # shell environment works unchanged.
    url_vars=("HA_URL", "HASS_SERVER"),
    token_vars=("HA_TOKEN", "HASS_TOKEN"),
    setup=(
        set_env(
            "HA_URL",
            "your Home Assistant base URL",
            example="export HA_URL=https://homeassistant.example.com",
        ),
        set_env(
            "HA_TOKEN",
            "a long-lived access token from your Home Assistant profile page, under Security",
        ),
    ),
    verify=run(("doctor",), purpose="to verify the connection once both are set"),
    token_recovery=(
        note("A long-lived access token is a single unbroken string; check for a line break"),
        note(
            "If it was read from a file, strip the trailing newline, "
            "e.g. HA_TOKEN=$(tr -d '\\n' < token.txt)"
        ),
    ),
    # A bare host that silently became http:// would send the access token in the clear.
    default_scheme="https",
    # A base URL already pointing at the API root is a common paste mistake.
    strip_path_suffix="/api",
)


PLEX = CredentialSpec(
    url_vars=("PLEX_URL", "PLEX_SERVER", "PLEX_BASEURL"),
    token_vars=("PLEX_TOKEN", "PLEX_API_TOKEN"),
    setup=(
        set_env(
            "PLEX_URL",
            "your server's local address",
            example="export PLEX_URL=http://plex.example.com:32400",
        ),
        set_env(
            "PLEX_TOKEN",
            "a Plex access token",
            reference="https://support.plex.tv/articles/204059436",
        ),
    ),
    verify=run(("doctor",), purpose="to verify the connection once both are set"),
    token_recovery=(
        note("A Plex token is a single unbroken string; check for a line break"),
        note(
            "If it was read from a file, strip the trailing newline, "
            "e.g. PLEX_TOKEN=$(tr -d '\\n' < token.txt)"
        ),
    ),
    # A Plex Media Server on the local network serves plain HTTP on 32400, and
    # defaulting to https would fail every first run.
    default_scheme="http",
    default_port=32400,
)


#: This tool adds no credential shape beyond the two built in: the system it talks to
#: issues JWTs, which the built-in rule already covers.
HA_PATTERNS: tuple = ()

#: Three shapes for a credential that travels in a URL as well as in a header. Each
#: keeps its prefix so a reader can still see which credential was suppressed.
PLEX_PATTERNS = (
    r"(?i)(X-Plex-Token=)[A-Za-z0-9._~-]{4,}",
    r"(?i)([?&]token=)[A-Za-z0-9._~-]{8,}",
    r"(?i)(X-Plex-Token['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9._~-]{8,}",
)


SPECS = {"ha": HA, "plex": PLEX}
PATTERNS = {"ha": HA_PATTERNS, "plex": PLEX_PATTERNS}
