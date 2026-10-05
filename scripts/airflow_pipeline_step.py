"""Private stdio JSON bridge; invokes existing CLIs, never emits their raw logs."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.orchestration.runtime import execute
from src.dq.orchestration import DQGateError


if __name__ == "__main__":
    try:
        result = execute(json.load(sys.stdin))
        print(json.dumps(result))
    except DQGateError as exc:
        print(json.dumps({'exception':'DQGateError', 'message':'Persistent DQ gate failed', **exc.summary}))
        sys.exit(1)
    except Exception as exc:
        # RuntimeError from our allowlisted run_cli has a safe fixed-format message.
        message = str(exc) if type(exc) is RuntimeError and str(exc).startswith("CLI failed: script=") else "Project adapter failed"
        print(json.dumps({"exception": type(exc).__name__, "message": message}))
        sys.exit(1)
