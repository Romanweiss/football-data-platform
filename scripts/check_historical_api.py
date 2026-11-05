"""Opt-in real-Gold HTTP integration; creates only owned ephemeral test resources."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.openfootball_etl.clickhouse import IMAGE, IsolatedClickHouse
from src.openfootball_etl.pipeline import gold_rows, safe_path
from src.recovery import runtime as io

BATCH = "ac5fb3b220d2841ed56b73e1cee6f0e49d8846f97b51fc7767865192ab99e9bc"
PHASE = "arguments"


def main():
    global PHASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-store", required=True)
    parser.add_argument("--confirm-isolated-tests", action="store_true")
    parser.add_argument("--checks-image", choices=("football-ci-checks:8a", "football-9c2f-checks:py310-git-edb3bfd", "football-9c2f-checks:py312-git-edb3bfd"),
                        default="football-ci-checks:8a")
    args = parser.parse_args()
    if not args.confirm_isolated_tests:
        raise ValueError("EXPLICIT_ISOLATED_TEST_CONFIRMATION_REQUIRED")
    # Verified existing Gold only; never run Bronze/Spark or read source credentials.
    data = gold_rows(safe_path(args.gold_store), BATCH)
    suffix = uuid.uuid4().hex[:12]
    name, database = "pet3-openfootball-ch-" + suffix, "pet3_openfootball_api_" + suffix
    container = network = client_container = None
    try:
        PHASE = "create_ephemeral_clickhouse"
        container = io.docker("run", "-d", "--rm", "--pull", "never", "--network", "none", "--name", name,
            "--label", "pet3.scope=openfootball-etl", "--cpus", "2", "--memory", "1536m", "--ulimit", "nofile=262144:262144",
            "--tmpfs", "/var/lib/clickhouse:rw,size=2g", "--tmpfs", "/var/log/clickhouse-server:rw,size=64m", IMAGE).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", container):
            raise ValueError("CREATED_CONTAINER_ID_REQUIRED")
        for _ in range(60):
            try:
                io.docker("exec", container, "clickhouse-client", "--query", "SELECT 1", timeout=5)
                break
            except io.RecoveryError:
                time.sleep(1)
        else:
            raise ValueError("EPHEMERAL_CLICKHOUSE_NOT_READY")
        isolated = IsolatedClickHouse(name, database)
        PHASE = "load_verified_gold"
        isolated.publish(data)
        PHASE = "readonly_identity"
        isolated.command("CREATE USER historical_reader IDENTIFIED BY 'synthetic-pet3b-only' "
                         "SETTINGS readonly=1,max_result_bytes=2097152,max_execution_time=10")
        isolated.command("GRANT SELECT ON " + database + ".* TO historical_reader")
        # Only the new tmpfs server joins a new internal network. Original PET-3A
        # server/production networks/ports/volumes are never changed.
        PHASE = "create_internal_test_network"
        network = io.docker("network", "create", "--internal", "--label", "pet3b.scope=historical-api",
                            "pet3b-historical-" + suffix).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", network):
            raise ValueError("CREATED_NETWORK_ID_REQUIRED")
        PHASE = "attach_internal_test_network"
        io.docker("network", "disconnect", "none", container)
        io.docker("network", "connect", network, container)
        PHASE = "django_contract_tests"
        command = ["docker", "create", "--pull", "never", "--network", network,
            "--name", "pet3b-historical-client-" + suffix,
            "--mount", "type=bind,source=" + str(ROOT / "application") + ",target=/repo/application,readonly",
            "--mount", "type=bind,source=" + str(ROOT / "src") + ",target=/repo/src,readonly",
            "--mount", "type=bind,source=" + str(ROOT / "tests/application") + ",target=/repo/tests/application,readonly",
            "--workdir", "/repo",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PET3B_INTEGRATION_ENABLED=true",
            "--env", "HISTORICAL_API_ENABLED=true", "--env", "HISTORICAL_CLICKHOUSE_HOST=" + name,
            "--env", "HISTORICAL_CLICKHOUSE_DATABASE=" + database,
            "--env", "HISTORICAL_CLICKHOUSE_PASSWORD=synthetic-pet3b-only", args.checks_image,
            "python", "tests/application/integration_historical_api.py"]
        client_container = io.run(command).decode().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", client_container):
            raise ValueError("CREATED_CLIENT_ID_REQUIRED")
        result = subprocess.run(["docker", "start", "--attach", client_container], capture_output=True, timeout=240)
        if result.returncode:
            # Only fixed API codes/status assertions from this owned test process;
            # never dump native driver errors, environment or credentials.
            for line in (result.stdout + result.stderr).decode(errors="replace").splitlines():
                if re.match(r"^(AssertionError:|API failure code=|Ran \d|FAILED|ERROR:|FAIL:)", line):
                    print(line[:400])
            raise ValueError("ISOLATED_HTTP_TESTS_FAILED")
        print(result.stdout.decode())
        print(json.dumps({"integration": "PASS", "loaded_rows": {n: len(r) for n, r in data.items()},
                          "production_connections": 0, "isolated_network": "internal", "temporary_storage": "tmpfs"}))
    finally:
        if client_container and re.fullmatch(r"[0-9a-f]{64}", client_container):
            io.docker("stop", "--time", "10", client_container)
            io.docker("rm", client_container)
        if container and re.fullmatch(r"[0-9a-f]{64}", container):
            io.docker("stop", "--time", "10", container)
        if network and re.fullmatch(r"[0-9a-f]{64}", network):
            io.docker("network", "rm", network)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("HISTORICAL_API_INTEGRATION_FAILED:" + PHASE + ":" + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
