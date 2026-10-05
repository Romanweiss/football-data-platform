"""Pure, import-safe allowlisted CLI planning and small-result parsing."""
import re

SILVER = {
    "teams": ("publish_silver_lineup_domains.py", "--dataset", "teams"),
    "players": ("publish_silver_lineup_domains.py", "--dataset", "players"),
    "match_squads": ("publish_silver_lineup_domains.py", "--dataset", "match-squads"),
    "event_core": ("publish_silver_event_core.py",),
    "pass_events": ("publish_silver_event_domains.py", "--dataset", "passes"),
    "shot_events": ("publish_silver_event_domains.py", "--dataset", "shots"),
    "matches": ("publish_silver_matches.py",),
}
SILVER_CLI = dict(teams="teams", players="players", match_squads="match-squads",
                  event_core="event-core", pass_events="passes", shot_events="shots", matches="matches")
GOLD = {
    "team_match_stats": ("event_core", "match_squads", "pass_events", "shot_events"),
    "player_match_stats": ("event_core", "match_squads", "pass_events", "shot_events"),
    "match_results": ("event_core", "matches", "shot_events"),
}


def context(value):
    result = {k: value.get(k) for k in ("competition_id", "season_id")}
    if any(type(v) is not int or not 0 < v < 2**32 for v in result.values()):
        raise ValueError("competition_id and season_id must be positive UInt32 integers")
    return result


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected exact lowercase SHA-256 identity")
    return value


def context_args(value):
    c = context(value)
    return ["--competition-id", str(c["competition_id"]), "--season-id", str(c["season_id"])]


def bronze_args(snapshot):
    boundary = snapshot["bronze_max_id"]
    if type(boundary) is not int or boundary <= 0:
        raise ValueError("Missing frozen Bronze boundary")
    return context_args(snapshot) + ["--parent-sha256", digest(snapshot["parent_sha256"]), "--bronze-max-id", str(boundary)]


def pins(dataset, builds):
    required = GOLD[dataset]
    if set(builds) != set(required):
        raise ValueError("Exact required upstream builds must be supplied")
    result = []
    for name in required:
        result += ["--silver-build", name + "=" + digest(builds[name]["build_id"])]
    return result


def build_command(layer, dataset, snapshot, upstream, check_only):
    if layer == "silver":
        argv = list(SILVER[dataset])
        if dataset == "matches":
            argv += context_args(snapshot) + ["--parent-sha256", digest(snapshot["parent_sha256"]),
                      "--teams-build-id", digest(upstream["teams"]["build_id"])]
        else:
            argv += bronze_args(snapshot)
    elif layer == "gold":
        version = dataset + ("_v1" if dataset == "match_results" else "_v2")
        argv = ["build_gold_match_stats.py", "--dataset", dataset.replace("_", "-"),
                "--transform-version", version] + context_args(snapshot) + pins(dataset, upstream)
    else:
        raise ValueError("Unknown build layer")
    return argv + (["--check-only"] if check_only else [])


def load_command(layer, dataset, snapshot, build, upstream, check_only):
    if layer == "silver":
        argv = ["load_clickhouse_silver.py", "--dataset", SILVER_CLI[dataset]]
    elif layer == "gold" and dataset in GOLD:
        argv = ["load_clickhouse_gold.py", "--dataset", dataset.replace("_", "-"),
                "--transform-version", "v1" if dataset == "match_results" else "v2"]
        if dataset != "match_results":
            argv += pins(dataset, upstream)
    else:
        raise ValueError("Unknown load target")
    return argv + context_args(snapshot) + ["--build-id", digest(build["build_id"])] + (["--check-only"] if check_only else [])


def parse_result(output, *, require_build=False):
    """Do not forward arbitrary subprocess output (including JVM/driver errors)."""
    result = {}
    builds = re.findall(r"^(?:Build ID|Silver build ID|Gold build ID): ([0-9a-f]{64})$", output, re.M)
    if require_build and not builds or len(set(builds)) > 1:
        raise ValueError("Missing or conflicting CLI build identity")
    if builds:
        result["build_id"] = digest(builds[0])
    for field, label in (("status", "Output status"), ("catalog", "Catalog")):
        values = re.findall(r"^" + label + r": ([A-Z_ /]+)$", output, re.M)
        if values:
            allowed = {"CREATED", "UNCHANGED / ALREADY_BUILT", "UNCHANGED / ALREADY_LOADED", "LOADED", "REGISTERED", "ALREADY_REGISTERED"}
            if values[-1] not in allowed:
                raise ValueError("Unexpected CLI status")
            result[field] = values[-1]
    for field, labels in {
        "row_count": "Output rows|Rows|Events read|Expected rows",
        "downloaded": "Objects downloaded|Downloaded", "uploaded": "Objects uploaded|Uploaded",
        "reused": "Objects unchanged|Unchanged", "registered": "Objects registered|Registered",
        "already_registered": "Objects already registered|Already registered",
    }.items():
        values = re.findall(r"^(?:" + labels + r"): ([0-9]+)$", output, re.M)
        if values:
            result[field] = int(values[-1])
    result["transport_retries"] = output.count("Public source request retry:")
    if "CHECK ONLY - " in output:
        result["status"] = "CHECKED"
    return result
