"""Immutable Gold stats/results build/check-only CLI; no ClickHouse dependencies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.gold.job import main


if __name__ == "__main__":
    raise SystemExit(main())
