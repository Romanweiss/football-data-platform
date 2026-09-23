"""Official HTTP client; configuration comes only from environment variables."""

import os
import re

import clickhouse_connect


def create_clickhouse_client():
    names = (
        "CLICKHOUSE_HOST", "CLICKHOUSE_HTTP_PORT", "CLICKHOUSE_DB",
        "CLICKHOUSE_USER", "CLICKHOUSE_PASSWORD",
    )
    settings = {name: os.environ.get(name, "") for name in names}
    missing = [name for name, value in settings.items() if not value.strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    if not re.fullmatch(r"[0-9]{1,5}", settings["CLICKHOUSE_HTTP_PORT"]):
        raise ValueError("CLICKHOUSE_HTTP_PORT must be an integer between 1 and 65535.")
    port = int(settings["CLICKHOUSE_HTTP_PORT"])
    if not 1 <= port <= 65535:
        raise ValueError("CLICKHOUSE_HTTP_PORT must be an integer between 1 and 65535.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", settings["CLICKHOUSE_HOST"]):
        raise ValueError("CLICKHOUSE_HOST must be a hostname, not a URL.")
    return clickhouse_connect.get_client(
        host=settings["CLICKHOUSE_HOST"], port=port,
        database=settings["CLICKHOUSE_DB"], username=settings["CLICKHOUSE_USER"],
        password=settings["CLICKHOUSE_PASSWORD"],
        connect_timeout=10, send_receive_timeout=300,
        query_retries=0, show_clickhouse_errors=False,
    )
