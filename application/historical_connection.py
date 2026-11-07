"""Explicit pinned historical connection; never an implicit production fallback."""
import os
import re

import clickhouse_connect
from src.openfootball_etl.serving_contract import (
    AUTHORIZATION, DATABASE, DATASET, HOST, PINNED, valid_uuid,
)


def persistent_client():
    from application.historical_repository import not_ready
    expected_uuid = os.environ.get("HISTORICAL_EXPECTED_SERVER_UUID", "")
    if (os.environ.get("HISTORICAL_PRODUCTION_AUTHORIZATION") != AUTHORIZATION or
            os.environ.get("HISTORICAL_DATASET_ID") != DATASET or
            os.environ.get("HISTORICAL_PINNED_BATCH") != PINNED.batch_id or
            os.environ.get("HISTORICAL_CLICKHOUSE_HOST") != HOST or
            os.environ.get("HISTORICAL_CLICKHOUSE_DATABASE") != DATABASE or
            not valid_uuid(expected_uuid)):
        raise not_ready()
    user = os.environ.get("HISTORICAL_CLICKHOUSE_USER", "")
    password = os.environ.get("HISTORICAL_CLICKHOUSE_PASSWORD", "")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", user) or user in ("root", "default") or not password:
        raise not_ready()
    client = None
    try:
        client = clickhouse_connect.get_client(host=HOST, port=8123, database=DATABASE,
            username=user, password=password, connect_timeout=3, send_receive_timeout=15,
            query_retries=0, show_clickhouse_errors=False)
        from application.repository import FootballRepository
        reader = FootballRepository(client)
        identity = reader._query("SELECT toString(serverUUID()) AS server_uuid, currentDatabase() AS database")
        engine = reader._query("SELECT engine FROM system.databases WHERE name = {database:String}", {"database": DATABASE})
        if identity != [{"server_uuid": expected_uuid, "database": DATABASE}] or engine != [{"engine": "Atomic"}]:
            raise not_ready()
        return client, DATABASE
    except Exception:
        if client is not None:
            client.close()
        raise not_ready() from None
