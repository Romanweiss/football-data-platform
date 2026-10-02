"""Preserve numeric precision/types and nullable fields; UUIDs are text identities."""
import math
from datetime import date, datetime, time
from uuid import UUID


def json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite number in serving data")
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    raise TypeError("Unsupported serving JSON type")


BOOLEAN_FIELDS = frozenset(("is_home", "is_goal", "is_extra_time", "went_to_extra_time", "went_to_penalties"))


def serialize_row(row):
    result = dict(row)
    for field in BOOLEAN_FIELDS & result.keys():
        if result[field] is not None:
            if result[field] not in (0, 1):
                raise ValueError("Invalid serving boolean")
            result[field] = bool(result[field])
    return json_value(result)
