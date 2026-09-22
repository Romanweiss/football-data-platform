"""Stage 2D: publish one lineup domain from exact World Cup Bronze artifacts."""

import argparse
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.silver.job import COMPETITION_ID, SEASON_ID, parse_publish_args, run_publish_job

DATASETS = {"teams": "teams", "players": "players", "match-squads": "match_squads"}


def build_lineup_frame(spark, paths: list[str], match_ids: list[int], *, dataset: str):
    from src.silver.statsbomb.lineups import build_lineup_frame as build

    return build(spark, paths, match_ids, dataset=dataset, competition_id=COMPETITION_ID, season_id=SEASON_ID)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=tuple(DATASETS))
    args = parse_publish_args(parser, argv)
    dataset = DATASETS[args.dataset]
    return run_publish_job(
        dataset=dataset, transform_version=dataset + "_v1",
        build_frame=partial(build_lineup_frame, dataset=dataset),
        check_only=args.check_only, limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
