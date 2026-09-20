"""Offline SHA-256 tests with known reference values."""

import unittest

from src.common.checksum import sha256_bytes


class Sha256BytesTests(unittest.TestCase):
    def test_known_vectors(self):
        vectors = (
            (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
            (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
        )
        for data, expected in vectors:
            with self.subTest(data=data):
                self.assertEqual(sha256_bytes(data), expected)

    def test_json_whitespace_changes_the_checksum(self):
        self.assertNotEqual(sha256_bytes(b'{"id":1}'), sha256_bytes(b'{ "id": 1 }\r\n'))


if __name__ == "__main__":
    unittest.main()
