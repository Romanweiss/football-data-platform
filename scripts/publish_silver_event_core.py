"""Stage 2B: direct S3A event reads and immutable full-parent Silver publication."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.silver.build_identity import TRANSFORM_VERSION
from src.statsbomb.context import context_from_args
from src.silver.job import parse_publish_args, run_publish_job
from src.statsbomb.events import EventArtifactError


def build_event_frame(spark, paths: list[str], *, competition_id, season_id):
    from src.silver.statsbomb.events import (
        EventCoreQualityError, read_s3a_events, transform_event_core, validate_event_core,
    )

    frame = transform_event_core(
        read_s3a_events(spark, paths), competition_id=competition_id, season_id=season_id,
    ).cache()
    try:
        counts = validate_event_core(frame)
        if counts["match_count"] != len(paths):
            raise EventArtifactError(
                f"DQ: selected_artifacts={len(paths)}, matches_with_events={counts['match_count']}."
            )
        return frame, counts
    except EventCoreQualityError as error:
        frame.unpersist()
        raise EventArtifactError(str(error)) from None
    except Exception:
        frame.unpersist()
        raise


def main(argv: list[str] | None = None) -> int:
    args = parse_publish_args(argparse.ArgumentParser(description=__doc__), argv)
    return run_publish_job(
        dataset="event_core", transform_version=TRANSFORM_VERSION,
        build_frame=lambda spark, paths, match_ids, **context: build_event_frame(spark, paths, **context),
        check_only=args.check_only, limit=args.limit, **context_from_args(args),
        parent_sha256=args.parent_sha256, bronze_max_id=args.bronze_max_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
