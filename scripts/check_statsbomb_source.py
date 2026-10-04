"""Public-source preflight only: no S3, database clients or registration."""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.checksum import sha256_bytes
from src.common.http import download_bytes
from src.statsbomb.context import (add_context_arguments, context_from_args, CATALOG_URL, SOURCE_BASE_URL,
                                   catalog_context, matches_context, matches_url)


def head(url):
    with urlopen(Request(url, method="HEAD"), timeout=30) as response:
        if response.status != 200:
            raise ValueError("Source file is unavailable")
    return url


def inspect_source(context):
    catalog_raw = download_bytes(CATALOG_URL)
    metadata = catalog_context(catalog_raw, **context)
    raw = download_bytes(matches_url(**context))
    ids = matches_context(raw, **context)
    urls = [f"{SOURCE_BASE_URL}/{kind}/{match_id}.json" for match_id in ids for kind in ("events", "lineups")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        verified = list(pool.map(head, urls))
    rows = json.loads(raw)
    return {**context, "competition_name": metadata.get("competition_name"), "season_name": metadata.get("season_name"),
            "matches_url": matches_url(**context), "catalog_sha256": sha256_bytes(catalog_raw),
            "matches_sha256": sha256_bytes(raw), "match_count": len(ids),
            "team_count": len({row[side + "_team"][side + "_team_id"] for row in rows for side in ("home", "away")}),
            "events_available": len(verified) // 2, "lineups_available": len(verified) // 2,
            "match_ids": ids, "source_urls": verified}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_context_arguments(parser)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_source(context_from_args(args)), indent=2))
        return 0
    except Exception as error:
        print(f"Public source preflight failed: exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
