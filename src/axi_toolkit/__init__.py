"""Shared toolkit for Agent eXperience Interface (AXI) command-line tools.

Two AXI CLIs measured 1 378 identical lines of toolkit between them, and the
duplication had already cost: a TOON specification violation was fixed in one copy and
not the other, and the divergence stayed invisible until somebody ran both encoders
against the same fixtures. This package is the one copy.

What is here is the toolkit tier and nothing else:

- :mod:`axi_toolkit.toon` -- a strict TOON encoder, and :mod:`axi_toolkit.toon_spec`, the
  specification's own conformance fixtures vendored beside it so a tool asserts its
  score rather than claiming one.
- :mod:`axi_toolkit.errors` -- the error contract, with recovery carried as data.
- :mod:`axi_toolkit.render` -- that data as a shell line, or as a sentence.
- :mod:`axi_toolkit.redact` -- the credential boundary.
- :mod:`axi_toolkit.envconfig` -- environment-only credentials.

What is deliberately not here: an agent package, framework adapters, an MCP server, a
dual sync/async API, and any client class wrapping an HTTP library. The agent surface
of a pure function is its own signature; every framework derives a schema from
annotations, so there is no adapter worth writing. Nothing in this package imports an
HTTP or WebSocket client, the distribution declares no runtime dependency, and
``tests/test_purity.py`` is what keeps both true.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
