"""Ensure the standalone `scripts/` tree (policy_eval, mcp_tools_server, etc.)
is importable regardless of which test files pytest happens to collect first.

Several tests under tests/ patch or import `policy_eval.*` (a package that
lives under scripts/, not on the normal Python path). Individual test modules
insert scripts/ onto sys.path themselves at import time, so running the full
suite "works" only by accident of collection order -- run a single such file
alone and the import fails. Doing it once here, for every test run, removes
that footgun.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
