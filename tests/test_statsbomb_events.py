"""Offline validation of canonical event artifact identity."""

import unittest

from src.statsbomb.events import EventArtifactError, extract_match_id_from_events_url

BASE = "https://raw.githubusercontent.com/hudl/open-data/master/data/events/"


class EventsUrlTests(unittest.TestCase):
    def test_canonical_url_returns_integer(self):
        self.assertEqual(extract_match_id_from_events_url(BASE + "3869685.json"), 3869685)

    def test_invalid_structures_are_rejected(self):
        urls = [
            None, 123, "", BASE + "0.json", BASE + "01.json", BASE + "-1.json",
            BASE + "1.0.json", BASE + "true.json", BASE + "１.json",
            BASE + "1.JSON", BASE + "1.json/", BASE + "1.json?token=secret",
            BASE + "1.json#fragment", BASE + "1.json\n", " " + BASE + "1.json",
            BASE + "../1.json", BASE + "%31.json", BASE + "9223372036854775808.json",
            BASE.replace("https:", "http:") + "1.json",
            BASE.replace("raw.githubusercontent.com", "raw.githubusercontent.com.evil") + "1.json",
            BASE.replace("raw.githubusercontent.com", "user:secret@raw.githubusercontent.com") + "1.json",
            BASE.replace("raw.githubusercontent.com", "raw.githubusercontent.com:443") + "1.json",
            BASE.replace("hudl", "statsbomb") + "1.json",
            BASE.replace("master", "main") + "1.json",
            BASE.replace("events/", "lineups/") + "1.json",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(EventArtifactError) as caught:
                extract_match_id_from_events_url(url)
            self.assertNotIn("secret", str(caught.exception))

    def test_bigint_boundary(self):
        self.assertEqual(extract_match_id_from_events_url(BASE + f"{2**63 - 1}.json"), 2**63 - 1)


if __name__ == "__main__":
    unittest.main()
