"""Immutable public handoff pins. No clients, credentials, or storage access."""
from dataclasses import dataclass
import re

from src.openfootball_etl.contract import GOLD, SEMANTIC, SOURCE_SHA, check, row_digest


@dataclass(frozen=True)
class DatasetContract:
    batch_id: str
    source_sha256: str
    semantic_fingerprint: str
    datasets: tuple[tuple[str, int, str], ...]


PINNED = DatasetContract("ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc", SOURCE_SHA, SEMANTIC, (
    ("historical_fixtures", 189, "55d66c3f22b571c28d553469032f446b6f47394167f00daa56fbade0276e4b8a"),
    ("competition_participants", 36, "a77c6cf8918eb4916786e6f69c469c2a4217825e60149062ace74ec40d48cb5a"),
    ("stage_round_coverage", 14, "2a2f16af9b794aa7909693251312fb071ab977d81688f554efd5e1c23632f06f"),
    ("source_quality", 394, "842f201eb009f5e9da1d169be2d22a54a4d32214b8d77edfadb7b631fc98dd89"),
))
HOST = "football-clickhouse"
DATABASE = "football"
PREFIX = "pet3d_ucl_2024_25_"
RECORDS = PREFIX + "records"
MODE = "production-pinned"
DATASET = "openfootball:uefa-champions-league:2024"
AUTHORIZATION = DATASET + ":" + PINNED.batch_id


def valid_uuid(value):
    return isinstance(value, str) and bool(re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value)) and value != "00000000-0000-0000-0000-000000000000"


def validate_bundle(data):
    check(set(data) == set(GOLD), "PINNED_DATASETS")
    for name, count, digest in PINNED.datasets:
        rows = data[name]
        check(isinstance(rows, list) and len(rows) == count, "PINNED_COUNTS")
        check(all(set(row) == {n for n, _, _ in GOLD[name]} and
                  row["batch_id"] == PINNED.batch_id and row["source_sha256"] == PINNED.source_sha256
                  for row in rows), "PINNED_PROVENANCE")
        check(row_digest(rows) == digest, "PINNED_CONTENT")
    return {name: len(rows) for name, rows in data.items()}
