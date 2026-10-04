"""Offline Stage 3E lineage, publisher recovery, serving schema and model checks."""

from context_fixtures import CONTEXT_ARGS
from context_fixtures import in_context

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from matches_fakes import parent
from silver_fakes import FakeS3
from src.silver import build_identity as identity, manifest, publish
from src.analytics import matches_model, loader
from src.analytics.specs import MATCHES
from src.analytics.validation import ClickHouseIntegrityError
from scripts import publish_silver_matches as cli


class MatchBuildTests(unittest.TestCase):
    def specification(self, inputs):
        return identity.build_specification(dataset="matches", transform_version="matches_v1", competition_id=43, season_id=106,
            input_fingerprint=identity.input_fingerprint(inputs, artifact_kind="matches"), schema_sha256="b" * 64)

    def test_lineage_whitelist_deterministic_and_every_field_sensitive(self):
        item = parent()
        baseline = identity.input_fingerprint([item], artifact_kind="matches")
        self.assertEqual(baseline, identity.input_fingerprint([{**dict(reversed(list(item.items()))), "timestamp": "now", "credentials": "secret"}], artifact_kind="matches"))
        self.assertNotIn("secret", identity.canonical_json(identity.canonical_inputs([{**item, "credentials": "secret"}], artifact_kind="matches")).decode())
        for key, value in (("s3_bucket", "other"), ("object_key", "other/key"), ("sha256", "f" * 64),
                           ("source_url", item["source_url"].replace("hudl", "statsbomb"))):
            self.assertNotEqual(baseline, identity.input_fingerprint([{**item, key: value}], artifact_kind="matches"))
        for changes in ({"source": "wrong"}, {"dataset": "wrong"}, {"source_url": "https://untrusted.invalid/matches/43/106.json"}, {"sha256": "wrong"}):
            with self.assertRaises(ValueError):
                identity.input_fingerprint([{**item, **changes}], artifact_kind="matches")
        for inputs in ([], [item, item]):
            with self.assertRaises(ValueError):
                identity.input_fingerprint(inputs, artifact_kind="matches")
        spec = self.specification([item])
        self.assertEqual(identity.calculate_build_id(spec), identity.calculate_build_id({**spec, "time": "now"}))
        self.assertIn("/matches/competition_id=43/season_id=106/build_id=", identity.silver_prefix(spec, identity.calculate_build_id(spec)))

    def test_publish_one_part_first_repeat_recovery_and_partial_fail(self):
        for fail_registration in (False, True):
            s3, store = FakeS3(), {}
            inputs = [parent()]
            spec = self.specification(inputs)
            prefix = identity.silver_prefix(spec, identity.calculate_build_id(spec))
            def write(frame, uri, *, partitions):
                self.assertEqual(partitions, 1)
                s3.seed("test-bucket", prefix + "part-00000.snappy.parquet")
                s3.seed("test-bucket", prefix + "_SUCCESS", b"")
            def register(connection, **record):
                store.update(record)
                return True
            with patch.object(publish, "find_silver_build", side_effect=lambda *a, **k: store or None), \
                    patch.object(publish, "register_silver_build", side_effect=register) as save, \
                    patch.object(publish, "write_new_silver", side_effect=write) as writer, \
                    patch.object(publish, "validate_readback"):
                options = dict(spark=None, frame=None, counts={"row_count": 2, "match_count": 2}, inputs=inputs,
                    specification=spec, bucket="test-bucket", client=s3, connection=None)
                if fail_registration:
                    save.side_effect = TimeoutError("secret")
                    with self.assertRaises(TimeoutError):
                        publish.publish_build(**options)
                    save.side_effect = register
                first = publish.publish_build(**options)
                self.assertEqual(first["catalog"], "REGISTERED")
                self.assertEqual(first["output_status"], "UNCHANGED / ALREADY_BUILT" if fail_registration else "CREATED")
                second = publish.publish_build(**options)
                self.assertEqual(second["catalog"], "ALREADY_REGISTERED")
                writer.assert_called_once()
                saved = manifest.read_manifest(s3, bucket="test-bucket", prefix=prefix, build_id=first["build_id"])
                self.assertEqual((len(saved["inputs"]), saved["row_count"], saved["match_count"], saved["file_count"]), (1, 2, 2, 1))
                s3.objects.pop(("test-bucket", prefix + "_SUCCESS"))
                with self.assertRaises(manifest.SilverIntegrityError):
                    publish.publish_build(**options)
                writer.assert_called_once()

    def test_matches_manifest_rejects_nonunique_count(self):
        inputs = [parent()]
        with self.assertRaises(manifest.SilverIntegrityError):
            manifest.make_manifest(self.specification(inputs), inputs, {"row_count": 3, "match_count": 2}, [{"object_key": "part", "size_bytes": 1, "etag": "etag"}])

    def test_schema_migration_explicit_casts_and_kickoff_boundary(self):
        sql = (Path(__file__).resolve().parents[1] / "infrastructure/clickhouse/migrations/005_create_matches.sql").read_text()
        body = sql.split("\n(\n")[1].split("\n)\n")[0]
        columns = tuple(tuple(line.strip().rstrip(",").split(" ", 1)) for line in body.splitlines())
        self.assertEqual(columns, (*MATCHES.target_columns[:-1], ("loaded_at", "DateTime64(3, 'UTC') DEFAULT now64(3)")))
        self.assertIn("ORDER BY (competition_id, season_id, match_date, match_id)", sql)
        insert = loader.insert_sql(spec=MATCHES)
        self.assertIn("accurateCast(ifNull(`kick_off`, ''), 'String')", insert)
        self.assertIn("accurateCast(accurateCast(toInt64(`match_date`), 'UInt16'), 'Date')", insert)
        self.assertNotIn("SELECT *", insert)

    def test_publish_cli_has_only_check_only(self):
        with patch.object(cli, "run_job", return_value=0) as run:
            self.assertEqual(cli.main(CONTEXT_ARGS + ["--parent-sha256", "a" * 64, "--teams-build-id", "b" * 64, "--check-only"]), 0)
            run.assert_called_once_with(check_only=True, competition_id=43, season_id=106, parent_sha256="a" * 64, teams_build_id="b" * 64)


class MatchModelTests(unittest.TestCase):
    def test_all_eleven_checks_are_build_scoped_and_hard(self):
        queries = matches_model.match_queries()
        self.assertEqual(len(queries), 11)
        client = MagicMock()
        for _, sql in queries:
            self.assertIn("competition_id = %(competition_id)s", sql)
            self.assertIn("season_id = %(season_id)s", sql)
            self.assertIn("_build_id)s", sql)
            self.assertNotIn("s3(", sql)
        for failed in range(-1, len(queries)):
            client.query.side_effect = [MagicMock(result_rows=[(int(index == failed),)]) for index in range(len(queries))]
            with redirect_stdout(io.StringIO()):
                if failed < 0:
                    self.assertEqual(len(in_context(matches_model.validate_match_references)(client, {})), 11)
                else:
                    with self.assertRaises(ClickHouseIntegrityError):
                        in_context(matches_model.validate_match_references)(client, {})
        client.command.assert_not_called()

    def test_full_model_preserves_old_checks_and_detects_changed_snapshot(self):
        with patch.object(matches_model, "current_builds", return_value={"matches": "a" * 64}) as silver, \
                patch.object(matches_model, "current_gold_builds", return_value={"team_match_stats": {"build_id": "b" * 64}}), \
                patch.object(matches_model, "validate_references", return_value={"old": 0}) as old, \
                patch.object(matches_model, "validate_match_references", return_value={"new": 0}), redirect_stdout(io.StringIO()):
            self.assertEqual(in_context(matches_model.check_model)(None, None), {"old": 0, "new": 0})
            old.assert_called_once()
            silver.side_effect = [{"matches": "a" * 64}, {"matches": "b" * 64}]
            with self.assertRaises(ClickHouseIntegrityError):
                in_context(matches_model.check_model)(None, None)


if __name__ == "__main__":
    unittest.main()
