"""Offline exact-build manifest checks using the existing in-memory S3 fixture."""

from context_fixtures import in_context

import copy
import os
import unittest
from unittest.mock import patch

from silver_fakes import FakeS3, artifact, seed_output, specification
from src.analytics.silver_input import parquet_url, resolve_silver_build, verify_silver_manifest
from src.common.checksum import sha256_bytes
from src.silver.build_identity import calculate_build_id, canonical_json, silver_prefix
from src.silver.manifest import SilverIntegrityError, inspect_silver_output, make_manifest

ENV = {"S3_ENDPOINT": "https://s3.ru-3.storage.selcloud.ru", "S3_BUCKET": "test-bucket"}


def fixture():
    s3 = FakeS3()
    inputs = [artifact(7), artifact(8)]
    spec = specification(inputs)
    build_id = calculate_build_id(spec)
    prefix = silver_prefix(spec, build_id)
    seed_output(s3, "test-bucket", prefix)
    files = inspect_silver_output(s3, bucket="test-bucket", prefix=prefix)
    manifest = make_manifest(spec, inputs, {"row_count": 6, "match_count": 2}, files)
    build = {**spec, "build_id": build_id, "s3_bucket": "test-bucket", "s3_prefix": prefix, "row_count": 6, "file_count": 4}
    seed_manifest(s3, build, manifest)
    s3.calls.clear()
    return s3, build, manifest


def seed_manifest(s3, build, manifest):
    raw = canonical_json(manifest)
    s3.seed(build["s3_bucket"], build["s3_prefix"] + "_manifest.json", raw,
            {"build_id": build["build_id"], "sha256": sha256_bytes(raw)})


class ClickHouseSilverInputTests(unittest.TestCase):
    def setUp(self):
        self.s3, self.build, self.manifest = fixture()
        env = patch.dict(os.environ, ENV, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_valid_manifest_only_gets_manifest_not_parquet(self):
        self.assertEqual(verify_silver_manifest(self.s3, self.build), self.manifest)
        self.assertEqual([call[2] for call in self.s3.calls if call[0] == "get"], [self.build["s3_prefix"] + "_manifest.json"])
        self.assertFalse(any(call[0] == "put" for call in self.s3.calls))

    def test_manifest_catalog_mismatches(self):
        for name, value in (('build_id', 'd' * 64), ('row_count', 7), ('schema_sha256', 'a' * 64),
                            ('file_count', 3), ('dataset', 'players'), ('competition_id', 1), ('season_id', 1),
                            ('transform_version', 'event_core_v2'), ('input_fingerprint', 'c' * 64), ('source', 'other')):
            with self.subTest(name=name):
                changed = {**self.manifest, name: value}
                seed_manifest(self.s3, self.build, changed)
                with self.assertRaises(SilverIntegrityError):
                    verify_silver_manifest(self.s3, self.build)

    def test_checksum_match_count_inputs_and_inventory_mismatches(self):
        variants = []
        for name, value in (("match_count", 1), ("layer", "bronze")):
            variants.append({**self.manifest, name: value})
        changed = copy.deepcopy(self.manifest)
        changed["inputs"][0]["sha256"] = "e" * 64
        variants.append(changed)
        changed = copy.deepcopy(self.manifest)
        changed["files"][0]["size_bytes"] += 1
        variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(SilverIntegrityError):
                seed_manifest(self.s3, self.build, changed)
                verify_silver_manifest(self.s3, self.build)

    def test_missing_manifest_success_extra_part_and_nested_object(self):
        for suffix in ("_manifest.json", "_SUCCESS"):
            s3, build, _ = fixture()
            del s3.objects[(build["s3_bucket"], build["s3_prefix"] + suffix)]
            with self.subTest(suffix=suffix), self.assertRaises(SilverIntegrityError):
                verify_silver_manifest(s3, build)

    def test_corrupt_checksum_and_malformed_lineage_remain_integrity_errors(self):
        key = (self.build["s3_bucket"], self.build["s3_prefix"] + "_manifest.json")
        self.s3.objects[key]["Metadata"]["sha256"] = "0" * 64
        with self.assertRaises(SilverIntegrityError):
            verify_silver_manifest(self.s3, self.build)
        for inputs in (None, [], [{}], ["secret-invalid-input"]):
            seed_manifest(self.s3, self.build, {**self.manifest, "inputs": inputs})
            with self.subTest(inputs=inputs), self.assertRaises(SilverIntegrityError):
                verify_silver_manifest(self.s3, self.build)
        for suffix in ("part-extra.snappy.parquet", "child/part-extra.snappy.parquet"):
            s3, build, _ = fixture()
            s3.seed(build["s3_bucket"], build["s3_prefix"] + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(SilverIntegrityError):
                verify_silver_manifest(s3, build)

    @patch("src.analytics.silver_input.find_latest_silver_build")
    @patch("src.analytics.silver_input.find_silver_build")
    def test_latest_and_exact_resolution(self, exact, latest):
        latest.return_value = exact.return_value = self.build
        self.assertEqual(in_context(resolve_silver_build)(None), self.build)
        latest.assert_called_once_with(None, source="statsbomb", dataset="event_core", competition_id=43, season_id=106)
        self.assertEqual(in_context(resolve_silver_build)(None, self.build["build_id"]), self.build)
        exact.assert_called_once_with(None, dataset="event_core", competition_id=43, season_id=106, build_id=self.build["build_id"])
        self.assertEqual(parquet_url(self.build), "https://test-bucket.s3.ru-3.storage.selcloud.ru/" + self.build["s3_prefix"] + "part-*.parquet")

    @patch("src.analytics.silver_input.find_latest_silver_build")
    def test_unsupported_version_context_bucket_prefix_or_missing_build(self, latest):
        for change in ({"transform_version": "event_core_v2"}, {"source": "other"}, {"dataset": "players"},
                       {"s3_bucket": "other-bucket"}, {"s3_prefix": "football/silver/"}, {"row_count": 0}, {"file_count": True}):
            latest.return_value = {**self.build, **change}
            with self.subTest(change=change), self.assertRaises(SilverIntegrityError):
                in_context(resolve_silver_build)(None)
        latest.return_value = None
        with self.assertRaises(SilverIntegrityError):
            in_context(resolve_silver_build)(None)


if __name__ == "__main__":
    unittest.main()
