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

## Web layer (local MVP)

```powershell
.venv\Scripts\uvicorn api.main:app --port 8000   # read-only API (model-free by design)
cd web; npm run dev                              # Next.js frontend on :3000
```

## Automation (Phase 6)

The daily pipeline runs on Fargate at 14:00 UTC via EventBridge Scheduler
(`infra/schedule.tf`). Image: `Dockerfile.pipeline` -> ECR `mlb-stats-pipeline`.
To ship pipeline code changes:
`docker build -f Dockerfile.pipeline -t mlb-stats-pipeline .` then tag/push to
ECR (`:latest`). Logs: CloudWatch `/ecs/mlb-stats-pipeline`.

To retry ledger entries that exhausted their attempts:
`UPDATE ingest_ledger SET attempts=0, status='pending' WHERE status='error';`
