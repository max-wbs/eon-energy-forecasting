"""Stage 1: raw -> interim/01_ingested.

Loads the four raw sources, types them, removes households without a target
value and merges the master data.

Usage:
    poetry run python scripts/01_load.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import loading  # noqa: E402
from utils.reporting import Reporter  # noqa: E402


def main() -> int:
    # The context manager writes the report even when a check aborts the run
    # (report-then-raise).
    try:
        with Reporter(stage=1, title="Load & Type") as rep:
            loading.run(rep)
    except Exception as exc:
        print(f"\nAborted: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
