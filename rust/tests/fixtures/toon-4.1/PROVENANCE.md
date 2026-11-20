# Fixture provenance

The files under `encode/` are the official TOON encoder conformance fixtures.

- Upstream: https://github.com/toon-format/spec
- Path upstream: `tests/fixtures/encode/`
- Spec version: v4.1.1
- Commit: 62f16b369408180f1faf1cba7da1b46d1f336f12
- License: MIT (see `LICENSE` in this directory)
- Copy: byte-for-byte; no file has been edited.

## Refreshing

1. Check out the upstream repository at the desired commit.
2. Copy `tests/fixtures/encode/*.json` over the files in `encode/` here, and the upstream `LICENSE` over `LICENSE`.
3. Update the spec version and commit above.
4. Run `cargo test`; the conformance test counts the cases it finds and requires every one to pass.
