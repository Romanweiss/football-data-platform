"""Dataset identity isolation and reuse of the Stage 2B publication/recovery contract."""

import json
import unittest
from unittest.mock import MagicMock, patch

from silver_fakes import FakeS3, artifact, seed_output, specification
from src.silver import publish
from src.silver.build_identity import build_specification, calculate_build_id, input_fingerprint, silver_prefix
from src.silver.manifest import SilverIntegrityError


class DomainBuildTests(unittest.TestCase):
    def spec(self, dataset, inputs=None, version=None):
        return build_specification(
            input_fingerprint=input_fingerprint(inputs or [artifact(1), artifact(2)]), schema_sha256="b" * 64,
            transform_version=version or dataset + "_v1", dataset=dataset, competition_id=43, season_id=106,
        )

    def test_dataset_ids_differ_but_input_fingerprints_match(self):
        specs = [self.spec(name) for name in ("event_core", "pass_events", "shot_events")]
        self.assertEqual(len({calculate_build_id(spec) for spec in specs}), 3)
        self.assertEqual(len({spec["input_fingerprint"] for spec in specs}), 1)
        for spec in specs:
            self.assertTrue(silver_prefix(spec, calculate_build_id(spec)).startswith(f"football/silver/statsbomb/{spec['dataset']}/"))

    def test_input_order_is_independent_and_transform_changes_identity(self):
        for name in ("pass_events", "shot_events"):
            forward = self.spec(name, [artifact(1), artifact(2)])
            reverse = self.spec(name, [artifact(2), artifact(1)])
            self.assertEqual(calculate_build_id(forward), calculate_build_id(reverse))
            self.assertNotEqual(calculate_build_id(forward), calculate_build_id(self.spec(name, version=name + "_v2")))

    def test_event_core_default_spec_and_prefix_match_stage_2b_contract(self):
        old_contract = {
            "source": "statsbomb", "layer": "silver", "dataset": "event_core",
            "competition_id": 43, "season_id": 106, "transform_version": "event_core_v1",
            "input_fingerprint": input_fingerprint([artifact(1), artifact(2)]), "schema_sha256": "b" * 64,
        }
        self.assertEqual(specification([artifact(1), artifact(2)]), old_contract)
        build_id = calculate_build_id(old_contract)
        self.assertEqual(silver_prefix(old_contract, build_id), f"football/silver/statsbomb/event_core/competition_id=43/season_id=106/build_id={build_id}/")

    def test_unknown_dataset_or_path_injection_rejected(self):
        for name in ("unknown", "../event_core", "pass_events/", "passes"):
            with self.subTest(dataset=name), self.assertRaises(ValueError):
                self.spec(name)
            with self.assertRaises(ValueError):
                silver_prefix({**self.spec("pass_events"), "dataset": name}, "a" * 64)

    def run_scenario(self, dataset, *, db_failure=False, missing_manifest=False, corrupt=False):
        client = FakeS3()
        inputs = [artifact(1), artifact(2)]
        spec = self.spec(dataset)
        prefix = silver_prefix(spec, calculate_build_id(spec))
        # A separate event_core build must remain byte-for-byte intact throughout.
        core_prefix = silver_prefix(self.spec("event_core"), calculate_build_id(self.spec("event_core")))
        seed_output(client, "test-bucket", core_prefix)
        core_objects = dict(client.objects)
        records = {}
        fail_registration = db_failure

        def register(connection, **record):
            nonlocal fail_registration
            self.assertIn(("test-bucket", prefix + "_manifest.json"), client.objects)
            if fail_registration:
                fail_registration = False
                raise RuntimeError("synthetic database failure")
            records[record["build_id"]] = record
            return True

        args = dict(spark=MagicMock(), frame=MagicMock(), counts={"row_count": 6, "match_count": 2},
                    inputs=inputs, specification=spec, bucket="test-bucket", client=client, connection=MagicMock())
        with (
            patch.object(publish, "find_silver_build", side_effect=lambda connection, **identity: records.get(identity["build_id"])),
            patch.object(publish, "register_silver_build", side_effect=register) as registration,
            patch.object(publish, "write_new_silver", side_effect=lambda frame, uri: seed_output(client, "test-bucket", prefix)) as write,
            patch.object(publish, "validate_readback") as readback,
        ):
            if corrupt:
                client.seed("test-bucket", prefix + "part-partial.snappy.parquet")
                before = dict(client.objects)
                with self.assertRaises(SilverIntegrityError):
                    publish.publish_build(**args)
                self.assertEqual(client.objects, before)
                write.assert_not_called()
                registration.assert_not_called()
                return
            if missing_manifest:
                seed_output(client, "test-bucket", prefix)
            if db_failure:
                with self.assertRaises(RuntimeError):
                    publish.publish_build(**args)
            result = publish.publish_build(**args)
            self.assertEqual(result["catalog"], "REGISTERED")
            before = dict(client.objects)
            again = publish.publish_build(**args)
            self.assertEqual(again["output_status"], "UNCHANGED / ALREADY_BUILT")
            self.assertEqual(again["catalog"], "ALREADY_REGISTERED")
            self.assertEqual(client.objects, before)
            self.assertEqual(write.call_count, 0 if missing_manifest else 1)
            self.assertGreaterEqual(readback.call_count, 2)
            self.assertEqual(len(records), 1)
            manifest = json.loads(client.objects[("test-bucket", prefix + "_manifest.json")]["Body"])
            self.assertEqual(manifest["dataset"], dataset)
            self.assertEqual(manifest["transform_version"], dataset + "_v1")
            self.assertEqual([item["match_id"] for item in manifest["inputs"]], [1, 2])
            self.assertEqual(manifest["file_count"], 4)
            self.assertEqual(manifest["build_id"], result["build_id"])
            self.assertEqual({key: client.objects[key] for key in core_objects}, core_objects)

    def test_both_domains_publish_correct_manifest_and_skip_identical_write(self):
        for dataset in ("pass_events", "shot_events"):
            with self.subTest(dataset=dataset):
                self.run_scenario(dataset)

    def test_both_domains_recover_database_failure_without_parquet_rewrite(self):
        for dataset in ("pass_events", "shot_events"):
            with self.subTest(dataset=dataset):
                self.run_scenario(dataset, db_failure=True)

    def test_both_domains_recover_missing_manifest_without_parquet_rewrite(self):
        for dataset in ("pass_events", "shot_events"):
            with self.subTest(dataset=dataset):
                self.run_scenario(dataset, missing_manifest=True)

    def test_partial_domain_prefix_is_not_cleaned_or_rewritten(self):
        for dataset in ("pass_events", "shot_events"):
            with self.subTest(dataset=dataset):
                self.run_scenario(dataset, corrupt=True)


if __name__ == "__main__":
    unittest.main()
