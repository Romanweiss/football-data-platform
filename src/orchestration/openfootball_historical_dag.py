"""Opt-in DAG blueprint, OUTSIDE production dags/. Never auto-registered here."""
from datetime import timedelta

from airflow.sdk import DAG, Param, get_current_context, task
from src.openfootball_etl.contract import STEPS

with DAG(dag_id="openfootball_historical_isolated", schedule=None, catchup=False,
         is_paused_upon_creation=True, max_active_runs=1, max_active_tasks=1,
         params={name: Param(type="string", minLength=1) for name in ("source", "receipt", "store", "container", "database")},
         default_args={"retries": 0, "execution_timeout": timedelta(minutes=30)},
         tags=["openfootball", "isolated", "manual", "source-only"]) as dag:
    @task
    def phase(step):
        import subprocess
        import sys
        from pathlib import Path
        values = get_current_context()["params"]
        script = str(Path(__file__).resolve().parents[2] / "scripts/openfootball_etl.py")
        command = [sys.executable, script, "--step", step, "--confirm-isolated"]
        for name in ("source", "receipt", "store", "container", "database"):
            command += ["--" + name, values[name]]
        result = subprocess.run(command, capture_output=True, timeout=1750)
        if result.returncode:
            raise RuntimeError("OPENFOOTBALL_ISOLATED_PHASE_FAILED")
        return {"step": step, "status": "PASS"}  # No rows/secrets/XCom payloads.

    previous = None
    for name in STEPS:
        current = phase.override(task_id=name)(name)
        if previous is not None:
            previous >> current
        previous = current
