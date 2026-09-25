"""Offline registered Gold artifacts and aggregate-only ClickHouse fake."""

from types import SimpleNamespace

from gold_fakes import seed_output, silver_inputs, specification
from test_clickhouse_silver_input import seed_manifest
from src.analytics.validation import expected_metrics
from src.gold.build_identity import OUTPUT_PARTITIONS, calculate_build_id, gold_prefix
from src.gold.manifest import inspect_output, make_manifest


def fixture(spec):
    client, builds, _ = silver_inputs()
    specification_ = specification(builds, dataset=spec.dataset)
    build_id = calculate_build_id(specification_)
    prefix = gold_prefix(specification_, build_id)
    seed_output(client, "test-bucket", prefix, OUTPUT_PARTITIONS[spec.dataset])
    files = inspect_output(client, bucket="test-bucket", prefix=prefix)
    manifest = make_manifest(specification_, builds, {"row_count": 4, "match_count": 2}, files)
    build = {**specification_, "build_id": build_id, "s3_bucket": "test-bucket", "s3_prefix": prefix,
             "row_count": 4, "file_count": len(files)}
    seed_manifest(client, build, manifest)
    client.calls.clear()
    return client, build, manifest


class GoldClient:
    def __init__(self, spec):
        self.spec = spec
        self.s3, self.build, self.manifest = fixture(spec)
        self.source = expected_metrics(self.manifest, spec)
        self.target = (0,) * len(self.source)
        self.other_rows = 0
        self.bad_schema = False
        self.bad_teams = False
        self.partial_insert = False
        self.fail_after_insert = False
        self.inserts = []
        self.queries = []

    def query(self, sql, **options):
        self.queries.append((sql, options))
        if sql.startswith("DESCRIBE"):
            rows = [(name, kind, "", "") for name, kind in self.spec.target_columns]
            rows[-1] = (*rows[-1][:2], "DEFAULT", "now64(3)")
            if self.bad_schema:
                rows[0] = ("wrong", "Float32", "", "")
        elif "FROM system.tables" in sql:
            rows = [("MergeTree", f"PARTITION BY ({', '.join(self.spec.context_columns)}) "
                     f"ORDER BY ({', '.join(self.spec.order_by)}) SETTINGS non_replicated_deduplication_window = 1000")]
        elif "FROM system.named_collections" in sql:
            rows = [(1,)]
        elif "HAVING uniqExact(team_id)" in sql:
            rows = [(int(self.bad_teams),)]
        elif "uniqExact(gold_build_id)" in sql:
            rows = [(self.target[0] + self.other_rows, int(self.target[0] > 0) + int(self.other_rows > 0), self.other_rows)]
        elif "FROM s3(" in sql:
            rows = [self.source]
        else:
            rows = [self.target]
        return SimpleNamespace(result_rows=rows)

    def command(self, sql, **options):
        self.inserts.append((sql, options))
        self.target = (1, *self.source[1:]) if self.partial_insert else self.source
        if self.fail_after_insert:
            raise TimeoutError("synthetic-private-secret")

    def close(self):
        pass
