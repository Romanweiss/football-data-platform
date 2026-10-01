"""One-shot initialization; no credentials in CLI arguments or captured logs."""

import io
import logging
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout


def admin_settings():
    names = ("SUPERSET_ADMIN_USERNAME", "SUPERSET_ADMIN_PASSWORD", "SUPERSET_ADMIN_EMAIL")
    settings = {name: os.environ.get(name, "") for name in names}
    if any(not value.strip() for value in settings.values()):
        raise ValueError("All SUPERSET_ADMIN_* variables must be nonempty")
    if settings["SUPERSET_ADMIN_PASSWORD"] == settings["SUPERSET_ADMIN_USERNAME"]:
        raise ValueError("Admin password must not equal the username")
    return settings


def ensure_admin(security_manager, settings):
    username = settings["SUPERSET_ADMIN_USERNAME"]
    existing = security_manager.find_user(username=username)
    if existing is not None:
        if not existing.active or not any(role.name == "Admin" for role in existing.roles):
            raise RuntimeError("Existing username is not an active Admin; manual review required")
        # Reinitialization is not a password reset or privilege escalation.
        return "EXISTS"
    role = security_manager.find_role("Admin") or security_manager.add_role("Admin")
    user = security_manager.add_user(username=username, first_name="Superset", last_name="Admin",
        email=settings["SUPERSET_ADMIN_EMAIL"], role=role, password=settings["SUPERSET_ADMIN_PASSWORD"])
    if not user:
        raise RuntimeError("Admin creation failed")
    return "CREATED"


def run_command(*args):
    # Framework failures can include connection strings. Never forward raw output.
    subprocess.run(["superset", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main():
    stage = "configuration"
    try:
        settings = admin_settings()
        # Validate config before migration; loading it is environment-only, no DB IO.
        import superset_config  # noqa: F401

        stage = "db upgrade"
        run_command("db", "upgrade")
        print("Superset metadata migration: OK", flush=True)
        stage = "admin"
        previous = logging.root.manager.disable
        try:
            logging.disable(logging.CRITICAL)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                from superset.app import create_app
                app = create_app()
                with app.app_context():
                    status = ensure_admin(app.appbuilder.sm, settings)
        finally:
            logging.disable(previous)
        print(f"Superset admin: {status}", flush=True)
        stage = "init"
        run_command("init")
        print("Superset initialization: OK", flush=True)
        return 0
    except Exception as error:
        print(f"Superset initialization failed: stage={stage}; exception={type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
