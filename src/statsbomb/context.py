"""Validated StatsBomb source context; no catalog of manually named competitions."""
import argparse
import json
import re

from src.analytics.context import add_context_arguments, context_from_args
class SourceContextError(ValueError):
    """Invalid authoritative source context, with safe fixed messages."""

SOURCE_BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
CATALOG_URL = SOURCE_BASE_URL + "/competitions.json"


def sha256_argument(value):
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("Expected 64 lowercase hexadecimal characters")
    return value


def positive_id(value):
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return int(value)


def add_bronze_arguments(parser, *, children=False):
    add_context_arguments(parser)
    parser.add_argument("--parent-sha256", required=True, type=sha256_argument,
                        help="Exact registered matches Bronze SHA-256")
    if children:
        parser.add_argument("--bronze-max-id", required=True, type=positive_id,
                            help="Freeze latest-per-source selection at this ingestion catalog ID")


def matches_url(*, competition_id, season_id):
    return f"{SOURCE_BASE_URL}/matches/{competition_id}/{season_id}.json"


def matches_prefix(*, competition_id, season_id):
    return f"football/bronze/statsbomb/matches/competition_id={competition_id}/season_id={season_id}"


def child_prefix(kind, match_id, *, competition_id, season_id):
    if kind not in ("events", "lineups"):
        raise ValueError("Unsupported child dataset")
    return (f"football/bronze/statsbomb/{kind}/competition_id={competition_id}/"
            f"season_id={season_id}/match_id={match_id}")


def catalog_context(raw, *, competition_id, season_id):
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError()
        selected = [row for row in rows if row.get("competition_id") == competition_id
                    and row.get("season_id") == season_id]
        if len(selected) != 1:
            raise ValueError()
        return selected[0]
    except (TypeError, ValueError):
        raise SourceContextError("Competition/season is absent or ambiguous in the authoritative source catalog.") from None


def matches_context(raw, *, competition_id, season_id):
    from src.statsbomb.matches import extract_match_ids
    ids = extract_match_ids(raw)
    rows = json.loads(raw)
    if not ids or any(row.get("competition", {}).get("competition_id") != competition_id
                      or row.get("season", {}).get("season_id") != season_id for row in rows):
        raise SourceContextError("Matches parent is empty or belongs to another competition/season.")
    return ids


def validate_parent_url(parent, *, competition_id, season_id):
    url = matches_url(competition_id=competition_id, season_id=season_id)
    if parent.get("source_url") not in (url, url.replace("/hudl/", "/statsbomb/")):
        raise SourceContextError("Matches parent source URL belongs to another context.")
