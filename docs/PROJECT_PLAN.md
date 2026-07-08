# MLB Stats Project — Master Plan

Successor to the NBA Stats Project (`D:\Kai\PycharmProjects\NBAStatsProject`), rebuilt
cloud-native from day one. Written 2026-07-08.

## 1. Goals

Three prediction products, in priority order:

1. **Winning margin** — home team run differential per game (regression + derived win probability).
2. **Per-batter performance vs. the probable starting pitcher** — the headline new feature.
   Two output forms per batter per game:
   - Expected stat line: E[hits], E[total bases], E[HR], E[BB], E[K]
   - Calibrated probabilities: P(≥1 hit), P(≥1 HR), P(≥2 TB), P(≥1 BB)
3. **Game run totals** — expected total runs (over/under style).

Training data: the four complete seasons **2022–2025** (~9,720 games), with the in-progress
2026 season as the live prediction target. Validation is **sequential / walk-forward** throughout.

Betting odds (moneyline, run line, totals) are ingested **as a benchmark only** — never as
model features. Beating or approaching the closing line is the gold-standard evaluation.

The web layer is deferred until MVP; when built, it runs locally first (the NBA
FastAPI + Next.js pattern ports directly).

## 2. Lessons carried over from the NBA project

Keep (proven patterns):
- **Versioned feature store in the DB** (`features` table + version pointer) — never a root CSV.
- **Single source of truth for feature selection** (`core/features.py::select_features()`).
  The NBA project's worst recurring bug was three modules each holding their own feature list.
- **Model registry table** (metrics + hyperparams + feature-set lineage + run_kind) and an
  append-only `docs/model_tuning_log.md` experiment journal.
- **Noise-aware ablation harness** (`e3_noise_ablation.py`: seeds × bootstrap × McNemar /
  paired-t) — port nearly verbatim; every feature must clear it.
- **Idempotent ingest with an imported-games ledger** and retry/backoff scaffolding.
- **Walk-forward validation as the core methodology**, Vegas as the accuracy/MAE floor.
- **Tree models (LightGBM/XGBoost) as workhorses** — the NBA NNs never beat them on tabular data.
- **Artifact store abstraction** (S3 or local by env var).

Change (pain points to avoid):
- **Postgres on RDS instead of MySQL** — better analytics SQL (window functions, partial
  indexes), and everything downstream is plain SQLAlchemy Core anyway.
- **Archive raw API JSON to S3 on ingest** — parsing bugs become a reprocess, not a re-fetch.
- **No monoliths**: inference, training, feature assembly, and IO live in separate modules
  from the start (`predict_games.py` hit 4,308 lines in the NBA repo).
- **Point-in-time correctness designed in from day one**: every feature build and backfilled
  prediction is keyed on a `data_through_date`; postgame information is unreachable by
  construction, not by discipline.
- **Calibration/staleness monitoring as first-class**: degeneracy tripwires and a scheduled
  retrain existed in the NBA project only after an incident. Build them with the first model.

## 3. Data sources

| Source | What | Access | Notes |
|---|---|---|---|
| **MLB Stats API** (`statsapi.mlb.com`) | Schedule, probable pitchers, starting lineups, boxscores, play-by-play, rosters, transactions, venues, weather in game data | Free, official, no key | Python: `MLB-StatsAPI` package or direct REST. The backbone. |
| **Statcast** (Baseball Savant via `pybaseball`) | Pitch-level data 2015+: pitch type, velo, spin, location, exit velocity, launch angle, xwOBA/xBA per event | Free | ~700–750k pitches/season → ~3M rows for 2022–2025. Bulk-download by date range; rate-limit friendly. |
| **Chadwick Bureau register** | Player ID crosswalk (MLBAM ↔ FanGraphs ↔ BBRef ↔ Retrosheet) | Free CSV | Load once into a reference table. |
| **FanGraphs** (via `pybaseball`) | Season-level advanced stats, projections (optional) | Free | Nice-to-have; most features derivable from Statcast + StatsAPI. |
| **Odds (benchmark only)** | Historical closing moneyline/run line/totals 2022–2025; daily lines going forward | Kaggle/SBR historical dumps + The Odds API or ESPN scrape for live | Same two-pronged approach as the NBA project (Kaggle import + ESPN scraper). |

Weather comes embedded in MLB StatsAPI game data (temp, wind, condition); park factors are
computed in-house from our own data (or seeded from Savant's published factors).

## 4. Cloud architecture (AWS)

Phase-1 footprint (cheap, immediately cloud-native in the data layer):

- **RDS PostgreSQL** (db.t4g.micro, single-AZ) — the operational store. Database `mlb_data`.
  Credentials in **Secrets Manager**; local dev connects over SSL to the same instance
  (no local/prod schema drift).
- **S3, one bucket, three prefixes**:
  - `raw/` — gzipped raw API JSON, keyed `source/date/game_pk.json.gz`
  - `models/` — model bundles (the NBA `artifact_store.py` pattern)
  - `exports/` — occasional feature-set snapshots for offline analysis
- Ingestion/training run **locally first** (scripts pointing at RDS/S3), then containerized.

Later phases (reuse NBA Terraform patterns from `infra/`): ECR + Fargate one-off tasks,
EventBridge Scheduler for the nightly predict / weekly retrain cadence, OIDC GitHub Actions.

Estimated steady-state cost before automation: ~$13–18/mo (RDS micro) + pennies for S3.

## 5. Database schema (sketch)

Reference:
- `teams`, `venues` (park dimensions, roof type), `players` (+ Chadwick crosswalk columns)
- `id_ledger` — imported-object memory (game_pk, source, status, attempt count) for idempotent ingest

Per game (from StatsAPI):
- `games` — game_pk, date, home/away team, venue, day/night, doubleheader flag, weather
  (temp, wind speed/dir, condition), attendance, umpires (HP umpire for totals features),
  final score, innings played
- `probable_pitchers` — **point-in-time snapshots** (game_pk, captured_at, home/away probable);
  probables change, and the model must train on what was knowable pregame
- `lineups` — starting lineups with batting order slot (also snapshot-stamped)
- `batter_game_lines` / `pitcher_game_lines` — per-player boxscore rows (~90 batter rows/game)
- `plays` — plate-appearance-level events from play-by-play (batter, pitcher, inning, outs,
  base state, event type, RBI, WPA-relevant fields): ~740k rows for 4 seasons

Pitch level (from Statcast):
- `statcast_pitches` — one row per pitch (~3M rows). Partition or index by game_date.
  This powers pitcher arsenal features and batter quality-of-contact features.

Derived / ML:
- `park_factors` (season × venue × handedness)
- `team_strength_pregame` (Elo-style rating, point-in-time, like `team_elo_pregame`)
- `features_team` + `features_batter` + `feature_set_versions` + `feature_set_current`
  (versioned feature store, one snapshot per build)
- `model_registry`, `model_predictions` (team-level), `batter_predictions` (player-level)
- `odds_lines` (benchmark data, kept out of feature joins by convention **and** by schema —
  no odds columns ever enter `features_*`)

## 6. Feature engineering

All rolling features use `.shift(1)` semantics (pregame info only) and are stamped with
`data_through_date`. Feature selection lives in exactly one module.

**Team level** (for margin + totals):
- Rolling team offense: runs/game, wOBA, xwOBA, ISO, K%, BB% over L10/L30 games
  (baseball needs longer windows than NBA's L5/L10 — single games are noisier)
- Rolling team run prevention: runs allowed, bullpen ERA/xFIP, defensive efficiency
- **Starting pitcher block** (the biggest single factor): rolling xFIP/SIERA-style rates,
  K%, BB%, GB%, xwOBA-against over last N starts, days rest, pitch count trend,
  times-through-order splits, handedness
- **Bullpen state**: pitches thrown by relievers in last 1–3 days (fatigue), available
  high-leverage arms
- Schedule/context: rest days, travel (time zones), day-after-night, series game number
- Park + weather: park factor, temperature, wind speed/direction (big at Wrigley/Coors),
  roof open/closed
- Team strength rating: Elo-style with MOV multiplier, tuned for baseball (much smaller K;
  a pure-Elo baseline gives ~55–56% accuracy vs NBA's 66%)
- HP umpire K/BB tendencies (totals model; optional, ablate it)

**Batter vs. probable SP** (per-PA framing):
- Batter skill (shrunken): rolling xwOBA, K%, BB%, ISO, barrel rate over L100/L250 PA,
  with **empirical-Bayes shrinkage toward league/position priors** — small samples dominate
  baseball and raw rates are noise
- Platoon splits (batter vs LHP/RHP), computed with shrinkage
- **Pitcher arsenal vs. batter profile**: pitcher's pitch-mix and per-pitch-type
  whiff/xwOBA-against crossed with batter's per-pitch-type performance (Statcast makes
  this possible; it's the principled replacement for raw batter-vs-pitcher history,
  which is famously noise and will NOT be a feature)
- Lineup slot → expected PA count (slot 1 averages ~4.6 PA, slot 9 ~3.6)
- Expected SP innings (how soon the bullpen enters) and opposing bullpen quality
- Park/weather HR factors for the probability heads

## 7. Modeling design

**Core structural idea — model runs, derive everything:** the primary team-level model
predicts each team's **runs scored** in the game (home and away heads sharing features).
Then margin = home − away and total = home + away fall out of one coherent model, and
win probability comes from the margin distribution. Direct margin and total regressors
are also trained as comparison baselines — walk-forward decides which ships.

- Team-level learners: **LightGBM and XGBoost** first (NBA-tuned regularization instincts
  carry over: shallow depth, strong min-child-weight). RF as a sanity baseline. No NNs
  until trees plateau.
- Distributional outputs: negative-binomial-style objectives or quantile/conformal wrappers
  for run-total intervals. Baseball quirks handled explicitly: walk-off truncation censors
  home-team runs in home wins; the extra-innings ghost runner inflates extras scoring —
  both matter for totals calibration.

**Batter model — per-PA outcome model, aggregated:** predict a per-PA outcome distribution
(K / BB / HBP / out-in-play / 1B / 2B / 3B / HR) given batter, pitcher, park, platoon,
context. A gradient-boosted multiclass model is the baseline. Then:
- Expected stat line = per-PA distribution × expected PA count for the lineup slot
- P(≥1 hit) etc. = analytic aggregation over PAs (with a calibration layer checked
  against observed frequencies)

This one model serves both chosen output forms, and its PA-level granularity means
~740k training rows instead of ~90k noisy game lines.

**Calibration & uncertainty:** isotonic calibration where walk-forward shows miscalibration
(the NBA finding: don't calibrate blindly — RF was fine raw, XGB needed it), split-conformal
intervals for margins/totals, and a degeneracy tripwire on pick-share drift from day one.

## 8. Validation methodology

- **Walk-forward, expanding window**: train on all games strictly before window W, predict
  W. Windows: monthly within a season and season-over-season (train 2022 → test 2023, etc.).
- **Regime awareness**: the 2023 rule changes (pitch clock, shift ban, bigger bases) shifted
  the scoring environment between 2022 and 2023. Walk-forward results are reported per-season;
  a recency-weighting ablation decides how much 2022 helps.
- Early-season handling: heavier shrinkage toward priors in April; ablate carrying
  prior-season stats forward with decay.
- **Metrics**: margin MAE/RMSE + win accuracy/AUC; totals MAE + over/under accuracy vs
  closing total; batter model — per-PA log loss, stat-line MAE, and reliability curves for
  the probability heads; CRPS for distributional outputs.
- **Benchmarks to beat/approach**: closing line (Vegas favorites hit ~57–58% in MLB;
  margin MAE floor ≈ 2.9–3.1 runs; totals MAE ≈ 2.5–2.7). Set expectations now: MLB is far
  noisier per-game than NBA — a great MLB model wins ~58–60% straight-up, not 75%+.
- Every feature/change goes through the ported **noise-aware ablation harness**
  (multi-seed × bootstrap × paired significance tests) and gets a row in the tuning log.

## 9. Phases

**Phase 0 — Scaffolding (small)**
Repo layout, `core/` (db engine w/ pooling + `pool_pre_ping`, feature selection stub,
features_io, model_registry, artifact_store), AWS setup (RDS Postgres, S3 bucket, Secrets
Manager), `.env` pattern + `.env.example`, Alembic (or SQL migration folder) from the start.

**Phase 1 — Ingestion + 4-season backfill**
StatsAPI client with retry/backoff + ledger; raw JSON → S3; parsers → Postgres for
games/boxscores/lineups/plays; Statcast bulk backfill 2022–2025; Chadwick ID crosswalk;
odds historical import. Exit criteria: row-count and spot-check audits pass for all 4 seasons.

**Phase 2 — Feature engineering + feature store**
Park factors, team rating, rolling team/SP/bullpen features, versioned `features_team`
build; leakage tests (a feature build at date D must be byte-identical whether or not
post-D data exists in the DB).

**Phase 3 — Team models + walk-forward harness**
Runs-scored model + direct margin/total baselines; walk-forward runner; ablation harness
port; model registry + tuning log; first honest results vs closing-line benchmark.
**This is the MVP checkpoint for team-level predictions.**

**Phase 4 — Batter vs SP model**
Per-PA multiclass model, shrinkage priors, arsenal×profile features, aggregation to stat
lines + probability heads, `batter_predictions` table, walk-forward evaluation per-season.

**Phase 5 — Daily prediction pipeline**
Morning job: fetch schedule + probables (+ lineups when posted, ~2–4h pregame) → build
point-in-time features → predict all three products → write predictions; outcome backfill
tracker; staleness/degeneracy monitors. Runs locally on a schedule first.

**Phase 6 — Automation + web MVP**
Terraform (adapted from NBA `infra/`): Fargate one-off tasks + EventBridge (nightly predict,
weekly retrain). Local web MVP: FastAPI read-only API + Next.js front end, reusing the NBA
site's structure (picks page, accuracy page, per-batter matchup page is the new piece).

## 10. Repo layout (target)

```
core/               db.py, features.py, features_io.py, model_registry.py, artifact_store.py
ingestion/          statsapi_client.py, statcast_backfill.py, odds_import.py, parsers/
features/           team_features.py, batter_features.py, park_factors.py, team_rating.py
modeling/           targets.py, train_team.py, train_batter.py, predict.py (thin), calibrate.py
validation/         walkforward.py, ablation.py (ported noise harness), benchmarks.py
orchestration/      pipeline.py (staged, DB-freshness driven)
experiments/        numbered, one file per hypothesis, logged in docs/model_tuning_log.md
api/  web/          deferred to Phase 6
infra/              Terraform, adapted from NBA project
docs/               PROJECT_PLAN.md (this), DATABASE_SCHEMA.md, model_tuning_log.md
migrations/         Alembic or ordered SQL
```

## 11. Known risks / gotchas

- **Probable pitcher changes and scratches** — snapshot probables with timestamps; evaluate
  the batter model only on games where the probable actually started (and separately measure
  scratch impact).
- **Doubleheaders** (game_pk disambiguation, fatigue effects), **suspended/resumed games**,
  **7-inning games are gone post-2021 but verify**, **ties impossible** (no margin=0 class).
- **Walk-off truncation + ghost runner** distort run distributions — handle in the totals
  model, not by ignoring.
- **Lineups post late**: the daily pipeline needs a "probables-only" early prediction and a
  "lineups-confirmed" refresh.
- **pybaseball/Savant rate limits** on the 3M-row backfill — chunk by date, archive to S3,
  never re-scrape.
- **2023 rule-change regime shift** — per-season reporting will reveal whether 2022 data helps or hurts.
- **BvP temptation** — batter-vs-pitcher career history stays out of the model; it's noise.

## 12. Open questions (deferred, non-blocking)

- Historical odds source final pick (Kaggle dump vs The Odds API paid tier) — decide in Phase 1.
- Whether 2026 in-progress data joins training continuously or only at season checkpoints.
- Umpire and catcher-framing features — Phase 3/4 ablation candidates, not core.
