"""Typed source-only HTTP DTOs over one validated immutable historical bundle."""
from collections import Counter
import json
from typing import Literal, TypedDict

from application.historical_repository import not_ready

BASE = "/api/v1/competitions/historical"
SEASON_PATH = BASE + "/uefa-champions-league/2024"
MAX_RESPONSE_BYTES = 1024 * 1024


class ParticipantDTO(TypedDict):
    state: Literal["known"]
    id: str
    name: str


class CompetitionDTO(TypedDict):
    state: Literal["known"]
    id: str
    slug: str
    name: str


class SeasonDTO(TypedDict):
    state: Literal["known"]
    id: str
    start_year: int
    label: str


class ProvenanceDTO(TypedDict):
    provider: str
    repository: str
    path: str
    source_revision: dict
    provider_revision: dict
    source_sha256: str
    batch_id: str
    semantic_fingerprint: str
    license: str
    normalized_schema_version: int


class ScoreDTO(TypedDict):
    state: Literal["known", "unknown", "unsupported"]
    value: list[int] | None


class FixtureDTO(TypedDict):
    id: str
    match_date: str
    kickoff_utc: dict
    home: ParticipantDTO
    away: ParticipantDTO
    stage: dict
    round: dict
    status: str
    status_origin: str
    result_availability: str
    source_reported_score: dict[str, ScoreDTO]
    canonical_regulation_score: ScoreDTO
    score_semantics: dict
    provenance: ProvenanceDTO


def participant(identifier, name) -> ParticipantDTO:
    return {"state": "known", "id": identifier, "name": name}


def provenance(row, semantic) -> ProvenanceDTO:
    return {"provider": row["source_provider"], "repository": row["source_repository"],
        "path": row["source_path"], "source_revision": {"kind": "git_commit", "value": row["source_commit"]},
        "provider_revision": {"state": "unsupported", "value": None}, "source_sha256": row["source_sha256"],
        "batch_id": row["batch_id"], "semantic_fingerprint": semantic, "license": row["license_id"],
        "normalized_schema_version": row["normalized_schema_version"]}


def fixture(row, semantic) -> FixtureDTO:
    scores = {}
    for component in ("ht", "ft", "et", "p"):
        home, away = row["source_" + component + "_home"], row["source_" + component + "_away"]
        scores[component] = {"state": "unknown" if home is None else "known",
                             "value": None if home is None else [home, away]}
    return {"id": row["fixture_id"], "match_date": row["match_date"],
        "kickoff_utc": {"state": "unknown", "value": None},
        "home": participant(row["home_id"], row["home_name"]),
        "away": participant(row["away_id"], row["away_name"]),
        "stage": {"state": "known", "id": row["stage_id"], "name": row["stage_name"], "kind": row["stage_kind"]},
        "round": {"state": "known", "id": row["round_id"], "name": row["round_name"]},
        "status": row["status"], "status_origin": row["status_origin"], "result_availability": row["result_availability"],
        "source_reported_score": scores, "canonical_regulation_score": {"state": "unsupported", "value": None},
        "score_semantics": {"scope": "source_reported_only", "ft_period_verified": False,
            "quality": row["score_quality"], "source_score_state": row["source_score_state"]},
        "provenance": provenance(row, semantic)}


class HistoricalService:
    def __init__(self, repository):
        self.contract = repository.contract
        self.data = repository.load()

    def response(self, section, filters, limit, offset):
        data = self.data
        rows = data["historical_fixtures"]
        first = rows[0]
        source = provenance(first, self.contract.semantic_fingerprint)
        competition: CompetitionDTO = {"state": "known", "id": first["competition_id"], "slug": "uefa-champions-league",
                       "name": "UEFA Champions League"}
        season: SeasonDTO = {"state": "known", "id": first["season_id"], "start_year": 2024, "label": "2024/25"}
        capabilities = json.loads(first["capabilities_json"])
        result = {"competition": competition, "season": season, "provenance": source,
            "coverage": {"source": first["coverage"], "results": first["result_coverage"],
                         "claim": "source_records_only_not_verified_complete_results"},
            "source_capabilities": capabilities,
            "capabilities": {"fixtures": "known", "source_reported_results": "known",
                "verified_regulation_scores": "unsupported", "standings": "unsupported", "events": "unsupported"},
            "freshness": {"mode": "pinned_historical", "last_observed_at": {"state": "unknown", "value": None}}}
        summary = {"fixture_records": len(rows), "participant_records": len(data["competition_participants"]),
            "source_stages": len({r["stage_id"] for r in rows}), "coverage_records": len(data["stage_round_coverage"]),
            "non_fatal_limitations": sum(r["severity"] == "NON_FATAL" for r in data["source_quality"]),
            "source_reported_ft": sum(r["source_ft_home"] is not None for r in rows),
            "unknown_results": sum(r["result_availability"] == "MISSING" for r in rows),
            "ambiguous_components": sum(r["score_quality"] == "AMBIGUOUS_SOURCE_COMPONENTS" for r in rows)}
        if section in ("index", "overview"):
            result["summary"] = summary
            result["links"] = {s: SEASON_PATH + "/" + s for s in ("fixtures", "participants", "coverage", "quality")}
            if section == "index":
                result = {"competitions": [result]}
        else:
            selected = [r for r in rows if self.matches(r, filters)]
            ids = {r["fixture_id"] for r in selected}
            if section == "fixtures":
                items = [fixture(r, self.contract.semantic_fingerprint) for r in
                         sorted(selected, key=lambda r: (r["match_date"], r["fixture_id"]))]
            elif section == "participants":
                items = [participant(r["participant_id"], r["participant_name"]) for r in
                         sorted(data["competition_participants"], key=lambda r: r["participant_id"])
                         if not filters.get("team_id") or r["participant_id"] == filters["team_id"]]
            elif section == "coverage":
                items = [{k: r[k] for k in ("stage_id", "round_id", "stage_name", "round_name", "stage_kind",
                    "fixture_count", "reported_result_count", "unknown_result_count", "ambiguous_component_count", "date_min", "date_max")}
                    for r in sorted(data["stage_round_coverage"], key=lambda r: (r["date_min"], r["stage_id"], r["round_id"]))
                    if all(r[k] == v for k, v in filters.items())]
            else:
                items = [{k: r[k] for k in ("fixture_id", "code", "severity")} for r in
                         sorted(data["source_quality"], key=lambda r: (r["fixture_id"], r["code"])) if r["fixture_id"] in ids]
                result["diagnostic_counts"] = dict(sorted(Counter(r["code"] for r in items).items()))
            page = items[offset:offset + limit]
            result.update({section: page, "filters": filters,
                "pagination": {"offset": offset, "limit": limit, "total": len(items), "returned": len(page),
                               "next_offset": offset + len(page) if offset + len(page) < len(items) else None}})
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESPONSE_BYTES:
            raise not_ready()
        return result

    @staticmethod
    def matches(row, filters):
        return all((value in (row["home_id"], row["away_id"]) if key == "team_id" else row[key] == value)
                   for key, value in filters.items())
