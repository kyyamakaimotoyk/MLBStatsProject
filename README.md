# MLB Stats Project

Predicts MLB **winning margins**, **per-batter performance vs. the probable
starting pitcher**, and **game run totals**, trained on the 2022–2025 seasons
with walk-forward validation. Cloud-native successor to the NBA Stats Project.

**Start here: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)** — goals,
architecture, modeling design, and the phase roadmap.

## Setup

```powershell
# 1. Python environment
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. AWS infrastructure (RDS Postgres, S3, Secrets Manager)
cd infra
Copy-Item terraform.tfvars.example terraform.tfvars   # set your home IP
terraform init; terraform apply

# 3. Local config
Copy-Item .env.example .env    # fill from `terraform output` in infra/

# 4. Database schema
.venv\Scripts\python scripts\migrate.py
```

## Layout

| Path | Purpose |
|---|---|
| `core/` | Shared library: DB engine, feature selection (single source of truth), feature store IO, model registry, S3 artifact store |
| `ingestion/` | StatsAPI / Statcast / odds ingest (Phase 1) |
| `features/` | Feature builders: team, batter, park factors, team rating (Phase 2) |
| `modeling/` | Training, prediction, calibration (Phase 3+) |
| `validation/` | Walk-forward runner, noise-aware ablation harness, benchmarks (Phase 3) |
| `experiments/` | Numbered, one file per hypothesis; results logged in `docs/model_tuning_log.md` |
| `migrations/` | Ordered SQL migrations, applied by `scripts/migrate.py` |
| `infra/` | Terraform for AWS (VPC, RDS, S3) |
| `docs/` | Project plan, schema doc, experiment journal |

## Conventions (hard-won in the NBA project)

- **Feature selection has exactly one home**: `core/features.py::select_features()`.
- **Point-in-time only**: every feature is stamped with `data_through_date`;
  postgame information never enters a pregame feature.
- **No data files in the repo** — DB and S3 are the source of truth.
- **Odds are a benchmark, never a feature.**
- Every model/feature change gets a `docs/model_tuning_log.md` entry with a
  walk-forward result and a significance test.
