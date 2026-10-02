"""Thin HTTP controllers; all database access lives in repository/services."""
from application.errors import ApiError
from application.repository import open_repository
from application.services import FootballService
from application.transport import endpoint, parameters, uint


@endpoint
def health(request):
    parameters(request)
    return {"status": "ok"}


@endpoint
def clickhouse_health(request):
    parameters(request)
    with open_repository() as repository:
        return repository.health()


@endpoint
def matches(request, competition_id, season_id):
    parameters(request)
    if (uint(competition_id, "competition_id", 32), uint(season_id, "season_id", 32)) != (43, 106):
        raise ApiError("context_not_found", "Only WC2022 context 43/106 is available", 404)
    with open_repository() as repository:
        return {"matches": repository.matches()}


@endpoint
def match(request, match_id, section=None):
    match_id = uint(match_id, "match_id")
    team_id = parameters(request, allow_team=section == "players")
    with open_repository() as repository:
        service = FootballService(repository)
        if section == "analysis":
            return service.analysis(match_id)
        if section is not None:
            return service.section(section, match_id, team_id)
        return service.match(match_id)
