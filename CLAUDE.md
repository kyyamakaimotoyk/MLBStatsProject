# MLB Stats Project

Predicts MLB winning margins, per-batter performance vs. the probable starting
pitcher, and game run totals. Cloud-native successor to the NBA Stats Project
(`D:\Kai\PycharmProjects\NBAStatsProject` — the architectural reference).

**Read `docs/PROJECT_PLAN.md` before making design decisions.** It records the
goals, architecture, modeling design, phase roadmap, and the NBA lessons this
project is built around.

## Hard rules (each one is a scar from the NBA project)

- Feature selection lives ONLY in `core/features.py::select_features()`.
  Never keep a second feature list anywhere.
- Point-in-time correctness: features and backfilled predictions may only use
  data with `data_through_date` before the game. No postgame info in pregame
  features.
- No data files in the repo (`.gitignore` blocks `*.csv`/`*.parquet`). The DB
  (RDS Postgres) and S3 are the source of truth.
- Odds/betting lines are evaluation benchmarks, never model features.
- Raw batter-vs-pitcher career history is not a feature (it's noise).
- Every model/feature change gets an entry in `docs/model_tuning_log.md` with
  a walk-forward result and significance test before it ships.
- Schema changes go through numbered SQL files in `migrations/`, applied with
  `python scripts/migrate.py`. No ad-hoc ALTER TABLE from application code.

## Stack

- Python 3.14 in `.venv`; deps in `requirements.txt`
- Postgres 17 on AWS RDS (`mlb_data`); SQLAlchemy 2 Core (raw SQL via `text()`,
  no ORM models); engine only via `core/db.py::get_engine()`
- S3 bucket `mlb-stats-data-<account>`: `raw/` (gzipped API JSON), `models/`
  (via `core/artifact_store.py`), `exports/`
- Infra: Terraform in `infra/` (region us-east-1). DB password is RDS-managed
  in Secrets Manager; `core/db.py` fetches it at startup — do not paste
  passwords into `.env`.
- Config via `.env` (see `.env.example`); secrets never committed.

## Commands

```powershell
.venv\Scripts\python scripts\migrate.py      # apply pending migrations
.venv\Scripts\python scripts\check_db.py     # connectivity + schema sanity check
.venv\Scripts\python scripts\audit_ingest.py # ingestion exit-criteria audit
cd infra; terraform plan                     # infra changes (tfvars has home IP)

# Ingestion (ledger-driven, resumable — safe to kill and rerun):
.venv\Scripts\python -m ingestion.backfill_games --season 2024 --workers 6
.venv\Scripts\python -m ingestion.backfill_statcast --limit 10
.venv\Scripts\python -m ingestion.import_reference --chadwick

# Umpire/officials track (2026-07 cycle, docs/literature_review_2026-07.md):
.venv\Scripts\python scripts\backfill_officials.py --workers 8      # full crews from S3 GUMBO archive
.venv\Scripts\python -m ingestion.import_retrosheet --start 1998 --end 2025  # historical crews + K/BB
.venv\Scripts\python scripts\alpha_atlas.py     # per-stat reliability constants -> docs/alpha_atlas_*.md

# Features (rebuild order: rating -> park -> features):
.venv\Scripts\python -m features.team_rating
.venv\Scripts\python -m features.park_factors
.venv\Scripts\python -m features.team_features --set-current
.venv\Scripts\python scripts\test_leakage.py     # must PASS before a snapshot ships

# Modeling:
.venv\Scripts\python -m validation.walkforward   # team models, writes registry+preds
.venv\Scripts\python -m validation.ablation --a lgbm_runs --b elo
.venv\Scripts\python -m validation.walkforward_batter   # per-PA batter model (long; run detached)

# Daily pipeline (Phase 5) — ingest refresh + slate + all three products:
.venv\Scripts\python -m orchestration.daily              # today
.venv\Scripts\python -m orchestration.daily --date 2026-07-16 --skip-ingest
.venv\Scripts\python -m orchestration.daily --scores-only   # same-day finals only
.venv\Scripts\python scripts\track_performance.py        # outcomes vs predictions
.venv\Scripts\python scripts\benchmark_odds.py           # models vs closing lines
.venv\Scripts\python -m ingestion.odds_espn --date 2026-07-16   # manual line capture
```

Odds are benchmark-only (hard rule): they live in odds_lines and never enter
a feature snapshot. The daily pipeline captures morning lines for today and
closing lines for yesterday automatically.

Model bundles live in S3 (`models/team_runs_latest.joblib`,
`models/batter_pa_latest.joblib`) and retrain automatically when older than
7 days — never ship a stale bundle silently (NBA calibration-incident lesson).

## Web layer

Public site: **https://moundmodel.com** (S3+CloudFront static export) with the
API at **https://api.moundmodel.com** (Fargate service behind an ALB).
Site changes ship automatically: any push to master touching `web/**` runs
`.github/workflows/deploy-site.yml` (build with the prod API URL -> S3 sync ->
CloudFront invalidation, via the OIDC role in `infra/deploy_ci.tf`). Manual
fallback:
`cd web; $env:NEXT_PUBLIC_API_URL="https://api.moundmodel.com"; npm run build`
then `aws s3 sync out s3://mlb-stats-site-583686634997 --delete` + CloudFront
invalidation — never deploy an `out/` from a plain `npm run build`
(`web/.env.local` bakes in localhost). To ship API changes: build
`Dockerfile.api`, push to ECR `mlb-stats-api`, then
`aws ecs update-service --force-new-deployment`.

The site is bilingual (EN/JA, the hoopmodel pattern): every user-facing string
lives in `web/lib/translations.ts` and is read via `useLang()` — never hardcode
UI copy in a component. `en` defines the dictionary shape; `ja` is type-checked
against it, so a missing translation is a build error. The file's header holds
the Japanese style glossary.

Monetization: the Google Analytics + AdSense IDs live in `web/lib/ads.ts`
(empty string = integration off; the publisher ID also goes in
`web/public/ads.txt`). Consent Mode v2 defaults to denied in the EEA/UK/CH —
bootstrap script in `app/layout.tsx`, banner in `components/ConsentBanner.tsx`.
Ads render only through `components/AdSlot.tsx`, whose frame heights are
reserved in CSS (`.ad-frame`) so ads can never shift page content; the privacy
policy lives at `/privacy` and is translated like everything else.

```powershell
.venv\Scripts\uvicorn api.main:app --port 8000   # local API (model-free by design)
cd web; npm run dev                              # local frontend on :3000
.venv\Scripts\python visualization\site_traffic.py   # local-only traffic dashboard on :8050
```

Site analytics: CloudFront access logs land in `mlb-stats-logs-<account>`
under `cf-site/` (90-day TTL) and are queried through Athena (Glue table
`moundmodel_logs.cf_site_logs`, workgroup `mlb-stats` — `infra/analytics.tf`).
The dashboard deps live in `visualization/requirements-viz.txt`, deliberately
out of the root `requirements.txt` so the Docker images don't inherit them.
Internal only — never surface this data on the public site.

## Automation (Phase 6)

The pipeline runs on Fargate via EventBridge Scheduler (`infra/schedule.tf`),
all UTC: the full daily run at 14:00; prediction refreshes at 18:00/21:00/23:00
(posted lineups + late probables, upserting over the morning run); and
same-day score refreshes at 20:00, 22:00, 00:00, 02:00, 04:00, 06:00
(`orchestration.daily --scores-only` — imports finals only, so scores and
pick grading reach the site the same evening).
Image: `Dockerfile.pipeline` -> ECR `mlb-stats-pipeline`.
To ship pipeline code changes:
`docker build -f Dockerfile.pipeline -t mlb-stats-pipeline .` then tag/push to
ECR (`:latest`). Logs: CloudWatch `/ecs/mlb-stats-pipeline`.

To retry ledger entries that exhausted their attempts:
`UPDATE ingest_ledger SET attempts=0, status='pending' WHERE status='error';`
