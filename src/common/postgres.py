"""PostgreSQL connections and registration of confirmed Bronze artifacts."""

import os

import psycopg


class IngestionObjectNotFoundError(LookupError):
    """No artifact has been registered for the requested source and dataset."""


def create_postgres_connection() -> psycopg.Connection:
    """Connect using environment variables without logging credentials."""
    names = (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    settings = {name: os.environ.get(name, "") for name in names}
    missing = [name for name, value in settings.items() if not value.strip()]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    try:
        port = int(settings["POSTGRES_PORT"])
    except ValueError:
        raise ValueError("POSTGRES_PORT must be an integer between 1 and 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("POSTGRES_PORT must be an integer between 1 and 65535")

    return psycopg.connect(
        host=settings["POSTGRES_HOST"],
        port=port,
        dbname=settings["POSTGRES_DB"],
        user=settings["POSTGRES_USER"],
        password=settings["POSTGRES_PASSWORD"],
        connect_timeout=10,
    )


def register_ingestion_object(
    connection: psycopg.Connection,
    *,
    source: str,
    dataset: str,
    source_url: str,
    s3_bucket: str,
    object_key: str,
    sha256: str,
    size_bytes: int,
) -> bool:
    """Register a confirmed S3 object; return True only for a new catalog row.

    The caller must confirm S3 integrity first and supply an idle connection.
    Each artifact is committed independently before returning.
    """
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO metadata.ingestion_objects
                    (source, dataset, source_url, s3_bucket, object_key, sha256, size_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (s3_bucket, object_key) DO NOTHING
                RETURNING id
                """,
                (source, dataset, source_url, s3_bucket, object_key, sha256, size_bytes),
            )
            registered = cursor.fetchone() is not None
    return registered


def find_latest_ingestion_object(
    connection: psycopg.Connection, *, source: str, dataset: str
) -> dict:
    """Return the latest registered artifact, ending SELECT's transaction first.

    The caller supplies an idle connection so later artifact registrations can
    commit independently, without an enclosing read transaction.
    """
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT s3_bucket, object_key, sha256, size_bytes, first_seen_at
                FROM metadata.ingestion_objects
                WHERE source = %s AND dataset = %s
                ORDER BY first_seen_at DESC, id DESC
                LIMIT 1
                """,
                (source, dataset),
            )
            row = cursor.fetchone()
    if row is None:
        raise IngestionObjectNotFoundError(
            f"No registered Bronze artifact for source={source}, dataset={dataset}. "
            "Ingest the parent dataset first."
        )
    columns = ("s3_bucket", "object_key", "sha256", "size_bytes", "first_seen_at")
    return dict(zip(columns, row, strict=True))
