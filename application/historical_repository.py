"""Opt-in isolated serving reader. Never falls back to the production connection."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import re

import clickhouse_connect
from clickhouse_connect.driver.exceptions import Error as ClickHouseError
from application.errors import ApiError, ServingIntegrityError
from application.repository import FootballRepository
from src.openfootball_etl.contract import GOLD, KEYS, SEMANTIC, SOURCE_SHA, row_digest

MAX_ROWS = 4096
MAX_BUNDLE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class DatasetContract:
    batch_id: str
    source_sha256: str
    semantic_fingerprint: str
    # Public non-secret manifests, not counts embedded in HTTP controllers.
    datasets: tuple[tuple[str, int, str], ...]


PINNED = DatasetContract("ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc", SOURCE_SHA, SEMANTIC, (
    ("historical_fixtures", 189, "55d66c3f22b571c28d553469032f446b6f47394167f00daa56fbade0276e4b8a"),
    ("competition_participants", 36, "a77c6cf8918eb4916786e6f69c469c2a4217825e60149062ace74ec40d48cb5a"),
    ("stage_round_coverage", 14, "2a2f16af9b794aa7909693251312fb071ab977d81688f554efd5e1c23632f06f"),
    ("source_quality", 394, "842f201eb009f5e9da1d169be2d22a54a4d32214b8d77edfadb7b631fc98dd89"),
))


def not_ready():
    return ApiError("historical_not_ready", "Historical serving dataset is NOT_READY", 503)


class HistoricalRepository:
    def __init__(self, client, database, *, contract=PINNED):
        if not re.fullmatch(r"pet3_openfootball_api_[0-9a-f]{12,32}", database):
            raise not_ready()
        self.reader = FootballRepository(client)  # Existing readonly=1, typed/native JSON and driver error handling.
        self.database, self.contract = database, contract

    def load(self):
        """Four bounded views, authenticated against the published content contract.

        A tiny immutable season is loaded per request. No Parquet/SDK writes, no
        hidden cache or SQL assembled from user filters. Exact logical digests
        fence mixed/partial generations without claiming a global transaction.
        """
        try:
            output = {}
            for name, count, digest in self.contract.datasets:
                if name not in GOLD or not 0 < count <= MAX_ROWS:
                    raise not_ready()
                fields = GOLD[name]
                sql = ("SELECT " + ",".join(n for n, _, _ in fields) + " FROM {database:Identifier}." + name +
                       " WHERE batch_id = {batch_id:String} AND source_sha256 = {source_sha256:String} "
                       "ORDER BY " + ",".join(KEYS[name]) + " LIMIT {row_limit:UInt32}")
                rows = self.reader._query(sql, {"database": self.database, "batch_id": self.contract.batch_id,
                    "source_sha256": self.contract.source_sha256, "row_limit": MAX_ROWS + 1})
                for row in rows:
                    for field, kind, _ in fields:
                        if kind == "bool" and row[field] in (0, 1):
                            row[field] = bool(row[field])
                if len(rows) != count or row_digest(rows) != digest:
                    raise not_ready()
                output[name] = rows
            if set(output) != set(GOLD) or len(json.dumps(output, ensure_ascii=False).encode()) > MAX_BUNDLE_BYTES:
                raise not_ready()
            return output
        except (ApiError, ServingIntegrityError, ValueError, TypeError, KeyError):
            raise not_ready() from None


def create_historical_client():
    # This isolated prototype deliberately does not read CLICKHOUSE_* or .env.
    if os.environ.get("HISTORICAL_API_ENABLED") != "true":
        raise not_ready()
    host = os.environ.get("HISTORICAL_CLICKHOUSE_HOST", "")
    database = os.environ.get("HISTORICAL_CLICKHOUSE_DATABASE", "")
    if (not re.fullmatch(r"pet3-openfootball-ch-[0-9a-f]{12,32}", host)
            or not re.fullmatch(r"pet3_openfootball_api_[0-9a-f]{12,32}", database)):
        raise not_ready()
    password = os.environ.get("HISTORICAL_CLICKHOUSE_PASSWORD", "")
    if not password:
        raise not_ready()
    return clickhouse_connect.get_client(host=host, port=8123, database=database,
        username="historical_reader", password=password, connect_timeout=3, send_receive_timeout=15,
        query_retries=0, show_clickhouse_errors=False), database


@contextmanager
def open_historical_repository():
    try:
        client, database = create_historical_client()
    except (ClickHouseError, ValueError, OSError, TimeoutError):
        raise not_ready() from None
    try:
        yield HistoricalRepository(client, database)
    finally:
        client.close()
