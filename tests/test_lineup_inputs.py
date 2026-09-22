"""Offline lineup URL, parent membership, immutable path and identity tests."""

import unittest

from silver_fakes import artifact
from src.common.bronze import BronzeIntegrityError
from src.silver.build_identity import build_specification, calculate_build_id, input_fingerprint
from src.silver.statsbomb.membership import lineup_artifact_s3a_path, select_parent_lineup_artifacts
from src.statsbomb.lineups import LineupArtifactError, extract_match_id_from_lineups_url

BASE = "https://raw.githubusercontent.com/hudl/open-data/master/data/lineups/"


def lineup_artifact(match_id=1, checksum="a" * 64):
    return {
        **artifact(match_id, checksum), "source_url": f"{BASE}{match_id}.json",
        "object_key": f"football/bronze/statsbomb/lineups/match_id={match_id}/sha256={checksum}/lineups.json",
    }


class LineupInputTests(unittest.TestCase):
    def test_canonical_url_and_bigint_boundary(self):
        for value in (1, 3869685, 2**63 - 1):
            self.assertEqual(extract_match_id_from_lineups_url(BASE + f"{value}.json"), value)

    def test_reject_noncanonical_urls_without_echoing_values(self):
        urls = [None, 1, "", BASE + "0.json", BASE + "01.json", BASE + "-1.json", BASE + "1.5.json",
                BASE + "１.json", BASE + "9223372036854775808.json", BASE + "1.JSON", BASE + "1.json/",
                BASE + "1.json\n", " " + BASE + "1.json", BASE + "1.json?token=secret", BASE + "1.json#secret",
                BASE + "%31.json", BASE + "../1.json", BASE.replace("https:", "http:") + "1.json",
                BASE.replace("hudl", "statsbomb") + "1.json", BASE.replace("master", "main") + "1.json",
                BASE.replace("lineups", "events") + "1.json", BASE.replace(".com/", ".com.evil/") + "1.json",
                BASE.replace("https://", "https://user:secret@") + "1.json", BASE.replace(".com/", ".com:443/") + "1.json"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(LineupArtifactError) as caught:
                extract_match_id_from_lineups_url(url)
            self.assertNotIn("secret", str(caught.exception))

    def test_exact_parent_membership_ignores_other_matches(self):
        selected = select_parent_lineup_artifacts([2, 1], [lineup_artifact(99), lineup_artifact(2), lineup_artifact(1)])
        self.assertEqual([item["match_id"] for item in selected], [1, 2])

    def test_missing_and_duplicate_artifacts_fail(self):
        for inputs in ([lineup_artifact(1)], [lineup_artifact(1), lineup_artifact(1), lineup_artifact(2)]):
            with self.assertRaises(LineupArtifactError):
                select_parent_lineup_artifacts([1, 2], inputs)
        for ids in ([], [0], [True], [1, 1]):
            with self.assertRaises(LineupArtifactError):
                select_parent_lineup_artifacts(ids, [lineup_artifact(1)])

    def test_immutable_path_matches_url_hash_and_kind(self):
        item = lineup_artifact(1)
        self.assertEqual(lineup_artifact_s3a_path(item), "s3a://test-bucket/" + item["object_key"])
        for key in (lineup_artifact(2)["object_key"], lineup_artifact(1, "b" * 64)["object_key"],
                    artifact(1)["object_key"], item["object_key"].replace("/lineups/", "/events/"), "flat/lineups.json"):
            with self.subTest(key=key), self.assertRaises(BronzeIntegrityError):
                lineup_artifact_s3a_path({**item, "object_key": key})

    def test_fingerprint_order_and_identity_changes(self):
        inputs = [lineup_artifact(1), lineup_artifact(2)]
        fingerprint = input_fingerprint(inputs, artifact_kind="lineups")
        self.assertEqual(fingerprint, input_fingerprint(list(reversed(inputs)), artifact_kind="lineups"))
        changed = input_fingerprint([lineup_artifact(1, "c" * 64), lineup_artifact(2)], artifact_kind="lineups")
        self.assertNotEqual(fingerprint, changed)
        specs = [build_specification(dataset=name, transform_version=name + "_v1", input_fingerprint=fingerprint,
                                     schema_sha256="b" * 64, competition_id=43, season_id=106)
                 for name in ("teams", "players", "match_squads")]
        self.assertEqual(len({calculate_build_id(spec) for spec in specs}), 3)
        self.assertEqual(len({spec["input_fingerprint"] for spec in specs}), 1)
        for spec in specs:
            self.assertNotEqual(calculate_build_id(spec), calculate_build_id({**spec, "transform_version": spec["dataset"] + "_v2"}))
            self.assertNotEqual(calculate_build_id(spec), calculate_build_id({**spec, "input_fingerprint": changed}))

    def test_wrong_input_kind_duplicates_and_identity_mismatch_fail(self):
        for inputs in ([artifact(1)], [lineup_artifact(1), artifact(2)], [lineup_artifact(1), lineup_artifact(1)],
                       [{**lineup_artifact(1), "match_id": 2}], []):
            with self.assertRaises(ValueError):
                input_fingerprint(inputs, artifact_kind="lineups")
        with self.assertRaises(ValueError):
            input_fingerprint([lineup_artifact(1)])


if __name__ == "__main__":
    unittest.main()
