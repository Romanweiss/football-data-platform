"""Isolated by default; explicit pinned persistent handoff, never a fallback."""
from contextlib import contextmanager
import json
import os
import re

import clickhouse_connect
from clickhouse_connect.driver.exceptions import Error as ClickHouseError
from application.errors import ApiError, ServingIntegrityError
from application.repository import FootballRepository
from src.openfootball_etl.contract import GOLD, KEYS, row_digest
from src.openfootball_etl.serving_contract import DATABASE, MODE, PREFIX, RECORDS, PINNED
from src.openfootball_etl.serving_contract import DatasetContract as DatasetContract

MAX_ROWS = 4096
MAX_BUNDLE_BYTES = 2 * 1024 * 1024


def not_ready():
    return ApiError("historical_not_ready", "Historical serving dataset is NOT_READY", 503)


class HistoricalRepository:
    def __init__(self, client, database, *, contract=PINNED, mode="isolated"):
        if mode not in ("isolated", MODE):
            raise not_ready()
        if mode == MODE and (database != DATABASE or contract != PINNED):
            raise not_ready()
        if mode == "isolated" and not re.fullmatch(r"pet3_openfootball_api_[0-9a-f]{12,32}", database):
            raise not_ready()
        self.reader = FootballRepository(client)  # Existing readonly=1, typed/native JSON and driver error handling.
        self.database, self.contract = database, contract
        self.mode = mode

    def generation(self):
        rows = self.reader._query("SELECT toString(uuid) AS uuid FROM system.tables "
            "WHERE database = {database:String} AND name = {name:String}",
            {"database": DATABASE, "name": RECORDS})
        if len(rows) != 1:
            raise not_ready()
        return rows

    def load(self):
        """Four bounded views, authenticated against the published content contract.

        A tiny immutable season is loaded per request. No Parquet/SDK writes, no
        hidden cache or SQL assembled from user filters. Exact logical digests
        fence mixed/partial generations without claiming a global transaction.
        """
        try:
            generation = self.generation() if self.mode == MODE else None
            output = {}
            for name, count, digest in self.contract.datasets:
                if name not in GOLD or not 0 < count <= MAX_ROWS:
                    raise not_ready()
                fields = GOLD[name]
                table = PREFIX + name if self.mode == MODE else name
                sql = ("SELECT " + ",".join(n for n, _, _ in fields) + " FROM {database:Identifier}." + table +
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
            if generation is not None and self.generation() != generation:
                raise not_ready()
            return output
        except (ApiError, ServingIntegrityError, ValueError, TypeError, KeyError):
            raise not_ready() from None


def create_historical_client():
    # This isolated prototype deliberately does not read CLICKHOUSE_* or .env.
    if os.environ.get("HISTORICAL_API_ENABLED") != "true":
        raise not_ready()
    mode = os.environ.get("HISTORICAL_SERVING_MODE", "isolated")
    if mode == MODE:
        from application.historical_connection import persistent_client
        return persistent_client()
    if mode != "isolated":
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
        yield HistoricalRepository(client, database, mode=os.environ.get("HISTORICAL_SERVING_MODE", "isolated"))
    finally:
        client.close()
