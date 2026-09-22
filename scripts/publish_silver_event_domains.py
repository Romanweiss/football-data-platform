"""Stage 2C: publish one immutable pass/shot dataset directly from Bronze S3A inputs."""

import argparse
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.silver.job import COMPETITION_ID, SEASON_ID, parse_publish_args, run_publish_job

DATASETS = {
    "passes": ("pass_events", "pass_events_v1"),
    "shots": ("shot_events", "shot_events_v1"),
}


def build_domain_frame(spark, paths: list[str], match_ids: list[int], *, dataset: str):
    # Keep the CLI/imports usable by offline tests without installing PySpark in python-tools.
    from src.silver.statsbomb.event_domains import build_domain_frame as build

    return build(spark, paths, match_ids, dataset=dataset, competition_id=COMPETITION_ID, season_id=SEASON_ID)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=tuple(DATASETS))
    args = parse_publish_args(parser, argv)
    dataset, transform_version = DATASETS[args.dataset]
    return run_publish_job(
        dataset=dataset, transform_version=transform_version,
        build_frame=partial(build_domain_frame, dataset=args.dataset),
        check_only=args.check_only, limit=args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
