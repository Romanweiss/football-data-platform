"""Stage 3B: materialize one known immutable Silver dataset."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.job import parse_args, run_job, context_from_args
from src.analytics.specs import CLI_DATASETS


def main(argv=None):
    args = parse_args(argv, generic=True)
    return run_job(**context_from_args(args), dataset=CLI_DATASETS[args.dataset], build_id=args.build_id, check_only=args.check_only)


if __name__ == "__main__":
    raise SystemExit(main())
