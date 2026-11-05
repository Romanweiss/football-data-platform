"""PET-2 edge regressions, using artificial records only; no acquired-file dependency."""
from dataclasses import replace
from hashlib import sha256
import unittest

from src.providers.identity_registry import IdentityRegistry
from src.providers.models import FixtureStatus
from src.providers.observed_versions import VersionLedger
from src.providers.openfootball import OpenFootballError, prepare_openfootball
from src.providers.openfootball_manifest import UCL_2024_25
from test_openfootball import NOW, encode, mapping, payload


class OpenFootballScoreEdgeTests(unittest.TestCase):
    def test_json_repository_is_not_upstream_txt_repository(self):
        self.assertEqual("https://github.com/openfootball/football.json", UCL_2024_25.repository)
        self.assertNotEqual("https://github.com/openfootball/champions-league", UCL_2024_25.repository)
        self.assertEqual("2024-25/uefa.cl.json", UCL_2024_25.path)
        self.assertIsNone(UCL_2024_25.content_sha256)  # Template is not a local acquisition receipt.

    def test_et_and_penalty_fields_are_retained_not_silently_entered_as_regulation_score(self):
        for extra in ({"et": [0, 1]}, {"p": [4, 4]}, {"et": [0, 1], "p": [4, 4]}):
            source = payload()
            source["matches"][2]["score"] = {"ft": [0, 1], "ht": [0, 1], **extra}
            with self.subTest(fields=tuple(extra)):
                proposal = prepare_openfootball(encode(source), mapping=mapping(), observed_at=NOW)
                item = next(f for f in proposal.fixtures if f.source_ft == (0, 1))
                self.assertEqual(tuple(extra["et"]) if "et" in extra else None, item.source_et)
                self.assertEqual(tuple(extra["p"]) if "p" in extra else None, item.source_p)
                self.assertIsNone(item.regulation_score)
                self.assertIsNone(item.penalty_shootout_score)
                self.assertIsNone(item.winner_id)

    def test_empty_score_is_not_absent_score_and_not_zero_zero(self):
        source = payload()
        source["matches"][2]["score"] = {}
        proposal = prepare_openfootball(source, mapping=mapping(), observed_at=NOW)
        item = next(f for f in proposal.fixtures if f.source_ft is None)
        self.assertEqual("EMPTY", item.source_score_state)
        self.assertEqual(FixtureStatus.UNKNOWN, item.status)
        del source["matches"][2]["score"]
        proposal = prepare_openfootball(source, mapping=mapping(), observed_at=NOW)
        item = next(f for f in proposal.fixtures if f.source_ft is None)
        self.assertEqual(FixtureStatus.UNKNOWN, item.status)
        self.assertEqual("ABSENT", item.source_score_state)
        self.assertIsNone(item.regulation_score)

    def test_late_bad_score_rejects_whole_batch_without_changing_input_states(self):
        initial = prepare_openfootball(payload(), mapping=mapping(), observed_at=NOW)
        registry = IdentityRegistry.from_bytes(initial.registry_after_state)
        ledger = VersionLedger.from_bytes(initial.ledger_after_state)
        before = registry.to_bytes(), ledger.to_bytes()
        source = payload()
        source["matches"][2]["score"] = {"p": [-1, 4]}
        with self.assertRaisesRegex(OpenFootballError, "SCORE"):
            prepare_openfootball(source, mapping=mapping(), observed_at=NOW,
                registry=registry, versions=ledger, previous=initial)
        self.assertEqual(before, (registry.to_bytes(), ledger.to_bytes()))

    def test_ambiguous_full_bytes_replay_has_same_fingerprint_and_limitations(self):
        source = payload()
        source["matches"][2]["score"] = {"ft": [0, 1], "et": [0, 1], "p": [4, 4]}
        raw = encode(source)
        manifest = replace(UCL_2024_25, content_sha256=sha256(raw).hexdigest(), acquired_at=NOW)
        proposals = []
        for _ in range(2):
            proposals.append(prepare_openfootball(raw, mapping=mapping(), manifest=manifest, observed_at=NOW))
        self.assertEqual(proposals[0], proposals[1])
        self.assertEqual(1, proposals[0].dq.counts["TIED_PENALTY_PAIR"])
        self.assertEqual("ACCEPTED_WITH_LIMITATIONS", proposals[0].batch_status)

    def test_unmarked_ft_remains_source_score_not_certified_ninety_minutes(self):
        source = payload()
        source["matches"][2]["score"] = {"ft": [4, 3], "ht": [2, 0]}
        proposal = prepare_openfootball(source, mapping=mapping(), observed_at=NOW)
        item = next(f for f in proposal.fixtures if f.source_ft == (4, 3))
        self.assertIsNone(item.regulation_score)
        self.assertIsNone(item.kickoff_utc)
        self.assertEqual("source_ft_present", item.status_origin)
        self.assertFalse(proposal.publish_authorized)

    def test_failure_is_not_bypassed_by_reordering_bad_and_good_records(self):
        source = payload()
        source["matches"][2]["score"] = {"et": "not-a-pair"}
        for rows, expected_index in ((source["matches"], 2), (list(reversed(source["matches"])), 0)):
            with self.subTest(index=expected_index), self.assertRaises(OpenFootballError) as raised:
                prepare_openfootball({"name": source["name"], "matches": rows}, mapping=mapping(), observed_at=NOW)
            self.assertEqual("SCORE", raised.exception.diagnostic.code)
            self.assertEqual(expected_index, raised.exception.diagnostic.row)


if __name__ == "__main__":
    unittest.main()
