"""Read-only Stage 4E checks, including 014 xG series and 015 shot labels."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.match_visuals import check_visuals, check_race_series, view_selects
from src.common.clickhouse import create_clickhouse_client
from scripts.check_clickhouse_match_analysis import main as check_stage4d


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--candidate", action="store_true", help="SELECT-only preview of the 013/014/015 contracts")
    modes.add_argument("--candidate-series", action="store_true", help="Preview only 014; other installed views must include the 015 shot-label contract")
    modes.add_argument("--candidate-shot-map", action="store_true", help="Validate installed 013/014 and preview only 015 without applying it")
    args = parser.parse_args(argv)
    stage = "Stage 4C/4D prerequisites"
    try:
        # Stage 4D in turn runs the full Stage 4C bi-v2 validator.
        if check_stage4d([]) != 0:
            return 1
        stage = "candidate SELECT" if args.candidate else "candidate shot map" if args.candidate_shot_map else "installed visual views"
        with closing(create_clickhouse_client()) as client:
            result = check_visuals(client, candidate=args.candidate, candidate_shot_map=args.candidate_shot_map)
            stage = "xG race series"
            relation = "(" + view_selects()["xg_race"] + ")" if args.candidate else "football.bi_match_xg_race"
            result.update(check_race_series(client, candidate=args.candidate or args.candidate_series, race_relation=relation))
        mode = "candidate" if args.candidate else "candidate-series" if args.candidate_series else "candidate-shot-map" if args.candidate_shot_map else "installed"
        print(f"MATCH VISUALS CHECK PASSED: mode={mode} {result}")
        return 0
    except Exception as error:
        print(f"Match visuals check failed: stage={stage}; exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
