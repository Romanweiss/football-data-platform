"""Offline Stage 3B fixtures. No real service connections or delete API."""

from types import SimpleNamespace

from silver_fakes import FakeS3, artifact, seed_output
from test_clickhouse_silver_input import seed_manifest
from src.analytics.specs import SPECS
from src.analytics.validation import expected_metrics
from src.silver.build_identity import build_specification, calculate_build_id, input_fingerprint, silver_prefix
from src.silver.manifest import inspect_silver_output, make_manifest


def dataset_fixture(spec):
    inputs = [artifact(7), artifact(8)]
    if spec.artifact_kind == "matches":
        inputs = [{**artifact(7), "source": "statsbomb", "dataset": "world_cup_2022_matches",
                   "source_url": "https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json"}]
    if spec.artifact_kind == "lineups":
        for item in inputs:
            item["source_url"] = item["source_url"].replace("/events/", "/lineups/")
            item["object_key"] = item["object_key"].replace("/events/", "/lineups/").replace("events.json", "lineups.json")
    specification = build_specification(
        dataset=spec.dataset, competition_id=43, season_id=106, transform_version=spec.transform_version,
        input_fingerprint=input_fingerprint(inputs, artifact_kind=spec.artifact_kind), schema_sha256="b" * 64,
    )
    build_id = calculate_build_id(specification)
    prefix = silver_prefix(specification, build_id)
    s3 = FakeS3()
    seed_output(s3, "test-bucket", prefix)
    files = inspect_silver_output(s3, bucket="test-bucket", prefix=prefix)
    manifest = make_manifest(specification, inputs,
                             {"row_count": 6, "match_count" if spec.has_match_count else "input_match_count": 6 if spec.dataset == "matches" else 2}, files)
    build = {**specification, "build_id": build_id, "s3_bucket": "test-bucket", "s3_prefix": prefix,
             "row_count": 6, "file_count": len(files)}
    seed_manifest(s3, build, manifest)
    return s3, build, manifest


class DatasetClient:
    def __init__(self, spec):
        self.spec = spec
        self.s3, self.build, self.manifest = dataset_fixture(spec)
        self.source = expected_metrics(self.manifest, spec)
        self.target = (0,) * len(self.source)
        self.other_rows = 0
        self.bad_schema = False
        self.bad_teams = 0
        self.calls = []
        self.inserts = []
        self.fail_after_insert = False
        self.partial_insert = False
        self.server_version = "25.8.23.13"

    def query(self, sql, **options):
        self.calls.append((sql, options))
        if sql.startswith("DESCRIBE"):
            rows = [(n, k, "DEFAULT" if n == "loaded_at" else "", "now64(3)" if n == "loaded_at" else "")
                    for n, k in self.spec.target_columns]
            if self.bad_schema:
                rows[0] = ("wrong", "String", "", "")
        elif "system.tables" in sql:
            rows = [("MergeTree", f"PARTITION BY ({', '.join(self.spec.context_columns)}) "
                     f"ORDER BY ({', '.join(self.spec.order_by)}) SETTINGS non_replicated_deduplication_window = 1000")]
        elif "system.named_collections" in sql:
            rows = [(1,)]
        elif "HAVING uniqExact(team_id)" in sql:
            rows = [(self.bad_teams,)]
        elif "uniqExact(silver_build_id)" in sql:
            rows = [(self.target[0] + self.other_rows, int(bool(self.target[0])) + int(bool(self.other_rows)),
                     self.other_rows, self.build["build_id"])]
        elif "FROM s3(" in sql:
            rows = [self.source]
        else:
            rows = [self.target]
        return SimpleNamespace(result_rows=rows)

    def command(self, sql, **options):
        self.inserts.append((sql, options))
        self.target = self.source
        if self.partial_insert:
            self.target = (1, *self.source[1:])
        if self.fail_after_insert:
            raise TimeoutError("FAKE secret must not be logged")

    def close(self):
        pass
