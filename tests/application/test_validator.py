"""Generic API validator must accept non-WC contexts and zero-shot matches."""
import unittest
from scripts.check_application_api import validate


class ValidatorTests(unittest.TestCase):
    def test_non_wc_single_match_without_shots_is_valid(self):
        match = dict(competition_id=7, season_id=9, match_id=1, match_date="2025-01-01",
                     kick_off="12:00", home_team_id=10, away_team_id=20,
                     home_team_name="Home", away_team_name="Away", went_to_penalties=False)
        teams = [dict(team_id=i, shot_xg=0.0) for i in (10, 20)]
        players = [dict(team_id=10, player_id=1, event_count=0, shot_xg=0.0, is_home=True)]
        shootout = dict(match_id=1, went_to_penalties=False, attempts=[])
        data = dict(match=match, teams=teams, players=players, shots=[], xg_race=[], shootout=shootout)
        seen = []
        prefix = "/competitions/7/seasons/9/matches"
        def request(path):
            seen.append(path)
            if path in ("/health", "/health/clickhouse"): return 200, {"status": "ok"}
            if path == "/competitions": return 200, {"competitions": [{"competition_id": 7}]}
            if path == "/competitions/7/seasons": return 200, {"seasons": [{"season_id": 9}]}
            if path == prefix: return 200, {"matches": [match]}
            if path == prefix + "/18446744073709551615": return 404, {"error": {"code": "match_not_found"}}
            if path.endswith("/not-an-id") or path.endswith("team_id=oops"): return 400, {"error": {"code": "invalid_request"}}
            if path == prefix + "/1": return 200, match
            if path.endswith("/analysis"): return 200, data
            if path.endswith("/shootout"): return 200, shootout
            key = path.rsplit("/", 1)[1].split("?")[0].replace("-", "_")
            return 200, {key: data[key]}
        result = validate(request, competition_id=7, season_id=9)
        self.assertEqual(result["matches"], 1)
        self.assertEqual(result["checked_match_ids"], [1])
        self.assertFalse(any("/43/" in path or "/106/" in path for path in seen))
