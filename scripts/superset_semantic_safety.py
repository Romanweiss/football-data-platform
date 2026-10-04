"""Stage 6B-F: targeted Superset metadata patch and SELECT-only live validation.

Run in football-superset with repository mounted read-only at /workspace.
Default --audit is read-only; only explicit --apply commits metadata changes.
No credentials/connection URLs/raw exception messages are printed or exported.
"""
import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analytics.superset_safety import (
    DATASETS, DEFAULT_MATCH, IDENTITY_COLUMN, IDENTITY_SQL, MATCH_CHARTS,
    MATCH_GUARD, OVERVIEW, WC_CONTEXT, patch_chart, patch_match_filter, require_contract,
)


def audit(session, Chart, Dashboard, Dataset):
    charts = {}
    for cid in {**OVERVIEW, **MATCH_CHARTS}:
        c = session.get(Chart, cid)
        charts[cid] = {"id": cid, "name": c.slice_name, "dataset": c.datasource_id,
                       "params": json.loads(c.params or "{}"),
                       "query_context": json.loads(c.query_context or "{}")}
    datasets = {}
    for did in DATASETS:
        d = session.get(Dataset, did)
        datasets[did] = {"id": did, "name": d.table_name, "schema": d.schema,
                         "sql": d.sql, "predicate": d.fetch_values_predicate,
                         "columns": [c.column_name for c in d.columns],
                         "identity_expression": next((c.expression for c in d.columns
                                                      if c.column_name == IDENTITY_COLUMN), None)}
    dashboards = {did: {"title": session.get(Dashboard, did).dashboard_title,
                        "metadata": json.loads(session.get(Dashboard, did).json_metadata or "{}")}
                  for did in (1, 2)}
    return charts, datasets, dashboards


def apply(session, Chart, Dashboard, Dataset, Column):
    charts, datasets, dashboards = audit(session, Chart, Dashboard, Dataset)
    if [dashboards[i]["title"] for i in (1, 2)] != ["World Cup 2022 Overview", "Match Analysis"]:
        raise ValueError("Unexpected dashboards")
    for did, name in DATASETS.items():
        d = datasets[did]
        required = {"competition_id", "season_id", "match_id"}
        if did not in (2, 3):
            required.add("match_label")
        if d["name"] != name or d["schema"] != "football" or d["sql"] or not required <= set(d["columns"]):
            raise ValueError(f"Dataset precondition failed: {did}")
    for cid, did in {**OVERVIEW, **MATCH_CHARTS}.items():
        if charts[cid]["dataset"] != did:
            raise ValueError(f"Unexpected chart source: {cid}")
        chart = session.get(Chart, cid)
        expression = WC_CONTEXT if cid in OVERVIEW else MATCH_GUARD
        params, qc = patch_chart(charts[cid]["params"], charts[cid]["query_context"],
                                 expression, f"stage6bf_guard_{cid}")
        chart.params, chart.query_context = json.dumps(params), json.dumps(qc)
    for did in DATASETS:
        d = session.get(Dataset, did)
        if did in (2, 3):
            if d.fetch_values_predicate not in (None, "", WC_CONTEXT):
                raise ValueError("Conflicting native-options predicate")
            d.fetch_values_predicate = WC_CONTEXT
        else:
            column = next((c for c in d.columns if c.column_name == IDENTITY_COLUMN), None)
            if column and column.expression != IDENTITY_SQL:
                raise ValueError("Conflicting identity column")
            if not column:
                d.columns.append(Column(column_name=IDENTITY_COLUMN, expression=IDENTITY_SQL,
                                        type="STRING", groupby=True, filterable=True,
                                        is_dttm=False, verbose_name="Match identity"))
    dashboard = session.get(Dashboard, 2)
    dashboard.json_metadata = json.dumps(patch_match_filter(dashboards[2]["metadata"]))
    session.flush()
    charts, datasets, dashboards = audit(session, Chart, Dashboard, Dataset)
    require_contract(charts, datasets, dashboards[2]["metadata"])
    session.commit()
    print("Superset metadata guards applied atomically")


def validate(app, session, Chart, Dashboard, Dataset, user):
    from flask_login import login_user
    from superset.utils.core import QueryStatus

    charts, datasets, dashboards = audit(session, Chart, Dashboard, Dataset)
    require_contract(charts, datasets, dashboards[2]["metadata"])
    if not app.config["FEATURE_FLAGS"].get("ENABLE_TEMPLATE_PROCESSING"):
        raise ValueError("Template processing disabled")
    evidence = {"overview": [], "overview_native_filters": [], "match_analysis": [], "native_options": []}

    def execute(dataset, query, form_data):
        # Use installed Superset compiler/executor, not a parallel handwritten SQL path.
        query = deepcopy(query)
        query.setdefault("filter", [])
        # Jinja reads the first query's native filters on real chart-data requests.
        # Exercise that path instead of injecting a synthetic g.form_data shortcut.
        request_query = {**query, "filters": query["filter"]}
        with app.test_request_context("/api/v1/chart/data", method="POST",
                                      json={"queries": [request_query], "form_data": form_data}):
            login_user(user)
            # Superset normally INSERTs query audit logs. This validator's SELECT
            # path must not perform (or even attempt) those metadata writes.
            with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
                result = dataset.query(query)
            if result.status != QueryStatus.SUCCESS:
                raise ValueError("Superset generated query failed")
            return result.df, result.query

    for cid, did in OVERVIEW.items():
        c, dataset = charts[cid], session.get(Dataset, did)
        fd = deepcopy(c["params"])
        q = {"columns": ["competition_id", "season_id"], "metrics": ["count"],
             "extras": {"where": WC_CONTEXT}, "is_timeseries": False}
        df, _ = execute(dataset, q, fd)
        if not len(df) or any(tuple(r) != (43, 106) for r in df[["competition_id", "season_id"]].itertuples(index=False, name=None)):
            raise ValueError(f"Foreign context chart {cid}")
        # Execute every stored original chart query, with only the persisted guards.
        for saved in c["query_context"]["queries"]:
            supported = {"columns", "extras", "metrics", "orderby", "row_limit", "row_offset", "series_columns", "series_limit", "order_desc"}
            query = {k: v for k, v in saved.items() if k in supported}
            query["filter"] = saved.get("filters", [])
            query["is_timeseries"] = False
            original_df, _ = execute(dataset, query, fd)
            if cid == 1 and int(original_df.iloc[0, 0]) != 64:
                raise ValueError("Total Matches must equal 64")
        evidence["overview"].append({"chart": cid, "dataset": did, "context": [43, 106], "display_rows": len(original_df)})
        # Attempt to select a Bundesliga team; permanent WC guard must still reject it.
        negative = deepcopy(q)
        negative["filter"] = [{"col": "team_name", "op": "IN", "val": ["Bayer Leverkusen"]}]
        negative_df, _ = execute(dataset, negative, fd)
        if not negative_df.empty:
            raise ValueError(f"Bundesliga entered chart {cid}")
        inside = deepcopy(q)
        inside["filter"] = [
            {"col": "competition_stage_name", "op": "IN", "val": ["Final"]},
            {"col": "team_name", "op": "IN", "val": ["Argentina"]},
            {"col": "match_date", "op": "TEMPORAL_RANGE", "val": "2022-12-18 : 2022-12-19"},
        ]
        inside_df, _ = execute(dataset, inside, fd)
        if inside_df.empty or set(inside_df["competition_id"]) != {43} or set(inside_df["season_id"]) != {106}:
            raise ValueError(f"WC native filters failed: chart {cid}")
        evidence["overview_native_filters"].append({"chart": cid, "stage": "Final", "team": "Argentina", "date": "2022-12-18", "rows": int(inside_df["count"].sum())})
    for did in (2, 3):
        dataset = session.get(Dataset, did)
        q = {"columns": ["competition_id", "season_id", "team_name"], "is_timeseries": False,
             "apply_fetch_values_predicate": True, "row_limit": 10000}
        df, _ = execute(dataset, q, {})
        if set(df["competition_id"]) != {43} or set(df["season_id"]) != {106}:
            raise ValueError("Foreign WC native options")
        evidence["native_options"].append({"dataset": did, "teams": len(set(df["team_name"]))})
    keys = [DEFAULT_MATCH, "9/281/3895052 | 2023-08-19 | Bayer Leverkusen - RB Leipzig"]
    for cid, did in MATCH_CHARTS.items():
        dataset, c = session.get(Dataset, did), charts[cid]
        for values in ([], [keys[0]], [keys[1]], keys, ["43/281/3895052 | 2023-08-19 | Bayer Leverkusen - RB Leipzig"]):
            fd = deepcopy(c["params"])
            extra_filters = [{"col": IDENTITY_COLUMN, "op": "IN", "val": values}] if values else []
            fd["extra_filters"] = extra_filters
            q = {"columns": ["competition_id", "season_id", "match_id"], "metrics": ["count"],
                 "filter": extra_filters, "extras": {"where": MATCH_GUARD}, "is_timeseries": False}
            df, sql = execute(dataset, q, fd)
            expected = {(43, 106, 3869685)} if values == [keys[0]] else {(9, 281, 3895052)} if values == [keys[1]] else set()
            actual = (set() if df.empty else
                      set(df[["competition_id", "season_id", "match_id"]].itertuples(index=False, name=None)))
            # Bundesliga has no shootout: its shootout chart is correctly empty.
            if actual != expected and not (did == 11 and expected == {(9, 281, 3895052)} and not actual):
                raise ValueError(f"Match identity leakage/missing rows: chart {cid}")
            if "{%" in sql or "{{" in sql:
                raise ValueError("Unrendered guard")
            if len(values) == 1 and actual:
                for saved in c["query_context"]["queries"]:
                    query = {k: v for k, v in saved.items() if k in supported}
                    query["filter"] = saved.get("filters", []) + extra_filters
                    query["is_timeseries"] = False
                    execute(dataset, query, fd)
            evidence["match_analysis"].append({"chart": cid, "selection": values, "resolved": sorted(actual), "rows": int(df["count"].sum()) if len(df) else 0})
    # Generic view definitions and two-context physical contents remain unrestricted.
    database = session.get(Dataset, 5).database
    with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
        generic = database.get_df("SELECT competition_id, season_id, count() AS matches FROM football.bi_match_overview GROUP BY competition_id, season_id ORDER BY competition_id")
    if generic.to_dict("records") != [{"competition_id": 9, "season_id": 281, "matches": 34}, {"competition_id": 43, "season_id": 106, "matches": 64}]:
        raise ValueError("Generic BI context coverage changed")
    evidence["generic_matches"] = generic.to_dict("records")
    evidence["generic_views"] = {}
    for name in DATASETS.values():
        with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
            data = database.get_df(f"SELECT competition_id, season_id, count() AS rows FROM football.{name} GROUP BY competition_id, season_id ORDER BY competition_id")
        records = data.to_dict("records")
        contexts = {(r["competition_id"], r["season_id"]) for r in records}
        expected_contexts = {(43, 106)} if name == "bi_match_shootout" else {(43, 106), (9, 281)}
        if contexts != expected_contexts:
            raise ValueError("Generic serving view context coverage changed")
        evidence["generic_views"][name] = records
    with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
        wc = database.get_df("SELECT countDistinct(match_id) AS matches, sum(shot_count) AS shots, sum(pass_attempts) AS passes, sum(shot_xg) AS xg FROM football.bi_team_match_stats WHERE " + WC_CONTEXT)
    row = wc.to_dict("records")[0]
    if row["matches"] != 64 or row["shots"] != 1453 or row["passes"] != 68515 or abs(row["xg"] - 155.8985419302) > 1e-9:
        raise ValueError("WC aggregate changed")
    evidence["wc_totals"] = row
    print(json.dumps(evidence, default=str))
    print("SUPERSET SEMANTIC SAFETY CHECK PASSED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    # Driver/bootstrap logging can include raw connection exceptions. This CLI
    # emits only our safe audit/evidence and exception-class summary.
    logging.disable(logging.CRITICAL)
    from superset.app import create_app, SupersetApp
    # Superset 6 seeds system themes during ordinary app bootstrap. The checker
    # must not write even that unrelated metadata; skip only this startup hook.
    with patch.object(SupersetApp, "sync_config_to_db", lambda self: None):
        app = create_app()
    from superset import db, security_manager
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from sqlalchemy import text

    with app.app_context():
        if not args.apply:
            db.session.execute(text("SET TRANSACTION READ ONLY"))
        if args.apply:
            if not app.config["FEATURE_FLAGS"].get("ENABLE_TEMPLATE_PROCESSING"):
                raise ValueError("Template processing must be enabled before applying guards")
            apply(db.session, Slice, Dashboard, SqlaTable, TableColumn)
        elif args.validate:
            users = security_manager.get_all_users()
            user = next(u for u in users if u.active and any(r.name == "Admin" for r in u.roles))
            validate(app, db.session, Slice, Dashboard, SqlaTable, user)
        else:
            charts, datasets, dashboards = audit(db.session, Slice, Dashboard, SqlaTable)
            print(json.dumps({"charts": charts, "datasets": datasets, "dashboards": dashboards}))
        db.session.rollback()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never expose ORM connection URLs or arbitrary driver messages.
        print(f"Superset safety failed: exception={type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
