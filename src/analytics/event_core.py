"""Stage 3A compatibility exports; implementation is shared with every dataset."""

from src.analytics.specs import EVENT_CORE
from src.analytics.loader import (
    INSERT_SETTINGS, insert_sql, load_dataset as load_event_core, load_record, validate_load_record,
)
from src.analytics.validation import (
    ClickHouseIntegrityError, READ_SETTINGS, S3_SOURCE, metric_expressions,
    source_metrics, target_metrics, validate_metrics, validate_table_schema, verify_named_collection,
)

DATABASE = EVENT_CORE.clickhouse_database
TABLE = EVENT_CORE.clickhouse_table
TARGET = EVENT_CORE.target
EVENT_COLUMNS = EVENT_CORE.columns
TARGET_COLUMNS = EVENT_CORE.target_columns
METRICS = metric_expressions(EVENT_CORE)
