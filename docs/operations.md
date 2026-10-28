# Operations and safety

[Documentation index](README.md) · [Architecture](architecture.md) · [Development](development.md)

This is a navigation/safety guide, not an automated deployment or data-change plan.
Local production-like delivery is not public hosting. Do not expose the existing
application/database ports externally without separate TLS/authentication/security design.

## Service ownership and runbooks

| Component | Purpose and default local entrypoint | Operator runbook |
| --- | --- | --- |
| Development API/web | Django/Vite; `:18000` / `:15173` | [Development](development.md) |
| Production-like API/web | internal Gunicorn; Nginx `:18090` | [Stage 8B](stage8b.md) |
| Platform PostgreSQL | catalogs, DQ and incidents; host `:15436` | [DQ contract](stage7a.md), [recovery](stage8c.md) |
| ClickHouse | SELECT-only application serving; host HTTP `:18124`, native `:19001` | [ETL/load contracts](stage6b1.md) |
| Airflow | optional orchestration UI `:18080` | [Architecture](stage6c1.md), [operations/replay](stage6c2.md) |
| Superset | optional BI `:18088` | [Historical setup](archive/README-legacy.md#stage-4a---superset-bi-foundation), [context safety](stage6b-superset-safety.md) |
| Grafana | optional DQ viewer `:13000` | [Stage 7B](stage7b.md) |

Ports are defaults, not an assertion that services are running. Host ports are for
host clients; containers use service DNS/container ports (for example ClickHouse
`football-clickhouse:8123`). Do not replace internal addresses with host localhost.
App deployment/restart is separate from database/ETL operations; Pass Map is not
yet deployed at production origin `18090`.

## Configuration and secrets

- `.env.example` is public placeholders only. Keep working `.env`, optional `.passes`
  and `keys.txt` private and excluded from Git and Docker build context.
- Compose does **not** automatically read `.passes`. Where used, the operator's
  explicit env-file order is documented in [Stage 8B](stage8b.md#powershell-operations).
  Changed env files do not silently update already running containers.
- Do not print resolved Compose configuration, Docker Config.Env, passwords,
  connection URIs, vault contents, recovery material or raw SDK error text.
  Use `docker compose ... config -q` for static configuration checks.
- API uses the existing SELECT-only reader; browser builds contain no infrastructure
  secrets. A healthy API container does not prove credential or data readiness.
- Preserve current TLS/CA configuration; never bypass verification. Python/Java/
  ClickHouse trust stores have distinct responsibilities.
- Environment changes do not reset initialized database users. Do not repair an
  authentication failure by deleting volumes, resetting passwords or granting access
  before diagnosing the actual runtime source/configuration mismatch.

## Data changes and initialization

Init scripts under `infrastructure/*/init` run only for a new empty volume.
They are not a schema upgrader for an existing database. Migrations, build
publication and loads require explicit operator review, exact context/build pins
and current runbooks. ClickHouse migration 011 is an explicit rollback, not a
normal step to run between 010 and 012.

For initial Bronze/Silver/Gold design details use the [archived README map](archive/README.md);
for context-explicit current invocations use [Stage 6B-1](stage6b1.md) with
[onboarding checkpoints](stage6b2.md). Validate prerequisites and pin values at
execution time; historical IDs/commands are evidence, not defaults for a new run.
No new ingestion, schema migration or source replacement is implied by this guide.

## Scheduling and data quality

The full context pipeline remains manual. Optional weekly discovery and DQ DAGs
are paused on creation; they do not automatically run ingestion or rebuild history.
Source discovery recommends review, while registered-context DQ checks persist
observations. Grafana reads DQ history; platform policy owns incidents. Alerts
default off and the shipped transport is local/log.

See [DQ taxonomy and execution storage](stage7a.md), [Grafana](stage7b.md) and
[scheduling/alerts](stage7c.md). Some validator commands append DQ history even
when analytical/source data access is read-only; inspect the command boundary.

## Recovery status and custody

**Isolated local S3 recovery: VERIFIED. Overall Stage 8C: PARTIAL.**
One current-object encrypted S3 generation on an independent USB disk and one
offline isolated local restore passed: 315 source objects, 356383409 plaintext
bytes, 315/315 SHA-256 readback, 22 empty objects, mapping and metadata checks.
The restore used an operator-attested PHONE key route without source services
or the original local key file. This is not proof of cold vault/MFA recovery.

The [closure runbook](stage8c-r2-4a2-4c.md) is authoritative for the recorded session,
retention proposals, safe manual USB removal, future plaintext cleanup and remaining
gates. Its media letters/disk numbers describe an inspection, not permanent identities.
Do not read keys or replay backup/restore simply to check documentation.

Keep encryption keys separate from archives and independently recoverable. The
recorded restore required a narrowly scoped post-restore per-file protected-DACL
adjustment: automatic per-file protection by the engine is **not proven**.
Future drills must audit this explicitly and obtain approval for any repair.

Still NOT VERIFIED: offsite copy/custody, fresh-machine bootstrap/old owner SID
handling, remote S3 restore, all runtime-secret recovery, cold vault/MFA recovery
and complete machine-loss recovery. Historical S3 versions are not backed up;
403 for versioning/Object Lock is UNKNOWN/ACCESS DENIED, not proof of disabled features.
No guaranteed RPO/RTO/SLA is established. Local restored plaintext is sensitive
and is not another independent backup.

## Before any operator action

1. Identify exact project, service, data context/build or recovery session.
2. Read the current runbook and distinguish historical evidence from current prerequisites.
3. Keep secrets out of command arguments, output, screenshots, Git and CI artifacts.
4. Obtain explicit approval for writes, deployment, backup/restore, cleanup or media removal.
5. Stop on failed integrity/identity/ACL checks; do not broaden permissions or overwrite data.
6. Use targeted, non-destructive operations; never use volume deletion/pruning as setup.
