"""Explicit opt-in live SELECT-only tests; excluded from offline discovery."""
import unittest
import math
from unittest.mock import patch
from scripts.check_application_api import make_request, validate
from application.repository import open_repository
from application.services import FootballService


class LiveApiTests(unittest.TestCase):
    def test_four_real_matches_and_all_http_contracts(self):
        result = validate(make_request())
        self.assertEqual(result["matches"], 64)
        self.assertEqual(len(result["checked_match_ids"]), 4)

    def test_all_64_matches_preserve_tournament_coverage(self):
        with open_repository() as repository:
            service = FootballService(repository)
            rows = [service.analysis(match["match_id"]) for match in repository.matches()]
        self.assertEqual(len(rows), 64)
        players = [player for row in rows for player in row["players"]]
        shots = [shot for row in rows for shot in row["shots"]]
        self.assertEqual(len(players), 3244)
        self.assertTrue(any(player["event_count"] == 0 for player in players))
        self.assertEqual(len(shots), 1453)
        self.assertEqual(sum(shot["is_extra_time"] for shot in shots), 45)
        self.assertTrue(all(shot["period"] != 5 for shot in shots))
        self.assertAlmostEqual(math.fsum(shot["statsbomb_xg"] for shot in shots), 155.8985419302, places=9)
        self.assertEqual(sum(len(row["shootout"]["attempts"]) for row in rows), 41)

    def test_composite_six_data_selects_plus_driver_bootstrap(self):
        from clickhouse_connect.driver.httpclient import HttpClient
        original = HttpClient._raw_request
        count = 0

        def measured(client, *args, **kwargs):
            nonlocal count
            count += 1
            return original(client, *args, **kwargs)

        with patch.object(HttpClient, "_raw_request", measured):
            with open_repository() as repository:
                bootstrap_count = count
                FootballService(repository).analysis(3869685)
        self.assertEqual(count - bootstrap_count, 6)
        print(f"Composite requests: BI=6 driver_bootstrap={bootstrap_count} total={count}")


if __name__ == "__main__": unittest.main()
