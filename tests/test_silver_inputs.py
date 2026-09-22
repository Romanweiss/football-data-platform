"""Offline HEAD preflight, World Cup membership and deterministic identities."""

import unittest
from unittest.mock import MagicMock

from botocore.exceptions import ClientError

from silver_fakes import artifact, error, specification
from src.common.bronze import BronzeIntegrityError
from src.common.bronze_reader import verify_bronze_object_metadata
from src.silver.build_identity import calculate_build_id, canonical_inputs, canonical_json, input_fingerprint
from src.silver.statsbomb.membership import event_artifact_s3a_path, select_parent_event_artifacts
from src.statsbomb.events import EventArtifactError


class BronzeMetadataPreflightTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=["head_object"])
        self.input = artifact()
        self.client.head_object.return_value = {"Metadata": {"sha256": self.input["sha256"]}}

    def test_valid_head_only(self):
        verify_bronze_object_metadata(self.client, self.input)
        self.client.head_object.assert_called_once_with(Bucket="test-bucket", Key=self.input["object_key"])

    def test_mismatched_or_missing_metadata(self):
        for metadata in ({}, {"sha256": "b" * 64}):
            self.client.head_object.return_value = {"Metadata": metadata}
            with self.assertRaises(BronzeIntegrityError):
                verify_bronze_object_metadata(self.client, self.input)

    def test_wrong_key_checksum_fails_before_head(self):
        self.input["sha256"] = "b" * 64
        with self.assertRaises(BronzeIntegrityError):
            verify_bronze_object_metadata(self.client, self.input)
        self.client.head_object.assert_not_called()

    def test_missing_object_is_integrity_failure(self):
        self.client.head_object.side_effect = error("404", "HeadObject")
        with self.assertRaisesRegex(BronzeIntegrityError, "missing"):
            verify_bronze_object_metadata(self.client, self.input)

    def test_access_denied_and_missing_bucket_propagate(self):
        for code in ("AccessDenied", "NoSuchBucket"):
            self.client.head_object.side_effect = error(code, "HeadObject")
            with self.assertRaises(ClientError) as caught:
                verify_bronze_object_metadata(self.client, self.input)
            self.assertEqual(caught.exception.response["Error"]["Code"], code)


class ParentMembershipTests(unittest.TestCase):
    def test_exact_parent_and_extra_league_ignored(self):
        result = select_parent_event_artifacts([2, 1], [artifact(3), artifact(2), artifact(1)])
        self.assertEqual([item["match_id"] for item in result], [1, 2])

    def test_missing_parent_event_fails(self):
        with self.assertRaisesRegex(EventArtifactError, "Missing event artifacts"):
            select_parent_event_artifacts([1, 2], [artifact(1), artifact(99)])

    def test_duplicate_selected_match_fails(self):
        with self.assertRaisesRegex(EventArtifactError, "Duplicate latest"):
            select_parent_event_artifacts([1], [artifact(1), artifact(1, "b" * 64)])

    def test_empty_or_invalid_parent_fails(self):
        for ids in ([], [0], [True], [1, 1]):
            with self.subTest(ids=ids), self.assertRaises(EventArtifactError):
                select_parent_event_artifacts(ids, [artifact()])

    def test_path_identity_must_match_url_and_catalog(self):
        item = artifact(1)
        self.assertEqual(event_artifact_s3a_path(item), f"s3a://test-bucket/{item['object_key']}")
        for wrong_key in (artifact(2)["object_key"], artifact(1, "b" * 64)["object_key"], "flat/events.json"):
            with self.subTest(key=wrong_key), self.assertRaises(BronzeIntegrityError):
                event_artifact_s3a_path({**item, "object_key": wrong_key})


class BuildIdentityTests(unittest.TestCase):
    def test_input_order_does_not_change_fingerprint(self):
        self.assertEqual(input_fingerprint([artifact(1), artifact(2)]), input_fingerprint([artifact(2), artifact(1)]))

    def test_one_checksum_change_changes_fingerprint(self):
        base = artifact(1)
        self.assertNotEqual(input_fingerprint([base]), input_fingerprint([{**base, "sha256": "b" * 64}]))

    def test_transform_version_or_schema_changes_build_id(self):
        spec = specification([artifact()])
        for update in ({"transform_version": "event_core_v2"}, {"schema_sha256": "c" * 64}):
            self.assertNotEqual(calculate_build_id(spec), calculate_build_id({**spec, **update}))

    def test_timestamps_and_extra_fields_do_not_enter_identity(self):
        base = artifact()
        enriched = {**base, "first_seen_at": "tomorrow", "secret": "synthetic-secret"}
        self.assertEqual(input_fingerprint([base]), input_fingerprint([enriched]))
        self.assertNotIn(b"synthetic-secret", canonical_json(canonical_inputs([enriched])))
        spec = specification([base])
        self.assertEqual(calculate_build_id(spec), calculate_build_id({**spec, "created_at": "now", "machine": "other"}))

    def test_canonical_json_is_utf8_sorted_and_compact(self):
        self.assertEqual(canonical_json({"z": "Матч", "a": 1}), '{"a":1,"z":"Матч"}'.encode("utf-8"))

    def test_duplicates_and_identity_mismatch_fail(self):
        for inputs in ([artifact(), artifact()], [{**artifact(), "match_id": 2}], []):
            with self.assertRaises(ValueError):
                input_fingerprint(inputs)


if __name__ == "__main__":
    unittest.main()
