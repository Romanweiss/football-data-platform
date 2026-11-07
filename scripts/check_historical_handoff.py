"""Manual isolated production-handoff rehearsal. Never selects a live write target."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.openfootball_etl.clickhouse import IMAGE
from src.openfootball_etl.contract import ETLError
from src.openfootball_etl.persistent import PersistentPublisher
from src.openfootball_etl.pipeline import gold_rows, safe_path
from src.openfootball_etl.serving_contract import AUTHORIZATION, DATASET, MODE, PINNED, RECORDS
from src.recovery import runtime as io


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-isolated-tests", action="store_true")
    parser.add_argument("--gold-store", required=True)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if not args.confirm_isolated_tests or not re.fullmatch(r"football-api:pet3d-fix-[a-z0-9-]+", args.api_image):
        raise ValueError("EXPLICIT_ISOLATED_REHEARSAL_REQUIRED")
    evidence = safe_path(args.evidence)
    cleanup_path = evidence.with_suffix(".cleanup.json")
    if evidence.exists() or cleanup_path.exists():
        raise ValueError("NO_OVERWRITE_EVIDENCE")
    data = gold_rows(safe_path(args.gold_store), PINNED.batch_id)
    suffix = uuid.uuid4().hex[:12]
    name = "pet3d-fix-ch-" + suffix
    container = client = network = None
    result = {"scope": "ephemeral_only", "production_writes": 0, "created": {}, "status": "FAILED"}
    def expect_rejection(call):
        try:
            call()
        except ETLError as error:
            return error.code
        raise ValueError("EXPECTED_REJECTION")
    try:
        result["no_optin"] = expect_rejection(lambda: PersistentPublisher.production())
        result["wrong_target"] = expect_rejection(lambda: PersistentPublisher.rehearsal(
            "football-clickhouse", expected_namespace="", confirm_isolated=True))
        container = io.docker("run", "-d", "--pull", "never", "--network", "none", "--name", name,
            "--label", "pet3d.scope=historical-rehearsal", "--cpus", "2", "--memory", "1536m",
            "--ulimit", "nofile=262144:262144",
            "--tmpfs", "/var/lib/clickhouse:rw,size=2g", "--tmpfs", "/var/log/clickhouse-server:rw,size=64m", IMAGE).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise ValueError("CREATED_ID_REQUIRED")
        result["created"]["clickhouse"] = container
        for _ in range(40):
            try:
                io.docker("exec", container, "clickhouse-client", "--query", "SELECT 1", timeout=5)
                break
            except io.RecoveryError:
                time.sleep(0.5)
        else:
            raise ValueError("ISOLATED_READINESS_TIMEOUT")
        io.docker("exec", container, "clickhouse-client", "--query", "CREATE DATABASE IF NOT EXISTS football ENGINE=Atomic")
        result["phase"] = "construct_publisher"
        publisher = PersistentPublisher.rehearsal(name, expected_namespace=io.digest(b"[]"), confirm_isolated=True)
        for field, value in (("batch_id", "b" * 64), ("source_sha256", "b" * 64), ("home_name", "wrong")):
            bad = deepcopy(data)
            row = bad["historical_fixtures"][0]
            row[field] = value
            result["wrong_" + field] = expect_rejection(lambda: publisher.publish(bad))
            assert publisher.objects() == []
        def interrupted():
            raise RuntimeError("SYNTHETIC_INTERRUPTION")
        result["phase"] = "interrupted_load"
        try:
            publisher.publish(data, fault=interrupted)
        except RuntimeError:
            pass
        else:
            raise ValueError("INTERRUPTION_NOT_OBSERVED")
        assert publisher.validate(allow_empty=True) == "EMPTY"
        result["partial_load"] = "NOT_PUBLISHED"
        # Retry requires fresh explicitly acknowledged metadata fingerprint.
        publisher = PersistentPublisher.rehearsal(name, expected_namespace=publisher.fingerprint(), confirm_isolated=True)
        result["phase"] = "complete_load"
        receipt = publisher.publish(data)
        assert receipt["status"] == "CREATED" and publisher.validate() == "PINNED"
        result["apply"] = receipt
        result["replay"] = publisher.publish(data)
        assert result["replay"]["status"] == "REUSED"
        assert publisher.query("SELECT count() AS n FROM " + publisher.table(RECORDS)) == [{"n": 633}]
        bad = deepcopy(data)
        bad["historical_fixtures"][0]["source_sha256"] = "0" * 64
        result["failed_update"] = expect_rejection(lambda: publisher.publish(bad))
        assert publisher.validate() == "PINNED"
        result["previous_version_after_failure"] = "RETAINED"
        bad_receipt = {**receipt, "published_uuid": str(uuid.uuid4())}
        result["rollback_conflict"] = expect_rejection(lambda: publisher.rollback(bad_receipt))
        result["phase"] = "rollback"
        result["rollback"] = publisher.rollback(receipt)
        assert publisher.object_uuid(RECORDS) == receipt["previous_uuid"]
        assert publisher.validate(allow_empty=True) == "EMPTY"
        result["old_contract"] = "EMPTY_NOT_READY_RESTORED"
        result["phase"] = "django_setup"
        io.docker("exec", container, "clickhouse-client", "--query",
                  "CREATE USER historical_reader IDENTIFIED BY 'synthetic-handoff-only' SETTINGS readonly=1")
        io.docker("exec", container, "clickhouse-client", "--query", "GRANT SELECT ON football.* TO historical_reader")
        network = io.docker("network", "create", "--internal", "--label", "pet3d.scope=historical-rehearsal",
                            "pet3d-fix-net-" + suffix).decode().strip()
        result["created"]["network"] = network
        io.docker("network", "disconnect", "none", container)
        io.docker("network", "connect", "--alias", "football-clickhouse", network, container)
        env = {"DJANGO_SETTINGS_MODULE": "application.settings", "DJANGO_SECRET_KEY": "synthetic-handoff-only",
            "API_SERVING_MODE": "production", "HISTORICAL_API_ENABLED": "true", "HISTORICAL_SERVING_MODE": MODE,
            "HISTORICAL_PRODUCTION_AUTHORIZATION": AUTHORIZATION, "HISTORICAL_DATASET_ID": DATASET,
            "HISTORICAL_PINNED_BATCH": PINNED.batch_id, "HISTORICAL_EXPECTED_SERVER_UUID": publisher.target.server_uuid,
            "HISTORICAL_CLICKHOUSE_HOST": "football-clickhouse", "HISTORICAL_CLICKHOUSE_DATABASE": "football",
            "HISTORICAL_CLICKHOUSE_USER": "historical_reader", "HISTORICAL_CLICKHOUSE_PASSWORD": "synthetic-handoff-only",
            "PET3D_ISOLATED_HTTP": "true", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/app"}
        flags = [value for key, value in env.items() for value in ("--env", key + "=" + value)]
        client = io.docker("run", "-d", "--pull", "never", "--name", "pet3d-fix-api-" + suffix,
            "--label", "pet3d.scope=historical-rehearsal", "--network", network, *flags,
            "--mount", "type=bind,source=" + str(ROOT / "tests/integration/historical_handoff_http.py") + ",target=/checks/handoff_check.py,readonly",
            "--entrypoint", "sleep", args.api_image, "infinity").decode().strip()
        result["created"]["api"] = client
        result["phase"] = "django_missing"
        result["missing_http"] = json.loads(io.docker("exec", client, "python", "/checks/handoff_check.py", "missing"))
        result["final_apply"] = publisher.publish(data)
        result["phase"] = "django_valid"
        result["valid_http"] = json.loads(io.docker("exec", client, "python", "/checks/handoff_check.py", "valid"))
        result["counts"] = {name: len(rows) for name, rows in data.items()}
        result["status"] = "PASS"
    finally:
        # Preserve non-secret receipts before discarding any ephemeral state.
        receipt_failure = None
        try:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            with evidence.open("x", encoding="utf8") as stream:
                json.dump(result, stream, indent=2)
        except Exception as error:
            # An unavailable evidence filesystem must not bypass cleanup.
            receipt_failure = type(error).__name__
        cleanup = []
        # Only exact IDs returned by this invocation. No prune, force, or volumes.
        for created in (client, container):
            if created and re.fullmatch(r"[0-9a-f]{64}", created):
                try:
                    io.docker("stop", "--time", "15", created)
                    io.docker("rm", created)
                    cleanup.append({"id": created, "removed": True})
                except Exception as error:
                    cleanup.append({"id": created, "removed": False, "error_class": type(error).__name__})
        if network and re.fullmatch(r"[0-9a-f]{64}", network):
            try:
                io.docker("network", "rm", network)
                cleanup.append({"id": network, "removed": True, "kind": "network"})
            except Exception as error:
                cleanup.append({"id": network, "removed": False, "error_class": type(error).__name__})
        try:
            with cleanup_path.open("x", encoding="utf8") as stream:
                json.dump(cleanup, stream, indent=2)
        except Exception as error:
            receipt_failure = type(error).__name__
        if not all(item["removed"] for item in cleanup):
            raise RuntimeError("OWNED_RESOURCE_CLEANUP_INCOMPLETE")
        if receipt_failure:
            raise RuntimeError("EVIDENCE_PERSISTENCE_FAILED_AFTER_CLEANUP")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never expose SQL, credential-bearing SDK exception bodies, or raw rows.
        print("HISTORICAL_HANDOFF_REHEARSAL_FAILED:" + (error.code if isinstance(error, ETLError) else type(error).__name__), file=sys.stderr)
        raise SystemExit(1) from None
