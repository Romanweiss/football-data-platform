"""Published adapter v2 -> explicit local Spark/serving contracts, no I/O."""
from dataclasses import replace
from datetime import date, datetime
from hashlib import sha256
import json

from src.common.checksum import sha256_bytes
from src.providers.identity_registry import IdentityEvidence
from src.providers.models import StageType
from src.providers.openfootball import OpenFootballMapping, RoundBinding, TeamBinding, prepare_openfootball
from src.providers.openfootball_manifest import UCL_2024_25

SOURCE_SHA = "12d6dc343a83ec353efbb89f84186a20d3f5c11aee1f10fdebe2219754d4a1b6"
SEMANTIC = "2d495cfbf4d175d7d404bdf900a2c0651eb8886037b675b92339c5ab32b9307b"
SPARK_VERSION = "4.2.0"
STEPS = ("verify_source", "bronze", "silver", "gold", "clickhouse_load", "quality_gate")


class ETLError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("openfootball_etl:" + code)


def check(condition, code):
    if not condition:
        raise ETLError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=lambda v: v.isoformat()).encode("utf-8")


def mapping(document):
    names = sorted({r[k] for r in document["matches"] for k in ("team1", "team2")})
    check(len(names) == 36 and len(document["matches"]) == 189, "SOURCE_COVERAGE")
    rounds = tuple(RoundBinding(f"League, Matchday {i}", "league", "League phase", StageType.LEAGUE_PHASE,
                               f"md{i}", i) for i in range(1, 9))
    rounds += tuple(RoundBinding(f"Playoffs, Matchday {i}", "knockout-playoffs", "Knockout phase play-offs",
                                StageType.KNOCKOUT, f"leg{i}", i) for i in (1, 2))
    rounds += tuple(RoundBinding("Finals, " + label, "knockout-finals", "Knockout finals", StageType.KNOCKOUT,
                                key, i) for i, (label, key) in enumerate((
        ("Round of 16", "r16"), ("Quarterfinals", "qf"), ("Semifinals", "sf"), ("Final", "final")), 1))
    return OpenFootballMapping("UEFA Champions League 2024/25", tuple(TeamBinding(n,
        "name-v1-" + sha256(n.encode("utf-8")).hexdigest(), n) for n in names), rounds,
        date(2024, 9, 17), date(2025, 5, 31), IdentityEvidence(True, "pet2-pinned-name-round-review-v1"), expected_rows=189)


def proposal(raw, receipt, observed_at):
    # Hash first: no JSON inspection, local artifact or SDK write before this gate.
    check(type(raw) is bytes and len(raw) == 58305 and sha256_bytes(raw) == SOURCE_SHA, "SOURCE_SHA256")
    required = {"repository": UCL_2024_25.repository, "commit": UCL_2024_25.commit,
        "path": UCL_2024_25.path, "content_sha256": SOURCE_SHA, "bytes": 58305, "license_id": "CC0-1.0",
        "license_reference": UCL_2024_25.license_reference}
    check(type(receipt) is dict and all(receipt.get(k) == v for k, v in required.items()), "SOURCE_RECEIPT")
    acquired = datetime.fromisoformat(receipt["acquired_at"])
    manifest = replace(UCL_2024_25, content_sha256=SOURCE_SHA, acquired_at=acquired)
    result = prepare_openfootball(raw, mapping=mapping(json.loads(raw)), manifest=manifest, observed_at=observed_at)
    check(result.semantic_digest == SEMANTIC and len(result.fixtures) == 189 and len(result.participants) == 36
          and len(result.dq.limitations) == 394 and result.dq.fatal_count == 0, "SOURCE_SEMANTICS")
    return result


def cols(names, kind="string", nullable=False):
    return tuple((n, kind, nullable) for n in names.split())


PROVENANCE = cols("batch_id source_provider source_repository source_commit source_path source_sha256 license_id "
                  "coverage result_coverage capabilities_json") + cols("normalized_schema_version", "int")
FIXTURE = (cols("fixture_id competition_id season_id stage_id round_id home_id away_id source_round status "
                "status_origin result_availability score_quality source_score_state") + cols("match_date", "date") +
    cols("source_time", nullable=True) + cols("kickoff_utc", "timestamp", True) +
    cols("source_ht_home source_ht_away source_ft_home source_ft_away source_et_home source_et_away source_p_home source_p_away "
         "regulation_home regulation_away after_extra_time_home after_extra_time_away penalties_home penalties_away "
         "points_home points_away", "int", True) + cols("winner_id", nullable=True) +
    cols("standings_eligible", "bool") + cols("local_revision", "int") + PROVENANCE)
PARTICIPANT = cols("participant_id participant_name external_id competition_id season_id") + PROVENANCE
STAGE = cols("stage_id stage_name stage_kind season_id") + PROVENANCE
ROUND = cols("round_id round_name stage_id") + cols("round_order", "int") + PROVENANCE
QUALITY = cols("fixture_id code severity") + PROVENANCE
COVERAGE = (cols("stage_id round_id stage_name round_name stage_kind") +
    cols("fixture_count reported_result_count unknown_result_count ambiguous_component_count", "int") +
    cols("date_min date_max", "date") + PROVENANCE)
SILVER = {"fixtures": FIXTURE, "participants": PARTICIPANT, "stages": STAGE, "rounds": ROUND, "quality": QUALITY}
GOLD = {"historical_fixtures": FIXTURE + cols("home_name away_name stage_name round_name stage_kind"),
        "competition_participants": PARTICIPANT, "stage_round_coverage": COVERAGE, "source_quality": QUALITY}
KEYS = {"historical_fixtures": ("fixture_id",), "competition_participants": ("participant_id",),
        "stage_round_coverage": ("stage_id", "round_id"), "source_quality": ("fixture_id", "code")}


def row_digest(rows):
    return sha256_bytes(encoded(sorted((encoded(r).decode("utf-8") for r in rows))))


def rows_from_proposal(result, batch_id):
    prov = dict(batch_id=batch_id, source_provider="openfootball", source_repository=result.manifest.repository,
        source_commit=result.manifest.commit, source_path=result.manifest.path,
        source_sha256=result.manifest.content_sha256 or "synthetic", license_id=result.manifest.license_id,
        coverage=result.coverage, result_coverage=result.result_coverage, normalized_schema_version=2,
        capabilities_json=encoded({c.name.value: c.availability.value for c in result.capabilities}).decode())
    output = {name: [] for name in SILVER}
    for f in result.fixtures:
        row = {name: getattr(f, name) for name in ("season_id", "stage_id", "round_id", "home_id", "away_id",
            "source_time", "source_round", "status_origin", "result_availability", "score_quality", "source_score_state",
            "kickoff_utc", "winner_id", "standings_eligible", "points_home", "points_away", "local_revision")}
        row.update(fixture_id=f.id, competition_id=result.competition.id, status=f.status.value,
                   match_date=date.fromisoformat(f.match_date))
        for source in ("ht", "ft", "et", "p"):
            pair = getattr(f, "source_" + source)
            row["source_" + source + "_home"], row["source_" + source + "_away"] = pair if pair is not None else (None, None)
        for name in ("regulation_home", "regulation_away", "after_extra_time_home", "after_extra_time_away",
                     "penalties_home", "penalties_away"):
            row[name] = None
        output["fixtures"].append({**row, **prov})
    output["participants"] = [dict(participant_id=p.id, participant_name=p.name, external_id=p.identity.external_id,
        competition_id=result.competition.id, season_id=result.season.id, **prov) for p in result.participants]
    output["stages"] = [dict(stage_id=s.id, stage_name=s.name, stage_kind=s.kind.value, season_id=s.season_id, **prov)
                        for s in result.stages]
    output["rounds"] = [dict(round_id=r.id, round_name=r.name, round_order=r.order, stage_id=r.stage_id, **prov)
                        for r in result.rounds]
    output["quality"] = [dict(fixture_id=d.fixture_id, code=d.code, severity=d.severity, **prov)
                         for d in result.dq.limitations]
    return output
