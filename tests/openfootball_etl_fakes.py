"""Artificial source-only fixture, never the acquired OpenFootball payload."""
from dataclasses import replace
from src.common.checksum import sha256_bytes
from src.openfootball_etl.contract import PROVENANCE, rows_from_proposal
from src.providers.openfootball import prepare_openfootball
from test_openfootball import NOW, encode, mapping, payload


def fixture():
    source = payload()
    source["matches"].append({"round": "Synthetic quarter-finals", "date": "2025-04-02",
        "team1": "Amber FC", "team2": "Dune FC", "score": {"ft": [1, 0], "et": [1, 0], "p": [4, 4]}})
    raw = encode(source)
    result = prepare_openfootball(raw, mapping=mapping(), observed_at=NOW)
    result = replace(result, manifest=replace(result.manifest, content_sha256=sha256_bytes(raw), acquired_at=NOW))
    return raw, result


def gold():
    _, result = fixture()
    source = rows_from_proposal(result, "a" * 64)
    participants = {p.id: p.name for p in result.participants}
    stages = {s.id: s for s in result.stages}
    rounds = {r.id: r for r in result.rounds}
    fixtures = [dict(r, home_name=participants[r["home_id"]], away_name=participants[r["away_id"]],
        stage_name=stages[r["stage_id"]].name, stage_kind=stages[r["stage_id"]].kind.value,
        round_name=rounds[r["round_id"]].name) for r in source["fixtures"]]
    coverage = []
    for key in sorted({(r["stage_id"], r["round_id"]) for r in fixtures}):
        rows = [r for r in fixtures if (r["stage_id"], r["round_id"]) == key]
        first = rows[0]
        coverage.append({**{n: first[n] for n, _, _ in PROVENANCE},
            **{n: first[n] for n in ("stage_id", "round_id", "stage_name", "round_name", "stage_kind")},
            "fixture_count": len(rows), "reported_result_count": sum(r["result_availability"] == "REPORTED" for r in rows),
            "unknown_result_count": sum(r["result_availability"] == "MISSING" for r in rows),
            "ambiguous_component_count": sum(r["score_quality"] == "AMBIGUOUS_SOURCE_COMPONENTS" for r in rows),
            "date_min": min(r["match_date"] for r in rows), "date_max": max(r["match_date"] for r in rows)})
    return {"historical_fixtures": fixtures, "competition_participants": source["participants"],
            "stage_round_coverage": coverage, "source_quality": source["quality"]}
