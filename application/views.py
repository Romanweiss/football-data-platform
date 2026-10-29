"""Thin HTTP controllers; all database access lives in repository/services."""
from application.repository import open_repository
from application.services import FootballService
from application.transport import endpoint, heatmap_parameters, parameters, pass_parameters, uint


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
def competitions(request):
    parameters(request)
    with open_repository() as repository:
        return FootballService(repository).competitions()


@endpoint
def seasons(request, competition_id):
    parameters(request)
    competition_id = uint(competition_id, "competition_id", 32)
    with open_repository() as repository:
        return FootballService(repository).seasons(competition_id)


@endpoint
def matches(request, competition_id, season_id):
    parameters(request)
    context = {"competition_id": uint(competition_id, "competition_id", 32), "season_id": uint(season_id, "season_id", 32)}
    with open_repository() as repository:
        return FootballService(repository).matches(context)


@endpoint
def passes(request, competition_id, season_id, match_id):
    filters = pass_parameters(request)
    context = {'competition_id': uint(competition_id, 'competition_id', 32),
               'season_id': uint(season_id, 'season_id', 32)}
    match_id = uint(match_id, 'match_id')
    with open_repository() as repository:
        return FootballService(repository).passes(match_id, context, filters)


@endpoint
def event_heatmap(request, competition_id, season_id, match_id, coordinates=False):
    filters = heatmap_parameters(request)
    context = {'competition_id': uint(competition_id, 'competition_id', 32),
               'season_id': uint(season_id, 'season_id', 32)}
    match_id = uint(match_id, 'match_id')
    with open_repository() as repository:
        return FootballService(repository).event_heatmap(match_id, context, filters, coordinates=coordinates)


@endpoint
def match(request, match_id, section=None, competition_id=None, season_id=None):
    match_id = uint(match_id, "match_id")
    team_id = parameters(request, allow_team=section == "players")
    context = None if competition_id is None else {
        "competition_id": uint(competition_id, "competition_id", 32), "season_id": uint(season_id, "season_id", 32)}
    with open_repository() as repository:
        service = FootballService(repository)
        if section == "analysis":
            return service.analysis(match_id, context)
        if section is not None:
            return service.section(section, match_id, team_id, context)
        return service.match(match_id, context)
