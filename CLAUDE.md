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
cd infra; terraform plan                     # infra changes (tfvars has home IP)
```
