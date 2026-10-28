"""Application orchestration only; the ClickHouse views own all metric semantics."""
from application.errors import ApiError, ServingIntegrityError


class FootballService:
    def __init__(self, repository):
        self.repository = repository

    def competitions(self):
        return {"competitions": self.repository.competitions()}

    def seasons(self, competition_id):
        rows = self.repository.seasons(competition_id)
        if not rows:
            raise ApiError("competition_not_found", "Competition was not found", 404)
        return {"seasons": rows}

    def matches(self, context):
        rows = self.repository.matches(context)
        if not rows:
            self.repository.require_context(context)
        return {"matches": rows}

    def match(self, match_id, context=None):
        match = self.repository.match(match_id) if context is None else self.repository.match(match_id, context)
        if match is None:
            raise ApiError("match_not_found", f"Match {match_id} was not found", 404)
        return match

    def _section(self, name, match, team_id=None):
        context = {key: match[key] for key in ("competition_id", "season_id")}
        rows = self.repository.section(name, match["match_id"], team_id, context=context)
        if name == "teams" and len(rows) != 2:
            raise ServingIntegrityError("Expected two team rows")
        return rows

    def _shootout(self, match):
        attempts = self._section("shootout", match)
        if bool(attempts) != match["went_to_penalties"]:
            raise ServingIntegrityError("Shootout coverage differs from overview")
        return {"match_id": match["match_id"], "went_to_penalties": match["went_to_penalties"], "attempts": attempts}

    def section(self, name, match_id, team_id=None, context=None):
        match = self.match(match_id, context)
        if name == "shootout":
            return self._shootout(match)
        return {"match_id": match_id, name: self._section(name, match, team_id)}

    def analysis(self, match_id, context=None):
        match = self.match(match_id, context)
        return {"match": match,
                **{name: self._section(name, match) for name in ("teams", "players", "shots", "xg_race")},
                "shootout": self._shootout(match)}

    def passes(self, match_id, context, filters):
        from application.passes import read_passes

        self.match(match_id, context)  # Wrong context/unknown match never exposes child rows.
        return read_passes(self.repository, context=context, match_id=match_id, filters=filters)
