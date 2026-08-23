"""Make the package and the conformance helpers importable without an install.

The suite runs against ``src/`` directly so a plain ``pytest`` in a fresh checkout
works, and against an installed wheel in CI, where the same imports resolve to the
installed package instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT / "src", ROOT / "tests"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
