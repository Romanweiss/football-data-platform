"""Manual source-scoped local ETL. No S3/PG credentials, production defaults or downloads."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.openfootball_etl.contract import STEPS, check, encoded
from src.openfootball_etl.pipeline import (
    bronze, build_id, bundle, gold_rows, initialize, read_json, verify_phase, verify_source, write_new, writer,
)
from src.openfootball_etl.clickhouse import IsolatedClickHouse


def run(args):
    check(args.confirm_isolated, "EXPLICIT_ISOLATION_CONFIRMATION_REQUIRED")
    raw, receipt, result = verify_source(args.source, args.receipt)  # Before ALL local writes.
    batch = build_id(result)
    if args.step == "verify_source":
        return {"step": args.step, "batch_id": batch, "source_verified": True}
    # Attest destination before local artifact writes, not just at first INSERT.
    client = IsolatedClickHouse(args.container, args.database)
    store = initialize(args.store)
    report = {"batch_id": batch, "source_sha256": result.manifest.content_sha256,
              "semantic_fingerprint": result.semantic_digest, "counts": {}, "steps": {}}
    steps = STEPS if args.step == "all" else (args.step,)
    with writer(store) as token:
        bronze_path = store / "bronze" / "openfootball" / ("sha256=" + result.manifest.content_sha256)
        for step in steps:
            if step == "verify_source":
                report["steps"][step] = "VERIFIED"
            elif step == "bronze":
                bronze_path, report["steps"][step] = bronze(store, raw, receipt, result)
            elif step in ("silver", "gold"):
                verify_phase(bronze_path)
                # Existing pinned Spark runtime, no network, no production bind mounts.
                args_worker = ["docker", "run", "--rm", "--network", "none", "--hostname", "localhost",
                    "--env", "SPARK_LOCAL_IP=127.0.0.1", "--cpus", "2", "--memory", "4g",
                    "--mount", "type=bind,source=" + str(ROOT) + ",target=/app,readonly",
                    "--mount", "type=bind,source=" + str(store) + ",target=/work",
                    "--workdir", "/app", "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", "/opt/spark/bin/spark-submit",
                    args.spark_image, "/app/scripts/openfootball_spark.py", "--store", "/work", "--bronze",
                    "/work/" + bronze_path.relative_to(store).as_posix(), "--batch", batch, "--phase", step, "--token", token]
                from src.recovery.runtime import run as captured
                output = captured(args_worker, timeout=900)
                check(b"OPENFOOTBALL_PHASE=" in output, "SPARK_PHASE_INCOMPLETE")
                report["steps"][step] = output.decode().split("OPENFOOTBALL_PHASE=")[-1].strip()
                report["counts"][step] = {n: d["rows"] for n, d in verify_phase(bundle(store, batch) / step)["datasets"].items()}
            elif step == "clickhouse_load":
                report["steps"][step], report["counts"]["clickhouse"] = client.publish(gold_rows(store, batch))
            elif step == "quality_gate":
                data = gold_rows(store, batch)
                report["counts"]["clickhouse"] = client.matches(data)
                check(len(data["historical_fixtures"]) == 189 and len(data["competition_participants"]) == 36 and
                      len(data["source_quality"]) == 394, "FINAL_COUNTS")
                # Compare only after a fresh destination readback, even if a receipt already exists.
                load_receipt = {"batch_id": batch, "container_id": client.container, "database": client.database,
                    "counts": report["counts"]["clickhouse"], "source_sha256": result.manifest.content_sha256,
                    "semantic_fingerprint": result.semantic_digest, "status": "VERIFIED"}
                path = store / "loads" / (batch + "-" + client.container[:12] + ".json")
                if path.exists():
                    check(read_json(path) == load_receipt, "LOAD_RECEIPT_CONFLICT")
                else:
                    write_new(path, encoded(load_receipt))
                report["steps"][step] = "VERIFIED"
        report["status"] = "VERIFIED" if "quality_gate" in steps else "PHASE_COMPLETE"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        write_new(store / "runs" / (uuid.uuid4().hex + ".json"), encoded(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "receipt", "store", "container", "database"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--step", choices=("all", *STEPS), default="all")
    parser.add_argument("--spark-image", choices=("football-ci-spark:8a",), default="football-ci-spark:8a")
    parser.add_argument("--confirm-isolated", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args), ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as error:
        # SDK/Docker/Spark exception bodies may contain raw rows or environment details.
        from src.openfootball_etl.contract import ETLError
        print("OPENFOOTBALL_ETL_FAILED:" + (error.code if isinstance(error, ETLError) else type(error).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
