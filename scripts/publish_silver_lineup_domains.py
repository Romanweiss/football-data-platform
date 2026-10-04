"""Publish one lineup domain from exact context-bound Bronze artifacts."""

import argparse
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.statsbomb.context import context_from_args
from src.silver.job import parse_publish_args, run_publish_job

DATASETS = {"teams": "teams", "players": "players", "match-squads": "match_squads"}


def build_lineup_frame(spark, paths: list[str], match_ids: list[int], *, dataset: str, competition_id, season_id):
    from src.silver.statsbomb.lineups import build_lineup_frame as build

    return build(spark, paths, match_ids, dataset=dataset, competition_id=competition_id, season_id=season_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=tuple(DATASETS))
    args = parse_publish_args(parser, argv)
    dataset = DATASETS[args.dataset]
    return run_publish_job(
        dataset=dataset, transform_version=dataset + "_v1",
        build_frame=partial(build_lineup_frame, dataset=dataset),
        check_only=args.check_only, limit=args.limit, **context_from_args(args),
        parent_sha256=args.parent_sha256, bronze_max_id=args.bronze_max_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
