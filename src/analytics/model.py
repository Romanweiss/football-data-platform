"""Read-only validation of the six currently materialized tournament builds."""

from dataclasses import dataclass

from src.analytics.loader import load_record, validate_load_record
from src.analytics.specs import SPECS
from src.analytics.validation import ClickHouseBuildConflictError, ClickHouseIntegrityError, validate_table_schema
from src.common.postgres import find_clickhouse_load, find_silver_build
from src.silver.build_identity import require_sha256


@dataclass(frozen=True)
class ReferenceCheck:
    name: str
    child: str
    parent: str
    keys: tuple[str, ...]
    hard: bool = True
    optional: bool = False
    distinct: bool = False


REFERENCE_CHECKS = (
    ReferenceCheck("squad_team_orphans", "match_squads", "teams", ("team_id",)),
    ReferenceCheck("squad_player_orphans", "match_squads", "players", ("player_id",)),
    ReferenceCheck("event_matches_without_squads", "event_core", "match_squads", ("match_id",), distinct=True),
    ReferenceCheck("pass_events_without_event_core", "pass_events", "event_core", ("match_id", "event_id")),
    ReferenceCheck("shot_events_without_event_core", "shot_events", "event_core", ("match_id", "event_id")),
    *(
        ReferenceCheck(f"{dataset}_{entity}_orphan_rows", dataset, dimension, (f"{entity}_id",),
                       hard=False, optional=(entity == "player"))
        for dataset in ("event_core", "pass_events", "shot_events")
        for entity, dimension in (("team", "teams"), ("player", "players"))
    )
)


def current_builds(client, connection, *, competition_id, season_id, specs=SPECS):
    """Resolve from serving rows, not latest Silver; require matching registrations."""
    builds = {}
    for dataset, spec in specs.items():
        validate_table_schema(client, spec=spec)
        rows, distinct, build_id = client.query(
            f"SELECT count(), uniqExact(silver_build_id), min(toString(silver_build_id)) FROM {spec.target} "
            "WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s",
            parameters={"competition_id": competition_id, "season_id": season_id},
        ).result_rows[0]
        if distinct > 1:
            raise ClickHouseBuildConflictError("Model has multiple snapshots in one dataset/context.")
        if rows <= 0 or distinct != 1:
            raise ClickHouseIntegrityError("All selected datasets must be materialized before model validation.")
        require_sha256(build_id)
        silver = find_silver_build(connection, dataset=dataset, competition_id=competition_id,
                                   season_id=season_id, build_id=build_id)
        if (silver is None or silver["source"] != "statsbomb" or silver["dataset"] != dataset
                or silver["competition_id"] != competition_id or silver["season_id"] != season_id
                or silver["transform_version"] != spec.transform_version or silver["row_count"] != rows):
            raise ClickHouseIntegrityError("Current materialization differs from registered Silver build.")
        record = find_clickhouse_load(connection, clickhouse_database=spec.clickhouse_database,
                                     clickhouse_table=spec.clickhouse_table, silver_build_id=build_id)
        validate_load_record(record, load_record(silver, spec=spec))
        builds[dataset] = build_id
    return builds


def reference_sql(check, *, specs=SPECS):
    def relation(dataset, *, distinct=False, optional=False):
        columns = ", ".join(check.keys)
        sql = (
            f"SELECT {'DISTINCT ' if distinct else ''}{columns} FROM {specs[dataset].target} "
            "WHERE competition_id = %(competition_id)s AND season_id = %(season_id)s "
            f"AND silver_build_id = %({dataset}_build_id)s"
        )
        if optional:
            sql += " AND " + " AND ".join(f"{key} IS NOT NULL" for key in check.keys)
        return sql
    return (
        f"SELECT count() FROM ({relation(check.child, distinct=check.distinct, optional=check.optional)}) AS child "
        f"LEFT ANTI JOIN ({relation(check.parent, distinct=True)}) AS parent "
        "ON " + " AND ".join(f"child.{key} = parent.{key}" for key in check.keys)
    )


def validate_references(client, builds, *, competition_id, season_id, specs=SPECS, report=None):
    parameters = {"competition_id": competition_id, "season_id": season_id,
                  **{dataset + "_build_id": build_id for dataset, build_id in builds.items()}}
    failed = False
    counts = {}
    for check in REFERENCE_CHECKS:
        count = client.query(reference_sql(check, specs=specs), parameters=parameters).result_rows[0][0]
        counts[check.name] = count
        if report is not None:
            report(check.name, count, 0, count == 0, check.hard)
        print(f"{'HARD' if check.hard else 'INFO'} {check.name}: {count}")
        failed |= check.hard and count != 0
    if failed:
        raise ClickHouseIntegrityError("Cross-table hard references failed; no data modified.")
    return counts


def check_model(client, connection, *, competition_id, season_id, specs=SPECS, report=None):
    builds = current_builds(client, connection, competition_id=competition_id, season_id=season_id, specs=specs)
    counts = validate_references(client, builds, competition_id=competition_id, season_id=season_id, specs=specs, report=report)
    # Detect a changed materialization/catalog during the series of read-only queries.
    if builds != current_builds(client, connection, competition_id=competition_id, season_id=season_id, specs=specs):
        raise ClickHouseIntegrityError("Model changed during validation; repeat after writers finish.")
    print("CLICKHOUSE MODEL CHECK PASSED")
    return counts
