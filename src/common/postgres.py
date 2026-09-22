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


def find_latest_ingestion_objects(
    connection: psycopg.Connection, *, source: str, dataset: str
) -> list[dict]:
    """Return one latest version per logical source_url, in source_url order.

    first_seen_at ties are resolved by id. Finish the read transaction before
    the caller starts downloading Bronze; an empty dataset returns [].
    """
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (source_url)
                    id, source_url, s3_bucket, object_key, sha256, size_bytes, first_seen_at
                FROM metadata.ingestion_objects
                WHERE source = %s AND dataset = %s
                ORDER BY source_url ASC, first_seen_at DESC, id DESC
                """,
                (source, dataset),
            )
            rows = cursor.fetchall()
    columns = (
        "id", "source_url", "s3_bucket", "object_key", "sha256", "size_bytes", "first_seen_at",
    )
    return [dict(zip(columns, row, strict=True)) for row in rows]


SILVER_BUILD_COLUMNS = (
    "id", "source", "dataset", "competition_id", "season_id", "transform_version",
    "input_fingerprint", "schema_sha256", "build_id", "s3_bucket", "s3_prefix",
    "row_count", "file_count", "created_at",
)


def find_silver_build(
    connection: psycopg.Connection, *, dataset: str, competition_id: int,
    season_id: int, build_id: str,
) -> dict | None:
    """Find a published build; finish the SELECT transaction before remote IO."""
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, source, dataset, competition_id, season_id, transform_version,
                    input_fingerprint, schema_sha256, build_id, s3_bucket, s3_prefix,
                    row_count, file_count, created_at
                FROM metadata.silver_builds
                WHERE dataset = %s AND competition_id = %s AND season_id = %s AND build_id = %s
                """,
                (dataset, competition_id, season_id, build_id),
            )
            row = cursor.fetchone()
    return None if row is None else dict(zip(SILVER_BUILD_COLUMNS, row, strict=True))


def register_silver_build(
    connection: psycopg.Connection, *, source: str, dataset: str,
    competition_id: int, season_id: int, transform_version: str,
    input_fingerprint: str, schema_sha256: str, build_id: str,
    s3_bucket: str, s3_prefix: str, row_count: int, file_count: int,
) -> bool:
    """Register only verified output; caller must validate any conflicting row.

    No UPDATE: repeat registration never changes a published build's metadata.
    """
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO metadata.silver_builds
                    (source, dataset, competition_id, season_id, transform_version,
                     input_fingerprint, schema_sha256, build_id, s3_bucket, s3_prefix,
                     row_count, file_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dataset, competition_id, season_id, build_id) DO NOTHING
                RETURNING id
                """,
                (source, dataset, competition_id, season_id, transform_version,
                 input_fingerprint, schema_sha256, build_id, s3_bucket, s3_prefix,
                 row_count, file_count),
            )
            registered = cursor.fetchone() is not None
    return registered
