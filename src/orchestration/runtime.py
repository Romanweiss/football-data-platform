"""Runtime-only CLI adapter. PostgreSQL, not XCom, remains build authority."""
import json
import os
from pathlib import Path
import re
import subprocess

from src.orchestration.commands import (
    GOLD, SILVER, build_command, context, context_args, bronze_args, digest,
    load_command, parse_result,
)

ROOT = Path(__file__).resolve().parents[2]


def run_cli(argv, *, spark=False):
    executable = "/opt/spark/bin/spark-submit" if spark else "/usr/bin/python3"
    command = [executable, str(ROOT / "scripts" / argv[0]), *argv[1:]]
    # Retain subprocess bytes privately: never pass through arbitrary JVM/driver
    # output to Airflow logs or XCom. Emit only parsed, allowlisted metadata.
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=3600)
    if result.returncode:
        classes = re.findall(r"exception[=:]([A-Za-z][A-Za-z0-9_]{0,100})", result.stderr)
        raise RuntimeError(f"CLI failed: script={argv[0]} exit={result.returncode} exception={classes[-1] if classes else 'JobFailure'}")
    return result.stdout, result.stderr


def catalog(c):
    from src.common.postgres import create_postgres_connection
    from scripts.inspect_context_catalog import inspect_catalog
    from src.statsbomb.context import CATALOG_URL
    with create_postgres_connection() as connection:
        inventory = inspect_catalog(connection, c)
        with connection.cursor() as cursor:
            cursor.execute("SELECT sha256 FROM metadata.ingestion_objects WHERE source=%s AND source_url IN (%s,%s)",
                           ("statsbomb", CATALOG_URL, CATALOG_URL.replace("/hudl/", "/statsbomb/")))
            inventory["shared_catalog_shas"] = [row[0] for row in cursor.fetchall()]
        return inventory


def expected_builds(inventory):
    expected = {}
    for layer, datasets in (("silver", SILVER), ("gold", GOLD)):
        for dataset in datasets:
            version = dataset + ("_v2" if layer == "gold" and dataset != "match_results" else "_v1")
            rows = [r for r in inventory[layer] if r["dataset"] == dataset and r["transform_version"] == version]
            if len(rows) > 1:
                raise ValueError("Ambiguous existing context builds; no latest fallback")
            if rows:
                expected[layer + "/" + dataset] = digest(rows[0]["build_id"])
    return expected


def registered(layer, dataset, c, build_id):
    from src.common.postgres import create_postgres_connection, find_gold_build, find_silver_build
    with create_postgres_connection() as connection:
        row = (find_silver_build if layer == "silver" else find_gold_build)(
            connection, dataset=dataset, **c, build_id=digest(build_id))
    if row is None:
        raise ValueError("CLI result is not registered in authoritative catalog")
    return row


def execute(request):
    step = request["step"]
    c = context(request["context"])
    snapshot = request.get("snapshot") or c
    if context(snapshot) != c:
        raise ValueError("Orchestration context mismatch")
    result = {**c, "step": step}
    if step == "source":
        stdout, stderr = run_cli(["check_statsbomb_source.py", *context_args(c)])
        source = json.loads(stdout)
        if context(source) != c:
            raise ValueError("Source context mismatch")
        inventory = catalog(c)
        parent = digest(source["matches_sha256"])
        # Replaying a completed context must never silently publish a changed
        # source snapshot. A deliberate source upgrade needs a separate review.
        if any(r["sha256"] != parent for r in inventory["parents"]):
            raise ValueError("Source parent changed relative to existing catalog")
        if any(sha != source["catalog_sha256"] for sha in inventory.get("shared_catalog_shas", [])):
            raise ValueError("Shared source catalog changed; deliberate source upgrade requires review")
        return {**result, "parent_sha256": parent, "catalog_sha256": digest(source["catalog_sha256"]),
                "match_count": source["match_count"], "expected_builds": expected_builds(inventory),
                "transport_retries": stderr.count("Public source request retry:"), "status": "CHECKED"}
    if step == "parent":
        stdout, stderr = run_cli(["ingest_statsbomb_bronze.py", *context_args(c)])
        from src.common.postgres import create_postgres_connection, find_matches_parent
        with create_postgres_connection() as connection:
            find_matches_parent(connection, **c, sha256=digest(snapshot["parent_sha256"]))
    elif step == "children":
        stdout, stderr = run_cli(["ingest_statsbomb_match_data.py", *context_args(c),
                                 "--parent-sha256", digest(snapshot["parent_sha256"])])
    elif step == "freeze":
        inventory = catalog(c)
        if expected_builds(inventory) != snapshot["expected_builds"]:
            raise ValueError("Build catalog changed while freezing Bronze")
        return {**snapshot, "step": step, "bronze_max_id": inventory["bronze_max_id"],
                "transport_retries": 0, "status": "FROZEN"}
    elif step == "bronze_validate":
        from src.dq.orchestration import validate
        bronze_args(snapshot)  # Preserve exact frozen-boundary argument validation.
        return {**result, 'status': 'SUCCESS', **validate(request, 'bronze',
                parent_sha256=snapshot['parent_sha256'], bronze_max_id=snapshot['bronze_max_id'])}
    elif step in ("build_check", "publish", "artifact_validate", "load_preflight", "load"):
        layer, dataset = request["layer"], request["dataset"]
        upstream = request.get("upstream") or {}
        for item in upstream.values():
            if context(item) != c:
                raise ValueError("Upstream build context mismatch")
        if step in ("build_check", "publish"):
            argv = build_command(layer, dataset, snapshot, upstream, step == "build_check")
            stdout, stderr = run_cli(argv, spark=True)
        else:
            build = request["build"]
            if context(build) != c or build["dataset"] != dataset or build["layer"] != layer:
                raise ValueError("Loader build identity/context mismatch")
            argv = load_command(layer, dataset, snapshot, build, upstream, step != "load")
            if step == 'artifact_validate':
                from src.dq.orchestration import validate
                expected = snapshot['expected_builds'].get(layer + '/' + dataset)
                if expected is not None and build['build_id'] != expected:
                    raise ValueError('Existing deterministic build identity changed; STOP')
                quality = validate(request, 'artifact', layer=layer, dataset=dataset, build_id=build['build_id'],
                                   expected_inputs={name:item['build_id'] for name,item in upstream.items()})
                row = registered(layer, dataset, c, build['build_id'])
                return {**result, 'layer':layer, 'dataset':dataset, 'build_id':build['build_id'],
                        'row_count':row['row_count'], 'status':'CHECKED', **quality}
            stdout, stderr = run_cli(argv)
        parsed = parse_result(stdout + "\n" + stderr, require_build=True)
        expected = snapshot["expected_builds"].get(layer + "/" + dataset)
        if expected is not None and parsed["build_id"] != expected:
            raise ValueError("Existing deterministic build identity changed; STOP")
        if request.get("build") and parsed["build_id"] != request["build"]["build_id"]:
            raise ValueError("Check/publish/load build identity mismatch")
        if step != "build_check":
            row = registered(layer, dataset, c, parsed["build_id"])
            parsed["row_count"] = row["row_count"]
        if step in ("publish", "load") and ("status" not in parsed or "catalog" not in parsed):
            raise ValueError("Missing publication/load completion status")
        return {**result, "layer": layer, "dataset": dataset, **parsed}
    elif step in ("serving_model", "serving_gold", "serving_results", "application"):
        from src.dq.orchestration import validate
        suite = {'serving_model':'references','serving_gold':'gold','serving_results':'results','application':'api'}[step]
        return {**result, 'status':'SUCCESS', **validate(request, suite)}
    else:
        raise ValueError("Unknown orchestration step")
    return {**result, "status": "SUCCESS", **parse_result(stdout + "\n" + stderr)}


def invoke(request):
    """Airflow venv entrypoint; project libraries run in the proven interpreter."""
    # Do not forward Airflow JWT/task tokens or metadata-DB config to data jobs.
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIRFLOW")}
    result = subprocess.run(["/usr/bin/python3", str(ROOT / "scripts/airflow_pipeline_step.py")],
                            input=json.dumps(request), text=True, capture_output=True,
                            cwd=ROOT, env=env, timeout=3700)
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError("Project adapter returned no safe result") from None
    if result.returncode:
        raise RuntimeError("Project step failed: " + json.dumps(payload)) from None
    if len(result.stdout) > 16000:
        raise ValueError("Unexpected large XCom result")
    print(json.dumps(payload, sort_keys=True), flush=True)
    return payload
