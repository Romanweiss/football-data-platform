"""Small historical controllers; separate opt-in connection, existing HTTP errors."""
import re
from application.errors import ApiError
from application.historical import HistoricalService
from application.historical_repository import open_historical_repository
from application.transport import endpoint


def query(request, section):
    allowed = {"fixtures": {"team_id", "stage_id", "round_id"}, "participants": {"team_id"},
               "coverage": {"stage_id", "round_id"}, "quality": {"team_id", "stage_id", "round_id"}}.get(section, set())
    names = allowed | ({"limit", "offset"} if section not in ("overview", "index") else set())
    if set(request.GET) - names or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ApiError("invalid_request", "Unsupported or repeated query parameter", 400)
    filters = {}
    for name in sorted(allowed & set(request.GET)):
        kind = {"team_id": "participant", "stage_id": "stage", "round_id": "round"}[name]
        if not re.fullmatch("uefa:" + kind + r":[0-9a-f]{64}", request.GET[name]):
            raise ApiError("invalid_request", "Invalid historical filter identity", 400)
        filters[name] = request.GET[name]
    limit, offset = request.GET.get("limit", "50"), request.GET.get("offset", "0")
    if not re.fullmatch(r"[0-9]{1,3}", limit) or not 1 <= int(limit) <= 100:
        raise ApiError("invalid_request", "limit must be between 1 and 100", 400)
    if not re.fullmatch(r"[0-9]{1,5}", offset) or int(offset) > 10000:
        raise ApiError("invalid_request", "offset must be between 0 and 10000", 400)
    return filters, int(limit), int(offset)


@endpoint
def historical(request, competition_slug=None, start_year=None, section="overview"):
    if start_year is not None and not re.fullmatch(r"[0-9]{4}", start_year):
        raise ApiError("invalid_request", "Invalid season start year", 400)
    if competition_slug is not None and (competition_slug != "uefa-champions-league" or start_year != "2024"):
        raise ApiError("historical_not_found", "Historical competition/season was not found", 404)
    filters, limit, offset = query(request, section)
    with open_historical_repository() as repository:
        return HistoricalService(repository).response(section, filters, limit, offset)
