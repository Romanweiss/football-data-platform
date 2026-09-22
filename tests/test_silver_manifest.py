"""Offline immutable manifest and prefix inventory tests."""

import unittest

from silver_fakes import FakeS3, artifact, seed_output, specification
from src.common.checksum import sha256_bytes
from src.silver.build_identity import calculate_build_id, canonical_json, silver_prefix
from src.silver.manifest import (
    SilverIntegrityError, ensure_manifest, inspect_silver_output, make_manifest, read_manifest,
)


class SilverManifestTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeS3()
        self.inputs = [artifact(2), artifact(1)]
        self.spec = specification(self.inputs)
        self.build_id = calculate_build_id(self.spec)
        self.bucket = "test-bucket"
        self.prefix = silver_prefix(self.spec, self.build_id)
        seed_output(self.client, self.bucket, self.prefix)
        self.files = inspect_silver_output(self.client, bucket=self.bucket, prefix=self.prefix)
        self.manifest = make_manifest(self.spec, self.inputs, {"row_count": 6, "match_count": 2}, self.files)

    def ensure(self):
        ensure_manifest(self.client, bucket=self.bucket, prefix=self.prefix, manifest=self.manifest)

    def test_deterministic_required_fields_without_credentials(self):
        enriched = [{**item, "AWS_SECRET_ACCESS_KEY": "synthetic-secret"} for item in reversed(self.inputs)]
        other = make_manifest({**self.spec, "secret": "synthetic-secret"}, enriched,
                              {"row_count": 6, "match_count": 2}, list(reversed(self.files)))
        self.assertEqual(canonical_json(self.manifest), canonical_json(other))
        for name in ("source", "layer", "dataset", "competition_id", "season_id", "transform_version",
                     "input_fingerprint", "schema_sha256", "build_id", "row_count", "match_count", "file_count", "inputs"):
            self.assertIn(name, self.manifest)
        self.assertNotIn(b"synthetic-secret", canonical_json(other))
        self.assertEqual(self.manifest["file_count"], 4)
        self.assertEqual([item["match_id"] for item in self.manifest["inputs"]], [1, 2])

    def test_conditional_manifest_create_then_repeat_no_overwrite(self):
        self.ensure()
        self.ensure()
        puts = [call for call in self.client.calls if call[0] == "put"]
        self.assertEqual(len(puts), 1)
        stored = self.client.objects[(self.bucket, self.prefix + "_manifest.json")]
        self.assertEqual(stored["Metadata"]["build_id"], self.build_id)
        self.assertEqual(stored["Metadata"]["sha256"], sha256_bytes(stored["Body"]))

    def test_incompatible_manifest_is_never_overwritten(self):
        self.ensure()
        before = dict(self.client.objects)
        self.manifest["row_count"] += 1
        with self.assertRaisesRegex(SilverIntegrityError, "manifest does not match"):
            self.ensure()
        self.assertEqual(before, self.client.objects)

    def test_wrong_build_id_metadata_is_rejected(self):
        self.ensure()
        self.client.objects[(self.bucket, self.prefix + "_manifest.json")]["Metadata"]["build_id"] = "f" * 64
        with self.assertRaisesRegex(SilverIntegrityError, "metadata"):
            self.ensure()

    def test_corrupt_manifest_body_is_rejected(self):
        key = self.prefix + "_manifest.json"
        self.client.seed(self.bucket, key, b"not-json", {"build_id": self.build_id, "sha256": sha256_bytes(b"not-json")})
        with self.assertRaisesRegex(SilverIntegrityError, "UTF-8 JSON"):
            self.ensure()

    def test_conditional_race_accepts_identical_winner(self):
        put = self.client.put_object

        def raced_put(**kwargs):
            self.client.seed(kwargs["Bucket"], kwargs["Key"], kwargs["Body"], kwargs["Metadata"])
            return put(**kwargs)  # raises 412, then ensure reads the winner

        self.client.put_object = raced_put
        self.ensure()

    def test_prefix_inventory_is_paginated_and_exact(self):
        self.client.seed(self.bucket, self.prefix.rstrip("/") + "-other/part-other.snappy.parquet")
        self.assertEqual(inspect_silver_output(self.client, bucket=self.bucket, prefix=self.prefix), self.files)

    def test_absent_prefix_returns_none(self):
        self.assertIsNone(inspect_silver_output(self.client, bucket=self.bucket, prefix="absent/"))

    def test_missing_success_or_missing_parts_is_corrupt(self):
        for key in ("part-00000.snappy.parquet", "_SUCCESS", "_manifest.json"):
            client = FakeS3()
            client.seed(self.bucket, self.prefix + key)
            with self.subTest(key=key), self.assertRaises(SilverIntegrityError):
                inspect_silver_output(client, bucket=self.bucket, prefix=self.prefix)

    def test_unexpected_object_is_corrupt(self):
        self.client.seed(self.bucket, self.prefix + "_temporary/leftover")
        with self.assertRaisesRegex(SilverIntegrityError, "unexpected"):
            inspect_silver_output(self.client, bucket=self.bucket, prefix=self.prefix)

    def test_manifest_rejects_wrong_input_fingerprint(self):
        with self.assertRaisesRegex(SilverIntegrityError, "fingerprint"):
            make_manifest({**self.spec, "input_fingerprint": "f" * 64}, self.inputs,
                          {"row_count": 6, "match_count": 2}, self.files)

    def test_directory_marker_must_be_empty(self):
        self.client.seed(self.bucket, self.prefix, b"unexpected content")
        with self.assertRaisesRegex(SilverIntegrityError, "directory marker"):
            inspect_silver_output(self.client, bucket=self.bucket, prefix=self.prefix)


if __name__ == "__main__":
    unittest.main()
