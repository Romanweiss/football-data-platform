class ApiError(Exception):
    """Only explicitly constructed public messages can cross HTTP boundary."""
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class ServingIntegrityError(Exception):
    """Serving contract violation: fail closed, do not repair analytical data."""


def unavailable():
    return ApiError("clickhouse_unavailable", "ClickHouse is unavailable", 503)
