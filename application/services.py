"""Application orchestration only; the ClickHouse views own all metric semantics."""
from application.errors import ApiError, ServingIntegrityError


class FootballService:
    def __init__(self, repository):
        self.repository = repository

    def match(self, match_id):
        match = self.repository.match(match_id)
        if match is None:
            raise ApiError("match_not_found", f"Match {match_id} was not found", 404)
        return match

    def _section(self, name, match_id, team_id=None):
        rows = self.repository.section(name, match_id, team_id)
        if name == "teams" and len(rows) != 2:
            raise ServingIntegrityError("Expected two team rows")
        return rows

    def _shootout(self, match):
        attempts = self._section("shootout", match["match_id"])
        if bool(attempts) != match["went_to_penalties"]:
            raise ServingIntegrityError("Shootout coverage differs from overview")
        return {"match_id": match["match_id"], "went_to_penalties": match["went_to_penalties"], "attempts": attempts}

    def section(self, name, match_id, team_id=None):
        match = self.match(match_id)
        if name == "shootout":
            return self._shootout(match)
        return {"match_id": match_id, name: self._section(name, match_id, team_id)}

    def analysis(self, match_id):
        match = self.match(match_id)
        return {"match": match,
                **{name: self._section(name, match_id) for name in ("teams", "players", "shots", "xg_race")},
                "shootout": self._shootout(match)}
