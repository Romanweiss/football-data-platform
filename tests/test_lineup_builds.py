"""Lineup manifest, partition routing, immutability and DB recovery offline."""

import json
import unittest
from unittest.mock import MagicMock, patch

from silver_fakes import FakeS3, seed_output
from test_lineup_inputs import lineup_artifact
from src.silver import publish
from src.silver.build_identity import build_specification, calculate_build_id, input_fingerprint, silver_prefix
from src.silver.manifest import SilverIntegrityError, make_manifest


class LineupBuildTests(unittest.TestCase):
    def setup_build(self, dataset):
        inputs = [lineup_artifact(1), lineup_artifact(2)]
        spec = build_specification(dataset=dataset, transform_version=dataset + "_v1",
                                   input_fingerprint=input_fingerprint(inputs, artifact_kind="lineups"),
                                   schema_sha256="b" * 64, competition_id=43, season_id=106)
        counts = {"row_count": 4, "input_match_count": 2}
        if dataset == "match_squads":
            counts["match_count"] = 2
        return dict(spark=MagicMock(), frame=MagicMock(), counts=counts, inputs=inputs, specification=spec,
                    bucket="test-bucket", client=FakeS3(), connection=MagicMock())

    def test_each_dataset_publication_idempotency_and_db_recovery(self):
        for dataset, partitions in publish.LINEUP_OUTPUT_PARTITIONS.items():
            for recover_db in (False, True):
                with self.subTest(dataset=dataset, recovery=recover_db):
                    args = self.setup_build(dataset)
                    client = args["client"]
                    prefix = silver_prefix(args["specification"], calculate_build_id(args["specification"]))
                    records = {}
                    failures = [recover_db]

                    def write(frame, uri, *, partitions):
                        self.assertEqual(uri, "s3a://test-bucket/" + prefix)
                        client.seed("test-bucket", prefix + "_SUCCESS", b"{}")
                        for index in range(partitions):
                            client.seed("test-bucket", prefix + f"part-{index:05d}-test.snappy.parquet")

                    def register(connection, **record):
                        self.assertIn(("test-bucket", prefix + "_manifest.json"), client.objects)
                        if failures and failures.pop():
                            raise RuntimeError("synthetic DB failure")
                        records[record["build_id"]] = record
                        return True

                    with (
                        patch.object(publish, "find_silver_build", side_effect=lambda connection, **identity: records.get(identity["build_id"])),
                        patch.object(publish, "register_silver_build", side_effect=register) as registration,
                        patch.object(publish, "write_new_silver", side_effect=write) as writer,
                        patch.object(publish, "validate_readback") as readback,
                    ):
                        if recover_db:
                            with self.assertRaises(RuntimeError):
                                publish.publish_build(**args)
                        result = publish.publish_build(**args)
                        self.assertEqual(result["catalog"], "REGISTERED")
                        before = dict(client.objects)
                        again = publish.publish_build(**args)
                        self.assertEqual(again["output_status"], "UNCHANGED / ALREADY_BUILT")
                        self.assertEqual(again["catalog"], "ALREADY_REGISTERED")
                        self.assertEqual(client.objects, before)
                        writer.assert_called_once_with(args["frame"], "s3a://test-bucket/" + prefix, partitions=partitions)
                        self.assertEqual(registration.call_count, 2 if recover_db else 1)
                        self.assertGreaterEqual(readback.call_count, 2)
                        self.assertEqual(len(records), 1)
                    manifest = json.loads(client.objects[("test-bucket", prefix + "_manifest.json")]["Body"])
                    self.assertEqual(manifest["dataset"], dataset)
                    self.assertEqual(manifest["file_count"], partitions)
                    self.assertEqual(manifest["row_count"], 4)
                    self.assertEqual("match_count" in manifest, dataset == "match_squads")
                    self.assertEqual([item["match_id"] for item in manifest["inputs"]], [1, 2])
                    self.assertTrue(all("/lineups/" in item["source_url"] for item in manifest["inputs"]))

    def test_complete_unregistered_output_repairs_manifest_without_write(self):
        for dataset in publish.LINEUP_OUTPUT_PARTITIONS:
            args = self.setup_build(dataset)
            prefix = silver_prefix(args["specification"], calculate_build_id(args["specification"]))
            seed_output(args["client"], "test-bucket", prefix)
            record = {}

            def register(connection, **values):
                record.update(values)
                return True

            with (
                patch.object(publish, "find_silver_build", side_effect=lambda *a, **kw: record or None),
                patch.object(publish, "register_silver_build", side_effect=register),
                patch.object(publish, "write_new_silver") as writer,
                patch.object(publish, "validate_readback"),
            ):
                self.assertEqual(publish.publish_build(**args)["output_status"], "UNCHANGED / ALREADY_BUILT")
                writer.assert_not_called()
                self.assertIn(("test-bucket", prefix + "_manifest.json"), args["client"].objects)

    def test_partial_prefix_fails_without_cleanup_or_registration(self):
        args = self.setup_build("players")
        prefix = silver_prefix(args["specification"], calculate_build_id(args["specification"]))
        args["client"].seed("test-bucket", prefix + "part-partial.snappy.parquet")
        before = dict(args["client"].objects)
        with patch.object(publish, "find_silver_build", return_value=None), patch.object(publish, "register_silver_build") as register:
            with self.assertRaises(SilverIntegrityError):
                publish.publish_build(**args)
            register.assert_not_called()
        self.assertEqual(args["client"].objects, before)

    def test_dimensions_still_require_complete_input_coverage(self):
        for dataset in ("teams", "players"):
            args = self.setup_build(dataset)
            args["counts"]["input_match_count"] = 1
            with self.assertRaises(SilverIntegrityError):
                make_manifest(args["specification"], args["inputs"], args["counts"], [{"object_key": "part.snappy.parquet", "size_bytes": 1, "etag": "a"}])

    def test_writer_repartitions_and_keeps_immutable_snappy_mode(self):
        for partitions in (1, 2, 4):
            frame = MagicMock()
            publish.write_new_silver(frame, "s3a://test-bucket/build/", partitions=partitions)
            frame.repartition.assert_called_once_with(partitions)
            frame.repartition.return_value.write.mode.assert_called_once_with("errorifexists")
            frame.repartition.return_value.write.mode.return_value.option.assert_called_once_with("compression", "snappy")


if __name__ == "__main__":
    unittest.main()
