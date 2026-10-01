"""Stage 4B read-only ClickHouse diagnostics; no Selectel access."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.shot_audit import main

if __name__ == "__main__":
    raise SystemExit(main())
