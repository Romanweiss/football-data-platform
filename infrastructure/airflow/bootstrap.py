"""Initialize only new Airflow secrets/log permissions; never rotate/reset state."""
import base64
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import quote

ROOT = Path("/opt/airflow/secrets")
LOGS = Path("/opt/airflow/logs")


def bootstrap():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chown(ROOT, 50000, 0)
    os.chmod(ROOT, 0o750)
    values = {
        "db_password": lambda: secrets.token_urlsafe(40),
        "fernet_key": lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "jwt_secret": lambda: secrets.token_urlsafe(48),
        "api_secret": lambda: secrets.token_urlsafe(48),
        "simple_auth_manager_passwords.json": lambda: json.dumps({"airflow": secrets.token_urlsafe(24)}),
    }
    for name, generate in values.items():
        path = ROOT / name
        if not path.exists():
            with open(path, "x", opener=lambda p, f: os.open(p, f, 0o640)) as out:
                out.write(generate())
            os.chown(path, 50000, 0)
        if not path.stat().st_size:
            raise ValueError("Airflow secret file is empty; manual recovery required")
    logs = LOGS
    logs.mkdir(parents=True, exist_ok=True)
    os.chown(logs, 50000, 0)
    os.chmod(logs, 0o770)
    print("Airflow secret files present; existing values preserved")


def main():
    action = sys.argv[1]
    if action == "init":
        bootstrap()
    elif action == "connection":
        # Only Airflow's *_CMD configuration consumes this stdout; never log it.
        password = (ROOT / "db_password").read_text().strip()
        sys.stdout.write("postgresql+psycopg2://airflow:" + quote(password, safe="")
              + "@football-airflow-db:5432/airflow")
    elif action in ("fernet_key", "jwt_secret", "api_secret"):
        sys.stdout.write((ROOT / action).read_text().strip())
    elif action == "ui-password":
        # Explicit local operator retrieval only; not called during bootstrap/logging.
        print(json.loads((ROOT / "simple_auth_manager_passwords.json").read_text())["airflow"])
    else:
        raise ValueError("Unknown bootstrap action")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Airflow bootstrap failed: exception={type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
