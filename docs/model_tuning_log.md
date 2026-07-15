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

**Vegas benchmark (added 2026-07-15).** Historical consensus closing lines
imported (archive_sbr, 8,934 games 2022-2025; in-game-contaminated books
filtered by a 0.15 implied-prob stability rule; 924 corrupt rows excluded by
a [0.20, 0.85] plausibility guard). On 6,291 paired walk-forward games:

| | win acc | log loss | total MAE |
|---|---|---|---|
| closing line (no-vig) | **0.5732** | **0.676** | **3.466** |
| elo | 0.5633 | 0.680 | 3.554 |
| lgbm_runs | 0.5508 | 0.691 | 3.553 |

Elo sits within 1.0pp of the closing line on accuracy and 0.004 on log loss —
a very high floor. The tree models trail the market by ~2.2pp. Market total
MAE 3.466 confirms the totals gap (~0.09 runs) is real but small. Daily
morning + closing line capture now runs in the pipeline (espn_daily), so the
benchmark extends itself going forward.

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

## E1-E4 — 2026-07-15 — first experiment round: all rejected, Elo still the bar

**Setup.** New base snapshot `team/v20260715_073434` (adds flag-gated
UMP_K_FACTOR / WIND_OUT_MPH; window now includes 2026 first half — leakage
test PASS). Monthly walk-forward, 8,713 regular-season test games 2023-04 ..
2026-07. Baselines on this window: lgbm_runs .5463 acc / .5662 AUC, elo
.5539 / .5761. All comparisons paired (validation.ablation).

**E1 — classifier p-head (lgbm_runs_cls). REJECTED, decisively.**
AUC .5524 vs .5662 for the sigma-squash, bootstrap p<.0001 in the WRONG
direction. The margin regressor + Phi(margin/sigma) extracts more probability
signal than a binary head on identical features — binary labels discard the
margin information. Do not revisit without a different probability design
(e.g. distributional runs heads).

**E2 — cross-season rolling windows (snapshot v20260715_073718). REJECTED.**
Directionally worse on every metric (acc .5433 vs .5463, McNemar p=.45; MAE
p=.18). Carrying October form into April does not help; season-scoped
windows stay.

**E3 — umpire K factor + out/in wind (flags umpire, wind_out). PARKED.**
Directionally positive on ALL four metrics (acc +0.4pp p=.18, total MAE
-.003 p=.25, AUC +.002 p=.19) but nothing clears significance. Flags stay
off. Revisit inside a dedicated totals model where these features should
concentrate their effect.

**E4 — slim profile (Elo + SP + park only). NOT SHIPPED, but the key
diagnostic of the round.** Slim matches full on margin MAE (p=.82), beats it
directionally on accuracy (.5531 vs .5463, p=.13), and is statistically
indistinguishable from ELO ITSELF on picks (acc p=.90, AUC p=.12); Elo keeps
a real margin-MAE edge (p=.03). Slim is significantly worse on totals
(p=.005), so the full profile stays default. Conclusion: the ~40 team-form /
bullpen rolling features contribute nothing to win picks — they dilute.
Future team-model features must carry information Elo doesn't already have
(lineup/roster strength, travel, framing), not more form aggregates.

**Decision.** Nothing ships. `feature_set_current` -> v20260715_073434
(extended data + gated columns, default behavior unchanged). Next most
promising: a dedicated totals model (E3 features + offense blocks, Poisson),
and lineup-strength features from the Phase 4 batter machinery — the one
information source the market-adjacent Elo baseline cannot see.

---

## E5 — 2026-07-15 — lineup-strength features: PARKED (positive, not significant)

**Hypothesis.** The posted starting nine, aggregated from shrunken per-batter
class rates (slot-PA-weighted wOBA/K/BB/HR/xwOBA-contact), carries information
Elo and team-form aggregates cannot see (injuries, rest, platoon stacking).

**Leakage catch first.** The initial build FAILED scripts/test_leakage.py:
batter_features' shrinkage prior fell back to FULL-SAMPLE league rates for
early-2022 dates — future data reaching 2.3% of rows at ~3e-4. Fixed with a
fixed era-constant prior (ERA_PRIOR). The same subtle leak existed in the
Phase 4 batter training path (impact negligible: constant prior, first ~week
of 2022 only, test seasons unaffected). Snapshot v20260715_081124, PASS.

**Result (8,713 paired games).**
- lgbm_runs+lineup vs lgbm_runs: acc .5489 vs .5463 (p=.51), margin MAE
  3.5008 vs 3.5055 (p=.28), AUC +.003 (p=.31) — all positive, none significant.
- slim+lineup vs elo: acc p=.51, AUC p=.32, and margin MAE 3.4972 vs 3.4886
  (p=.26) — **the first configuration at statistical parity with Elo on all
  four metrics** (slim alone lost margin MAE at p=.03). Parity, not a win.

**Decision.** Flag stays off; nothing ships. v1 aggregation likely too blunt:
heavy shrinkage (W=150/300) compresses lineup differences, and slot-weighted
means dilute the strongest signal (a star missing). Queued sharper variants:
- E5b: deviation aggregation — sum of (batter rate - league) with lighter
  shrinkage, plus a "missing regular" indicator vs the team's recent lineup.
- E5c: platoon-aware lineup rates vs the opposing probable's hand.
feature_set_current -> v20260715_081124 (fixed prior + gated columns;
default behavior unchanged).

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

