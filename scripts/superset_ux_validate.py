"""SELECT-only new-contract checks; the v1 validator remains unchanged."""
from copy import deepcopy
from unittest.mock import patch

from src.analytics.superset_ux import cas_value, check, display_mapping, expected_fields, require_fresh_mapping
from scripts.superset_ux_metadata import IsolatedMetadataStore


def validate_ux(app, session, Chart, Dashboard, Dataset, Column, user, bundle):
    from flask_login import login_user
    from superset.utils.core import QueryStatus

    store = IsolatedMetadataStore(session, Chart, Dataset, Dashboard, Column, bundle)
    for path, _, expected in expected_fields(bundle, "apply"):
        check(cas_value(path, store.read(path)) == cas_value(path, expected), "NEW_CONTRACT_CONFIG")
    after = bundle["candidate-config.json"]
    chart = after["charts"]["9"]
    guard = next(f["sqlExpression"] for f in chart["params"]["adhoc_filters"]
                 if "get_filters" in (f.get("sqlExpression") or ""))
    mapping = display_mapping(guard)
    dataset = session.get(Dataset, 5)
    with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
        frame = dataset.database.get_df(dataset.sql + " ORDER BY competition_id,season_id,match_id LIMIT 1000")
    records = frame.to_dict("records")
    require_fresh_mapping(mapping, records)
    check(len(frame) == 98, "MATCH_COVERAGE")
    check(sum(frame["shootout_status"] == "NOT_APPLICABLE") == 93, "SHOOTOUT_STATUS")
    check(sum(frame["shootout_status"] == "DATA_AVAILABLE") == 5, "SHOOTOUT_STATUS")
    labels = {int(r["match_id"]): r["match_display"] for r in records}

    def execute(table, query, form_data):
        query = deepcopy(query)
        query.setdefault("filter", [])
        with app.test_request_context("/api/v1/chart/data", method="POST", json={
            "queries": [{**query, "filters": query["filter"]}], "form_data": form_data,
        }):
            login_user(user)
            with patch("superset.utils.log.DBEventLogger.log", lambda *a, **kw: None):
                result = table.query(query)
        check(result.status == QueryStatus.SUCCESS, "CHART_QUERY_ERROR")
        return result.df

    evidence = []
    keys = {"columns", "extras", "metrics", "orderby", "row_limit", "row_offset", "series_columns", "series_limit", "order_desc"}
    for mid in (3857256, 3857274, 3869685, 3895052):
        filters = [{"col": "match_display", "op": "IN", "val": [labels[mid]]}]
        for cid in range(9, 17):
            c = after["charts"][str(cid)]
            for saved in c["query_context"]["queries"]:
                query = {k: v for k, v in saved.items() if k in keys}
                query.update(filter=saved.get("filters", []) + filters, is_timeseries=False)
                result = execute(session.get(Dataset, c["dataset"]), query, {**c["params"], "extra_filters": filters})
                if cid == 13:
                    check(len(result) == (8 if mid == 3869685 else 0), "SHOOTOUT_ROWS")
                elif cid == 14:
                    check(len(result) == 1, "SUMMARY_ROWS")
                    check(result["shootout_status"].iloc[0] == ("DATA_AVAILABLE" if mid == 3869685 else "NOT_APPLICABLE"), "SUMMARY_STATUS")
                evidence.append({"match_id": mid, "chart_id": cid, "rows": len(result)})
    negatives = 0
    default = labels[3869685]
    for filters in ([], [{"col": "match_display", "op": "IN", "val": list(labels.values())[:2]}],
                    [{"col": "match_display", "op": "IN", "val": ["x' OR 1=1 --"]}],
                    [{"col": "match_display", "op": "NOT IN", "val": [default]}],
                    [{"col": "match_display", "op": "IN", "val": [default]}] * 2):
        for did in (5, 6, 7, 8, 10, 11, 12):
            query = {"columns": ["competition_id", "season_id", "match_id"], "metrics": ["count"],
                     "filter": filters, "extras": {"where": guard}, "is_timeseries": False, "row_limit": 1000}
            check(execute(session.get(Dataset, did), query, {"extra_filters": filters}).empty, "SCOPE_LEAK")
            negatives += 1
    return {"status": "PASS", "contract": "ux2", "labels": 98, "chart_cases": evidence,
            "negative_cases": negatives, "mapping": "FRESH", "viewer": "authorized synthetic test role"}
