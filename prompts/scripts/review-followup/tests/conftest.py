"""Make the review-followup script modules importable for their unit tests.

The scripts are standalone files (no package), so the tests put their parent
directory on ``sys.path`` and import them by module name.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
