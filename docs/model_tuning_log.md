# Model tuning log

Append-only experiment journal (the NBA project's `docs/model_tuning_log.md`
convention, which made every result auditable). Every model or feature change
gets an entry before it ships:

- **Hypothesis** — what should improve and why
- **Setup** — feature_set_version, model type(s), train/test windows
- **Result** — walk-forward metrics vs. the current baseline
- **Significance** — output of the noise-aware ablation harness
  (seeds × bootstrap × paired tests)
- **Decision** — ship / park behind a feature flag / reject

---

## E0 — 2026-07-15 — Phase 3 baseline: model suite vs Elo on v1 features

**Hypothesis.** Tree models over the 69-feature v1 set (rolling team/SP/bullpen,
Elo block, park/weather) beat the pure-Elo baseline on margin and win metrics;
the runs-two-head structure beats direct margin/total regression.

**Setup.** Feature set `team/v20260714_121152`. Monthly expanding walk-forward,
test = regular-season games 2023-04 .. 2025-09 (7,269 games), train = everything
strictly earlier (2022 season is training-only burn-in). Models: lgbm/xgb ×
runs-two-head/direct (conservative hyperparams), Elo baseline (margin via
1-feature linear fit, p from rating), const baseline. Seed 0.

**Result (pooled, regular season).**

| model | win_acc | win_auc | margin MAE | total MAE |
|---|---|---|---|---|
| elo | **0.5602** | **0.5848** | **3.459** | 3.554 |
| lgbm_runs | 0.5478 | 0.5702 | 3.488 | 3.553 |
| xgb_runs | 0.5451 | 0.5699 | 3.487 | 3.559 |
| lgbm_direct | 0.5412 | 0.5604 | 3.519 | 3.558 |
| xgb_direct | 0.5397 | 0.5625 | 3.514 | 3.556 |
| const | 0.5002 | 0.4909 | 3.556 | 3.554 |

**Significance (validation.ablation, paired on 7,269 shared games).**
- elo > lgbm_runs: acc McNemar p=0.026, margin MAE paired-t p=0.0006, AUC
  bootstrap p=0.002 — **the deficit is real**.
- lgbm_runs > lgbm_direct: margin MAE p<0.0001, AUC p=0.004 — **runs structure
  wins**; direct heads retired from the default suite.
- lgbm_runs vs xgb_runs: all p>0.4 — **families equivalent**; keep lgbm as
  primary (faster), xgb as an occasional cross-check.
- Totals: no model beats const (p=0.92) — **zero total-runs signal in v1
  features**.

**Decision.** Honest checkpoint, nothing ships as "better than Elo" yet.
Elo remains the bar. Next experiments, in order:
1. E1: p_home head — trees predict margin then squash; Elo predicts probability
   directly. Try a classifier head / logistic stack on (ELO_P_HOME, pred_margin).
2. E2: cross-season rolling windows with decay (April rows are NaN-heavy;
   2023-04 windows train on 2022 only).
3. E3: totals need dedicated features — umpire tendencies (flag exists),
   park×weather interactions, real 2022 park factors (backfill 2019-21 games).
4. E4: feature pruning — 69 correlated noisy features may be diluting the
   Elo signal; try Elo + SP block only.

---

## B0 — 2026-07-15 — Phase 4 baseline: per-PA batter model vs shrunken marginals

**Hypothesis.** An 8-class per-PA model (OUT/K/BB/HBP/1B/2B/3B/HR) with
shrunken batter/pitcher profiles, platoon splits, arsenal features, and park
beats the batter's own shrunken marginal rates — i.e., the matchup adds signal.

**Setup.** ~740k PAs 2022-2025 (features/batter_features.py; EB shrinkage
W=150 overall / 300 splits; B window 60 games, P window 30). LightGBM
multiclass (300 trees). Season-level walk-forward: train < S, test S.
Game-level eval on regular-season games where the announced probable started;
mixing weight w = league SP PA share; PA counts from empirical slot
distributions. Baseline = batter shrunken marginals aggregated identically.

**Result — per-PA log loss (model | batter-marginal | league):**
- 2023 (train 2022 only): 1.4949 | **1.4920** | 1.5049 — model LOSES
- 2024 (train 22-23):     **1.4682** | 1.4738 | 1.4855 — model wins
- 2025 (train 22-24):     **1.4643** | 1.4731 | 1.4858 — model wins, gap grows

Monotone in training data: the matchup features need 2+ seasons to pay off.

**Game-level (2025, MAE model vs baseline):** H 0.684 vs 0.686, TB 1.349 vs
1.351, HR 0.2172 vs 0.2177, BB **0.457 vs 0.469** (largest edge, all 3
seasons), K 0.671 vs **0.666** (model loses on K all 3 seasons).

**Calibration (pooled 130,950 batter-games):** P(>=1 hit) and P(>=1 HR)
well-calibrated through decile 8; top decile overconfident (p_hr pred 0.226
vs obs 0.188). Ranking power: top p_hr decile homers at 18.8% vs 5.4% for
bottom.

**Decision.** Ships as pa_v1 (predictions in batter_predictions). Queued:
- B1: per-SP workload share for the mixing weight w (openers vs workhorses).
- B2: K anomaly — model trails shrunken marginals on strikeouts every season;
  test dropping arsenal features from the K head or longer batter K windows.
- B3: isotonic calibration on the probability heads (top-decile overconfidence).
- B4: batter per-pitch-type profile x pitcher arsenal crossing (the full
  arsenal-matchup idea; v1 only has aggregate arsenal features).

