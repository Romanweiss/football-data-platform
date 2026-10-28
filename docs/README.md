# Documentation

[English product overview](../README.md) · [Обзор на русском](../README.ru.md)

Start with the topic guides below. Stage reports preserve decisions, implementation
checkpoints and measured evidence; their earlier STOP/NOT EXECUTED paragraphs are
historical unless explicitly identified as the current status. Do not run an old
command just because it remains in an archived report.

## Topic guides

| Question | Guide |
| --- | --- |
| What exists and how does data reach Match Lab? | [Architecture](architecture.md) |
| How do I prepare development and run safe tests? | [Development](development.md) |
| Which matches, fields and usage rights are available? | [Data sources and attribution](data-sources.md) |
| How do I operate services, monitoring and recovery safely? | [Operations](operations.md) |
| Where did the old README material go? | [Archive and migration map](archive/README.md) |

## Application and analytics

- [Pass Map API, interactions, counts and limits](stage9b1.md) — published Stage 9B.1;
  production origin has not been updated for it.
- [Canonical competition/season/match scope](stage6a.md),
  [two-context onboarding evidence](stage6b2.md#final-acceptance-real-coexistence).
- [API foundation](stage5a.md), [React and SVG foundations](stage5b.md),
  [search, shared shot interaction and localization](stage5c.md).
- [Result/shootout audit](stage4b.md), [v2 serving cutover](stage4c.md),
  [Match Analysis views](stage4d.md), [visual analytics and Superset charts](stage4e.md).
- [Superset multi-context safety](stage6b-superset-safety.md) — do not mix contexts
  in historical World Cup dashboards.

## Pipeline and observability

- [Context-explicit ETL and loader runbook](stage6b1.md) supersedes the old
  WC-only parent/source assumptions; [real onboarding](stage6b2.md) records exact pins.
- [Airflow architecture and manual DAG](stage6c1.md),
  [replay, failure inspection and operations](stage6c2.md).
- [Persistent DQ contract and validator inventory](stage7a.md),
  [DQ inventory](stage7a-inventory.md), [Grafana](stage7b.md),
  [conservative scheduling and platform alerts](stage7c.md).
- [CI architecture and local equivalents](stage8a.md),
  [local production-like application delivery](stage8b.md).

## Recovery — current status first

Current-object encrypted S3 backup and isolated offline local restore are
**VERIFIED** for the recorded generation. Overall **Stage 8C is PARTIAL**;
fresh-machine, offsite, remote S3 and cold vault/MFA recovery are not verified.

- [Recovery overview](stage8c.md) and
  [latest evidence, USB custody, retention and closure gates](stage8c-r2-4a2-4c.md).
- [Offline restore engine and safety boundary](stage8c-r2-4a2-4a.md).
- Archive/workflow/adapter/operator design:
  [R2.3-A](stage8c-r2-3a.md), [B](stage8c-r2-3b.md),
  [C](stage8c-r2-3c.md), [D](stage8c-r2-3d.md),
  [publication review](stage8c-r2-3-publication.md).
- Windows and manual escrow preparation:
  [A1](stage8c-r2-4a1.md), [A1.5](stage8c-r2-4a1-5.md),
  [A1.6](stage8c-r2-4a1-6.md), [A1.7](stage8c-r2-4a1-7.md),
  [publication review](stage8c-r2-4a1-publication.md).
- Production-key readiness: [A2.1](stage8c-r2-4a2-1.md),
  [A2.2](stage8c-r2-4a2-2.md), [safe host create handoff](stage8c-r2-4a2-3-f1.md).

These links are not authorization to collect, decrypt, restore, delete or eject.
Keep keys, credentials, manifests with private object data and restored payloads
outside Git and Docker contexts. Never send key material to an automated assistant.

## Screenshot provenance

The product READMEs use [one real development screenshot](assets/match-pass-map.png),
captured on 2026-10-29 (Europe/Moscow) with existing Playwright/Chromium from the
9/281/3895052 Pass Map, Xhaka, period 1, in a 1440×900 viewport. The reviewed
1232×1165 PNG is 112588 bytes. It shows public football analysis only: no browser chrome, account details,
host paths, credentials or runtime logs. Source-byte payloads are not embedded.
It is a documentation asset, not an AI mockup, test-failure dump, production-deployment
claim or new analytical acceptance gate. Attribution uses the provider's official logo;
see [data-source terms](data-sources.md#attribution-and-licensing).

## Historical material

The [legacy README](archive/README-legacy.md) preserves all 2674 original lines,
with relative documentation links retargeted. The [archive audit](archive/README.md)
records its baseline, integrity check and replacement destinations. Existing stage
runbooks, JSON/CSV evidence and earlier Airflow screenshots remain in place.
