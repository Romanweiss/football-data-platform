"""Offline validation of StatsBomb match-list JSON."""

import unittest

from src.statsbomb.matches import MatchDataError, extract_match_ids


class ExtractMatchIdsTests(unittest.TestCase):
    def test_valid_json_extracts_integer_ids_without_changing_bytes(self):
        raw = '[{"match_id": 9, "label": "Матч"}, {"match_id": 3}]\r\n'.encode("utf-8")
        original = bytes(raw)
        self.assertEqual(extract_match_ids(raw), [9, 3])
        self.assertEqual(raw, original)

    def test_deduplicates_and_preserves_first_appearance_order(self):
        self.assertEqual(
            extract_match_ids(b'[{"match_id": 7}, {"match_id": 2}, {"match_id": 7}, {"match_id": 1}, {"match_id": 2}]'),
            [7, 2, 1],
        )

    def test_empty_list_is_valid(self):
        self.assertEqual(extract_match_ids(b"[]"), [])

    def test_invalid_json_is_reported_without_dumping_source(self):
        with self.assertRaisesRegex(MatchDataError, "Invalid matches JSON") as caught:
            extract_match_ids(b"[private-source-content")
        self.assertNotIn("private-source-content", str(caught.exception))

    def test_invalid_utf8_is_rejected(self):
        with self.assertRaisesRegex(MatchDataError, "UTF-8"):
            extract_match_ids(b"\xff")

    def test_non_list_root_is_rejected(self):
        for raw in (b"{}", b"null", b"1", b'"text"'):
            with self.subTest(raw=raw), self.assertRaisesRegex(MatchDataError, "root must be a list"):
                extract_match_ids(raw)

    def test_entry_must_be_object(self):
        for raw in (b"[null]", b"[1]", b"[[]]"):
            with self.subTest(raw=raw), self.assertRaisesRegex(MatchDataError, "entry 0 must be an object"):
                extract_match_ids(raw)

    def test_missing_match_id_is_rejected(self):
        with self.assertRaisesRegex(MatchDataError, "entry 0 is missing match_id"):
            extract_match_ids(b"[{}]")

    def test_non_integer_match_id_is_rejected_including_booleans(self):
        for value in (b'"1"', b"1.0", b"null", b"true", b"false", b"[]", b"{}"):
            with self.subTest(value=value), self.assertRaisesRegex(MatchDataError, "must be an integer"):
                extract_match_ids(b'[{"match_id": ' + value + b"}]")


if __name__ == "__main__":
    unittest.main()
