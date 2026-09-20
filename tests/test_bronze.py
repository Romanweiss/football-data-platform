"""Versioned keys are deterministic and never need S3 access."""

import unittest

from src.common.bronze import build_versioned_key


class BuildVersionedKeyTests(unittest.TestCase):
    def setUp(self):
        self.prefix = "football/bronze/statsbomb/competitions"
        self.filename = "competitions.json"
        self.checksum = "0123456789abcdef" * 4

    def test_expected_key(self):
        self.assertEqual(
            build_versioned_key(self.prefix, self.filename, self.checksum),
            f"football/bronze/statsbomb/competitions/sha256={self.checksum}/competitions.json",
        )

    def test_same_checksum_produces_same_key(self):
        self.assertEqual(
            build_versioned_key(self.prefix, self.filename, self.checksum),
            build_versioned_key(self.prefix, self.filename, self.checksum),
        )

    def test_different_checksums_produce_different_keys(self):
        self.assertNotEqual(
            build_versioned_key(self.prefix, self.filename, "a" * 64),
            build_versioned_key(self.prefix, self.filename, "b" * 64),
        )

    def test_rejects_invalid_checksums(self):
        for checksum in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"):
            with self.subTest(checksum=checksum):
                with self.assertRaises(ValueError):
                    build_versioned_key(self.prefix, self.filename, checksum)

    def test_normalizes_separators(self):
        self.assertEqual(
            build_versioned_key(" /football//bronze///statsbomb/ ", "/data.json/", self.checksum),
            f"football/bronze/statsbomb/sha256={self.checksum}/data.json",
        )

    def test_rejects_empty_components(self):
        for empty in ("", " ", "///", " / / "):
            with self.subTest(empty=empty):
                with self.assertRaises(ValueError):
                    build_versioned_key(empty, self.filename, self.checksum)
                with self.assertRaises(ValueError):
                    build_versioned_key(self.prefix, empty, self.checksum)

    def test_rejects_filename_with_nested_path(self):
        for name in ("folder/data.json", "folder\\data.json", ".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    build_versioned_key(self.prefix, name, self.checksum)


if __name__ == "__main__":
    unittest.main()
