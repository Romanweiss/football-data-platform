"""Superset-only semantic contracts. No service IO or analytical transformations."""

from copy import deepcopy

WC_CONTEXT = "competition_id = 43 AND season_id = 106"
IDENTITY_COLUMN = "match_identity"
IDENTITY_SQL = (
    "concat(toString(competition_id), '/', toString(season_id), '/', "
    "toString(match_id), ' | ', match_label)"
)
# A label remains human readable, but numeric full-key identity is part of value.
# Reject absent, inverse, multi-value and multiple filters. Never interpolate raw
# selected text: where_in uses the actual database dialect's literal escaping.
MATCH_GUARD = (
    "{% set selected = get_filters('match_identity') %}"
    "{% if selected|length == 1 and selected[0].get('op') == 'IN' "
    "and selected[0].get('val')|length == 1 %}"
    + IDENTITY_SQL + " IN {{ selected[0].get('val')|where_in }}"
    "{% else %}0 = 1{% endif %}"
)
OVERVIEW = {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 2}
MATCH_CHARTS = {9: 5, 10: 6, 11: 7, 12: 8, 13: 11, 14: 5, 15: 12, 16: 10}
DATASETS = {
    2: "bi_team_match_stats", 3: "bi_player_match_stats",
    5: "bi_match_overview", 6: "bi_match_team_stats",
    7: "bi_match_player_stats", 8: "bi_match_shots",
    10: "bi_match_shot_map", 11: "bi_match_shootout",
    12: "bi_match_xg_race_series",
}
DEFAULT_MATCH = "43/106/3869685 | 2022-12-18 | Argentina - France"


def sql_filter(expression, name):
    return {"expressionType": "SQL", "sqlExpression": expression, "clause": "WHERE",
            "subject": None, "operator": None, "comparator": None, "isExtra": False,
            "isNew": False, "datasourceWarning": False, "filterOptionName": name}


def append_where(existing, expression):
    return f"({existing}) AND ({expression})" if existing else expression


def patch_chart(params, query_context, expression, name):
    """Preserve all original visuals/metrics/analytical filters; idempotent guard."""
    params, query_context = deepcopy(params), deepcopy(query_context)
    filters = params.setdefault("adhoc_filters", [])
    if not any(f.get("sqlExpression") == expression for f in filters):
        filters.append(sql_filter(expression, name))
        for query in query_context.get("queries", []):
            extras = query.setdefault("extras", {})
            extras["where"] = append_where(extras.get("where", ""), expression)
    if "form_data" in query_context:
        query_context["form_data"]["adhoc_filters"] = deepcopy(filters)
    return params, query_context


def patch_match_filter(metadata):
    metadata = deepcopy(metadata)
    filters = metadata["native_filter_configuration"]
    if len(filters) != 1 or filters[0]["name"] != "Match":
        raise ValueError("Unexpected Match Analysis native filter configuration")
    f = filters[0]
    f["targets"] = [{"datasetId": 5, "column": {"name": IDENTITY_COLUMN}}]
    f["controlValues"].update(enableEmptyFilter=True, defaultToFirstItem=False,
                             creatable=False, multiSelect=False, inverseSelection=False)
    f["scope"] = {"rootPath": ["ROOT_ID"], "excluded": []}
    f["chartsInScope"] = list(MATCH_CHARTS)
    f["defaultDataMask"] = {
        "extraFormData": {"filters": [{"col": IDENTITY_COLUMN, "op": "IN", "val": [DEFAULT_MATCH]}]},
        "filterState": {"value": [DEFAULT_MATCH], "label": DEFAULT_MATCH}, "ownState": {},
    }
    f["description"] = "Select one competition/season/match identity. Empty selection shows no data."
    return metadata


def require_contract(charts, datasets, metadata):
    """Read-only exact-config verification; refuse silently degraded safeguards."""
    for cid, did in {**OVERVIEW, **MATCH_CHARTS}.items():
        chart = charts[cid]
        if chart["dataset"] != did:
            raise ValueError(f"Unexpected dataset for chart {cid}")
        expression = WC_CONTEXT if cid in OVERVIEW else MATCH_GUARD
        found = [f for f in chart["params"].get("adhoc_filters", [])
                 if f.get("sqlExpression") == expression and f.get("clause") == "WHERE"]
        if len(found) != 1:
            raise ValueError(f"Missing/duplicate permanent guard: chart {cid}")
        qc = chart["query_context"]
        if not qc.get("queries") or qc.get("form_data", {}).get("adhoc_filters") != chart["params"]["adhoc_filters"]:
            raise ValueError(f"Stale query context: chart {cid}")
        if any(expression not in q.get("extras", {}).get("where", "") for q in qc["queries"]):
            raise ValueError(f"Missing saved query guard: chart {cid}")
    for did, name in DATASETS.items():
        d = datasets[did]
        if d["name"] != name or d["schema"] != "football" or d.get("sql"):
            raise ValueError(f"Unexpected physical dataset: {did}")
        if did in (2, 3):
            if d.get("predicate") != WC_CONTEXT:
                raise ValueError(f"Unscoped WC native options: {did}")
        elif d.get("identity_expression") != IDENTITY_SQL:
            raise ValueError(f"Missing composite identity: {did}")
    f = metadata["native_filter_configuration"][0]
    if (len(metadata["native_filter_configuration"]) != 1
            or f["targets"] != [{"datasetId": 5, "column": {"name": IDENTITY_COLUMN}}]
            or f["scope"] != {"rootPath": ["ROOT_ID"], "excluded": []}
            or set(f.get("chartsInScope", [])) != set(MATCH_CHARTS)
            or f["controlValues"].get("multiSelect")
            or f["controlValues"].get("creatable")
            or f["controlValues"].get("inverseSelection")):
        raise ValueError("Unsafe Match native selector")
