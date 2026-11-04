#!/usr/bin/env python3
"""Write the language-neutral conformance pack in ``conformance/``.

    scripts/conformance_pack.py            write every file of the pack

The pack is built by ``tests/conformance/pack.py`` from the committed capture and the
package itself, so it needs no source checkout and no network. ``tests/test_conformance_pack.py``
makes the same comparison on every ``pytest``; this is the command that fixes a red one.
Run it from the virtualenv ``scripts/dev-setup.sh`` builds.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT / "src", ROOT / "tests"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from conformance import pack  # noqa: E402


def main(argv: list[str]) -> int:
    if argv:
        print(__doc__)
        return 2
    built = pack.build()
    stale = [
        name
        for name, text in built.items()
        if not (pack.PACK_DIR / name).is_file()
        or (pack.PACK_DIR / name).read_text(encoding="utf-8") != text
    ]
    pack.PACK_DIR.mkdir(exist_ok=True)
    for name, text in built.items():
        (pack.PACK_DIR / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(built)} files to conformance/ ({len(stale)} changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
