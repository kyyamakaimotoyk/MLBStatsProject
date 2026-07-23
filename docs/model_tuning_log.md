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

## E7 — 2026-07-16 — 2019-2021 backfill: SHIPPED, the project's largest gain

**Change.** Three seasons backfilled (5,883 games, ~2.1M pitches; 2020 is the
60-game COVID season). Consequences bundled in: real 2022 park factors
(previously neutral), two extra seasons of Elo burn-in, 7-inning 2020-21
doubleheaders excluded from training targets (kept in rolling inputs), odds
archive extended to 2021 (11,312 games with closing lines), era-constant
prior unchanged. Snapshot v20260716_083741 (16,985 rows), leakage PASS on
11,854 games.

**Team model (same 8,713 test games, seeds 0/1/2 all confirm).**
vs the previous shipped config: acc .5612 vs .5522 (p=.034), margin MAE
3.4778 vs 3.4946 (p=.003), total MAE 3.5331 vs 3.5556 (**p=.0001 — first
significant totals gain ever**), AUC .5810 vs .5734 (p=.031). Seeds 1/2:
all four metrics p<=.026, most p<.001. 12/12 comparisons positive.

vs rebuilt Elo (also improved with burn-in, .5563/.5789/3.480): the model
leads every point estimate; totals decisively (p<.0001); win-pick metrics at
parity (acc p=.31, AUC p=.62). Honest claim: better-or-equal everywhere,
strictly better on totals. Market gap: totals 3.533 vs market 3.47 — halved.

**Batter model.** The 2023 anomaly resolved: with 2019-2022 training, 2023
now beats the marginal baseline (1.4836 vs 1.4918; it lost with 2022-only).
Every season, every game-level stat except raw K (B2 blend covers it).
B0's learning curve confirmed end to end.

**Also observed.** B3 isotonic on p_hit turned SIGNIFICANT with 8-season
training (Brier .23349 vs .23376, p<.0001 pooled) — queued for its own
confirmation before shipping. B1 still negative, B2 still strong.

**Decision.** Ships everywhere: snapshot current, production bundles
invalidated (next daily run trains on 8 seasons), public-site backtest
rewritten from the 8-season model.

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

## E5b — 2026-07-15 — deviation + missing-regular lineup features: SHIPPED

**Changes vs E5.** LINEUP_DEV_WOBA (slot-PA-weighted SUM of each starter's
wOBA deviation from the expanding league rate — magnitude preserved instead
of shrinkage-compressed) and the injury signal: LINEUP_MISSING_WOBA /
LINEUP_N_REG_OUT, where regulars = >=60% of the team's previous 15 posted
lineups and their absence is weighted by appearance share x as-of deviation.
Snapshot v20260715_082809 (105 cols), leakage gate PASS.

**Result (8,713 paired games).**
- lgbm_runs+lineup2 vs lgbm_runs baseline: margin MAE 3.4946 vs 3.5055
  (**p=.020**), AUC .5734 vs .5662 (**p=.009**), acc +0.6pp (p=.16) —
  first change to clear the significance bar. SHIPS.
- vs E5 v1 on the slim stack: better on acc (p=.055), AUC (p=.062), margin
  (p=.096) — the sharper aggregation is what v1 lacked.
- vs Elo (slim+lineup2): acc .5565 vs .5539 — ahead of Elo for the first
  time, though within noise (p=.64); margin MAE and AUC at parity. Elo no
  longer leads on any metric.

**Multi-seed confirmation (added same day).** Reran E5b-vs-baseline at seeds
1 and 2 (baseline on the lineup-free snapshot v20260715_073434). All 12
seed x metric comparisons favor lineup2 with consistent magnitudes (margin
MAE -0.007..-0.011, AUC +0.005..+0.007, acc +0.6..+1.4pp); seed 2 alone
gives acc McNemar p=.0008 and AUC p=.022. Direction never flips — not seed
noise. (Known caveats stand: per-comparison p-values, no family-wise
correction; game independence assumed.)

**Decision.** FEATURE_FLAGS['lineup'] = True. Daily path wired:
build_prediction_rows takes projected lineups via lineup_strength_asof
(caveat: projection = last posted lineup until real lineups are consumed, so
missing-regular reflects yesterday's absences pregame; rerunning after
lineups post sharpens it). Team bundle invalidated to force retrain.
Queued: E5c platoon-aware lineup rates; consume real lineups when posted.

---

## E5c — 2026-07-15 — platoon-aware lineup rates: REJECTED (null result)

**Setup.** LINEUP_VS_HAND_WOBA / LINEUP_VS_HAND_DEV (nine's vs-hand rates
against the opposing probable's throwing hand) + LINEUP_SAME_HAND_SHARE,
flag lineup_platoon, snapshot v20260715_091625 (114 cols, leakage PASS).

**Result vs shipped E5b config (8,713 paired games).** acc +0.3pp (p=.35),
margin MAE +.0005 (p=.87), AUC -.0004 (p=.85), total MAE +.002 (p=.62).
Indistinguishable — the SP handedness features and overall lineup rates
already carry the platoon information, and W=300 shrinkage leaves the splits
little independent signal.

**Decision.** Flag stays off. Not worth a multi-seed run on a null this flat.
Remaining queue: dedicated totals model (parked E3 features), batter B1-B4.

---

## E6 — 2026-07-15 — dedicated totals model: REJECTED (null)

**Setup.** lgbm_runs_tt: runs heads unchanged + a dedicated Poisson totals
head on a totals-focused subset (no DIFF_*/ELO_DIFF/ELO_P_HOME). Variants
with and without the parked E3 flags (umpire, wind_out). Snapshot
v20260715_091625; margin/p_home provably untouched (0 discordant picks).

**Result (8,713 paired games, totals MAE).** Dedicated head alone: 3.5597 vs
shipped 3.5556 (p=.39) — no better than summing the runs heads. With
umpire+wind: 3.5550 vs 3.5597 (p=.13) — the E3 effect appears a third time
(~-.005, p=.13-.25 every time) and fails significance a third time. Net vs
shipped config: p=.91.

**Decision.** Rejected. The market totals gap (3.466 vs our 3.555) is not
addressable by rearranging current features — the missing ingredient is NEW
information: real weather FORECASTS (we train on game-time weather and serve
NaN), venue scoring drift, bullpen-day specifics. Queued as E6b: forecast
weather feed for the daily pipeline + rolling venue scoring environment.
The tiny umpire/wind effect likely becomes shippable as seasons accumulate.

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

---

## B1-B4 — 2026-07-15 — batter experiment round: B2 ships, rest rejected/parked

**Method.** B1/B2/B3 are aggregation/calibration variants evaluated in ONE
walk-forward pass against the same trained models — paired by construction
on 130,950 batter-games; B4 trains with/without models per season
(--b4-compare). All verdicts replicated across two independent runs.

**B1 — per-SP workload share for the mixing weight w: REJECTED (significantly
worse).** Hits MAE 0.6851 vs 0.6850, K MAE 0.6784 vs 0.6782, both p<.01 in
the WRONG direction: the per-SP IP/9 estimate is noisier than the league
constant it replaces.

**B2 — K probability blended halfway to the batter marginal: SHIPPED.**
K MAE 0.6721 vs 0.6782 (p<.0001) — closes the strikeout anomaly tracked
since B0 (the PA model over-trusts matchup K signal). Shipped as
batter_model.blend_k in the daily aggregation; stored pa_v1 walk-forward
preds are pre-blend, the harness reports the blend variant explicitly.

**B3 — isotonic calibration of p_hit/p_hr on the prior season: PARKED.**
Brier deltas ~5e-5, p=.15-.35. Top-decile overconfidence is real but too
small and season-drifty for a prior-season calibrator. Revisit as seasons
accumulate; never ship a calibrator without demonstrated benefit (NBA E13
lesson).

**B4 — per-pitch-class quality x pitcher mix (B_XWOBA_F/B/O,
B_ARSENAL_MATCH): PARKED.** Per-PA log loss 1.47543 vs 1.47562 (p=.22),
hits MAE p=.22, K MAE p=.97. Direction mildly positive; columns stay in the
builder behind flag arsenal_cross (off).


## B5 — 2026-07-17 — 2026 batter walk-forward window: backfill shipped

**What.** Ran the standard batter walk-forward for a 2026 test window
(train 2019-2025, 1,188,606 PAs; test 109,249 PAs through 2026-07-16) via
the new `--seasons` flag, writing 25,887 game predictions as pa_v3 — the
site's player pages had no pregame batter calls for 2026 games before
launch (blank "We said" columns).

**Result (out of sample, consistent with the 2023-25 windows).** Per-PA
log loss 1.47009 vs batter-marginal 1.48074 / league 1.49304. Game-level:
hits MAE 0.6803 vs 0.6826 base; Brier p_hit 0.2357 vs 0.2366; Brier p_hr
0.1014 vs 0.1017. B2 K-blend confirmed again on 2026 alone (K MAE 0.6717
vs 0.6749, p<.0001).

**No model or feature change** — same builder, same feature set, same
hyperparams; registry row logged as usual. Also backfilled 2026 closing
lines from ESPN the same day (1,444/1,444 final games covered), so the
vs-market record now includes the current season.

---

## E8 — 2026-07-17 — systematic feature-family loop: nothing ships, the map redrawn

Full write-up (method, tables, per-experiment detail):
docs/modeling_deep-dive_2026-07-17.md. Baselines lgbm_runs+8s / elo+8s on
v20260716_083741, 8,713 paired games, validation.ablation throughout.

**E8a — drop-one family matrix** (new no_<family> profiles in
core/features.py, still the single source of truth). Picks/margin/AUC are
carried by SP + Elo ALONE (dropping either: acc -0.8/-0.9pp McNemar p=.02,
AUC p<=.003); totals are carried by weather (+.0166 total MAE when dropped,
p<.0001), park (p=.002), lineup (p=.019), context (p=.016). Bullpen is inert
on all four metrics. Form DILUTES probability ranking (drop -> AUC +.0037
p=.022 at seed 0) but the gain flips sign at seed 2 — not a robust win, no
default change. Slim rerun confirms E4 at 8 seasons (picks parity, totals
p=.004 worse).

**E8b — umpire+wind retest at 8 seasons. REJECTED (4th time).** Total MAE
3.5303 vs 3.5331, p=.23. The effect did not grow with data. Retest retired
until a pregame serve path exists (ump capture + E6c park orientation).

**E8c — Elo/LGBM p-blend (offline). PARKED.** Best alpha=.3: pooled acc
.5638 vs .5612 (McNemar p=.57). Diagnostic: when the two models split
(~20% of games) lgbm accuracy is .5074 — coin flip; agreement games .5792.

**E8d — first MLB hyperparameter sweep. INCUMBENT WINS.** 15 configs,
selection on 2023-2025 only (2026 untouched): incumbent .5654, next .5634;
deeper trees monotonically worse (63 leaves .5565). Conservative NBA-derived
params are validated; hyperparams are ruled out as the market-gap source.

**E8e/E8f — travel + venue scoring drift. REJECTED (null).** New flag-gated
columns (TRAVEL_KM, TRAVEL_TZ_DELTA per side + DIFF; VENUE_ENV_L40), snapshot
v20260717_023946 (121 cols, leakage PASS). Travel: all four metrics p>=.29.
Venue env: totals p=.64. Flags stay off; columns remain in the builder.

**E8g — market-gap decomposition (diagnostic).** The gap to the closing line
is a first-half phenomenon: Mar -5.6pp, Apr -1.8pp, Jun -3.3pp, then Aug
+2.1pp / Sep +0.1pp — the model beats the market from August on. 2026's
-2.0pp is entirely Mar-Jun (Jul 2026 already +1.2pp). Disagreement picks are
.4785 pooled and no confidence bucket rescues them.

**Decision.** No team-model change ships. The queue reorders: E9
early-season priors/shrinkage (the one first-half lever with direct
evidence), then serve-path acquisitions (pregame umpire, E6c park
orientation, game-day roof status). feature_set_current stays
v20260716_083741.

---

## B6 — 2026-07-17 — B3 isotonic on p_hit: CONFIRMED, SHIPS (p_hr stays raw)

**Setup.** walkforward_batter --seasons 2023 2024 2025 2026 --no-preds,
seeds 0/1/2 (8-season data, 156,837 pooled batter-games; calibrator fit on
prior test seasons, 2023 uncalibrated either way).

**Result.** p_hit Brier .23380/.23385/.23383 vs raw .23408/.23410/.23406 —
p<.0001 at every seed, magnitude stable (~-.00025), direction never flips.
p_hr: p=.33/.17/.17 — never significant, exactly as in the 4-season rounds.

**Decision.** SHIPS for p_hit only (never ship a calibrator without
demonstrated benefit — p_hr stays raw). Production: orchestration/daily.py
fits an IsotonicRegression at batter-bundle-train time on stored
out-of-sample predictions joined to outcomes (>=10k rows required; the
bundle carries it as cal_hit) and applies it to the p_hit head. Vintage
note: stored walk-forward preds are pre-B2-blend while daily p_hit is
post-blend — the blend moves p_hit only via the 7-class rescale, second-order
vs the calibration signal. Batter bundle invalidated to force retrain.

---

## E8h — 2026-07-17 — model-family suite (RF / PyTorch NN / HGB / ridge / XGB): LightGBM stays

**Setup.** Four new families in modeling/team_models.py, same runs-two-head
structure and sigma squash (rf_runs: 500-tree RandomForest, native NaN;
hgb_runs: sklearn HistGradientBoosting, Poisson; ridge_runs: impute+scale+
Ridge linear floor; nn_runs: PyTorch MLP with the NBA architecture 128-64-32
BatchNorm+Dropout .3, median-impute+standardize — torch installed in the
venv only, deliberately NOT in requirements.txt). Plus xgb_runs rerun.
Walk-forward on v20260716_083741, ablation vs lgbm_runs+8s (8,713 games).
The plan's "no NNs until trees plateau" gate was met by E8a-f.

**Result.** xgb: parity everywhere (E0 replicated). HGB: significantly worse
(acc p=.043, totals p=.009). Ridge: strikingly close (margin MAE 3.4731 vs
3.4778, acc -0.5pp n.s.) — most pick signal is linear in Elo+SP. NN:
REJECTED decisively — worse on ALL four metrics (acc .5431 vs .5612 McNemar
p=.0014; margin MAE 3.5884 p<.0001; AUC -.025 p<.0001; totals +.14
p<.0001) — the NBA "NNs never beat trees on tabular data" lesson replicates
on MLB. RF: the one positive — pick parity with margin MAE 3.4712 vs 3.4778
(p=.043) and AUC +.0035 (p=.088).

**Decision.** LightGBM remains the workhorse; nothing ships. Queued E10:
lgbm+RF margin ensemble (multi-seed gated). Do not revisit NNs without a
structurally different design.

---

## B7 — 2026-07-17 — starter-scoped K/BB/H heads by aggregation: SHIPS

**Hypothesis.** The per-PA model already contains a pitcher product:
predicted starter K = w_sp x sum over the opposing nine of exp_pa x
P(K | vs this SP), with w_sp = the starter's own expected PA share
(clip(SP_IP_PER_START_L10/9, .40, .85)). Ditto BB and hits allowed.

**Result (pooled 2023-2026, 17,374 starter-games where the probable started;
seeds 0/1/2 identical to 3 decimals, all paired-t).**
- K MAE: workload-scaled model **1.812** vs league-w model 1.856 (p<.0001)
  vs SP-marginal baseline 1.888 (p<.0001) vs w-scaled whole-game board sum
  1.876 (p<.0001).
- BB MAE: **1.025** (wsp) vs 1.032 (p<.0001) vs marginal 1.036 (p=.015-.026).
- H allowed MAE: **1.769** (wsp) vs 1.792 (p<.0001) vs marginal 1.819 (p<.0001).
Note the contrast with B1 (rejected): per-SP workload hurts the BATTER
mixing weight but is decisively right for PITCHER-level counts.

**Decision.** SHIPS. migrations/0008 adds pitcher_predictions; the daily
pipeline aggregates and writes starter heads per (game, sp) when the full
nine is predicted; /api/public/pitchers serves sp_exp_k/sp_exp_bb/sp_exp_h
(daily_v1-preferred); the pitchers board now leads with starter-scoped
K/BB/H instead of unlabeled whole-game lineup sums. Evaluation lives in
walkforward_batter's pooled B7 verdicts.

---

## E11/E12 — 2026-07-22 — probability-head suite: log + hv confirmed, sk + iso rejected

First experiments of the literature-driven cycle (roster + designs:
docs/literature_review_2026-07.md). Enabled by the W0.1 harness extension
(win_logloss/win_brier in walkforward metrics; paired per-game log-loss/Brier
tests + --months slice in validation.ablation) — which immediately surfaced
the motivating fact: **the base model's p_home is worse-calibrated than
Elo's** (log loss .6836 vs .6816 pooled; market ≈ .676 from E0).

**Hypothesis.** The documented "sigma runs hot" miscalibration is fixable by
replacing/recalibrating Phi(margin/sigma_train) without touching picks or
margins; the Karlis-Ntzoufras lambda3 identity predicts pure independent-heads
Skellam is overconfident while a dispersion-corrected variance is right.

**Setup.** validation/recalibrate.py: offline transforms over STORED
lgbm_runs+8s predictions @v20260716_083741 (margins untouched -> ablation
isolates the probability change), each fit per month on STRICTLY PRIOR months
pooled (MIN_FIT 1,500 games, pass-through before that — fixes parked-E8c's
in-sample-alpha flaw; the B3/B6 growing-history pattern). Variants: E11a iso
(isotonic), E11b sig (OOS sigma), E11c log (logistic on sigma-scaled margin +
logit of stored Elo p), E12a sk (Skellam, tie mass renormalized), E12b hv
(p = Phi(margin/sqrt(c·(lam_h+lam_a))), c from prior OOS residuals). Seeds
via the stored s1/s2 bases — no retraining anywhere.

**Result (pooled, 8,713 games; log loss / Brier vs base .6836/.2452).**

| variant | log loss | p | Brier | p | AUC delta | verdict |
|---|---|---|---|---|---|---|
| E12a sk | .6917 | <.0001 WORSE | .2487 | <.0001 WORSE | +.0003 (ns) | REJECTED — overdispersion+correlation make pure Skellam overconfident, exactly as predicted |
| E11a iso | .6827 | .185 | .2448 | .208 | **−.0037 (p=.007) WORSE** | REJECTED — step function flattens ranking, no significant calibration gain |
| E11b sig | .6832 | .015 | .2451 | .015 | .000 | confirmed s1 p=.047 / s2 p=.028 — real but smallest; superseded by hv/log |
| E12b hv | .6830 | **.0009** | .2449 | **.0008** | +.0002 (ns) | **CONFIRMED** s1 p=.0047 / s2 p=.0025, direction never flips |
| E11c log | .6813 | **.0071** | .2441 | **.0084** | +.0010 (ns) | **CONFIRMED** s1 p=.019 / s2 p=.008 — largest gain; full effect holds in the Mar–Jun slice (−.0027, p=.0077) |

Diagnostic: hv's gain thins in Mar–Jun (p=.09) — the dispersion correction
pays mostly in-season; log (which blends the better-calibrated Elo signal)
carries the early-season window too.

**Decision.** sk and iso are rejected and must not ship. sig/hv/log all clear
the significance + multi-seed bar as pure probability-head improvements
(picks, margins, totals untouched). **Ship candidate: log**, with the hv⊕log
stack to be tested in the Wave-5 combined round before production wiring
(bundle-carried calibrator at daily train time, the B6 cal_hit pattern; no
model retrain involved). Registry rows: run_kind='offline_recalibration';
stored tags lgbm_runs+{sk8,hv8,sig8,iso8,log8}[_s1|_s2].

---

## E13 — 2026-07-22 — cross-season recency weighting: REJECTED on the selection window

**Hypothesis.** Environment-wide 2026 drift (Elo dips too) suggests
down-weighting older seasons; grid decay^(seasons_ago), decay in {0.8, 0.9}
(Marcel-anchored range), cross-season only — Brown 2008 (month-constant
ability) and Glickman-Stern beta_w~1 both predict within-season decay adds
nothing, so it was not run.

**Setup.** RunsModel gains a decay param (sample_weight on both Poisson
heads); tags lgbm_runs_d8+8s / lgbm_runs_d9+8s @v20260716_083741; selection
on 2023-2025 pooled ONLY (E8d hygiene), 2026 held out.

**Result.** Selection window (7,269 games): base acc .5654 vs d8 .5610 /
d9 .5618 — the incumbent wins outright; margin MAE parity (3.4587 vs
3.4563/3.4559), totals slightly worse. Pooled ablations null on all four
metrics (acc p=.57/.55, margin p=.49/.27, totals p=.16/.49, AUC p=.66/.36).

**Recorded observation (not actionable).** On the 2026 holdout alone both
decays beat the base (.5512/.5478 vs .5402, +0.8..+1.1pp) — directionally
consistent with the drift motivation, but selecting on the holdout is the
exact violation the hygiene rule exists for. Revisit next cycle when 2026 is
a complete season inside the selection window; do not ship on this.

**Decision.** REJECTED; no decay ships; unweighted training stays.

---

## E10 — 2026-07-22 — lgbm+RF margin ensemble: NOT SHIPPED (seed gate)

**Hypothesis.** The parked E8h RF margin-MAE edge (p=.043 single seed)
survives as a 50/50 lgbm+RF margin average (totals stay lgbm; p_home via
prior-months OOS sigma on the ensemble margin).

**Setup.** validation/recalibrate.py rfens variant over stored predictions;
seed pairs (lgbm_runs+8s, rf_runs+8s) x {seed0, s1, s2} — RF seed runs added
for s1/s2. Tags lgbm_rf+ens8[_s1|_s2] @v20260716_083741.

**Result.** Seed 0: margin MAE 3.4723 vs 3.4778 (p=.0009), Brier/log-loss
p=.004/.003, AUC +.0017 (p=.058) — looked like a clear win. Seeds 1/2:
margin MAE −.0017 (p=.31) / −.0026 (p=.11), all other metrics null.
Direction consistent 3/3, magnitude collapses; the seed-0 pairing overstated
the effect roughly 2-3x.

**Decision.** NOT SHIPPED — fails the multi-seed significance gate exactly
as the gate is designed to catch. Closed for this cycle; do not re-run
without new information (more seasons, or an RF variant with a materially
different bias profile). The consistent small directional edge is recorded;
E8h's parked status resolves to REJECTED-for-shipping.

---

## B8a — 2026-07-23 — slot-conditional expected RBI: CONFIRMED, SHIPS

**Hypothesis.** RBI is predictable without base-state data via
r̄(outcome, slot) — the shrunken league mean RBI credited when class c
occurs from lineup slot s — aggregated over the per-PA heads:
exp_rbi = exp_pa x sum_c p_mix[c] x r̄(c, slot). Beating the batter's own
marginal RBI rate shows the head works; beating a slot-only variant shows
the OUTCOME conditioning specifically earns its keep.

**Setup.** r̄ from seasons strictly before each test season (W=300 toward
class-globals; era constants below 10k PAs — never frame-derived).
Baselines: exp_pa x batter's rolling 60-game shrunken RBI/PA (W=150,
searchsorted as-of), and exp_pa x r̄(slot). walkforward_batter
--seasons 2023 2024 2025 2026, seeds 0/1/2, migration 0011. Sanity gates
passed pre-launch: HR r̄ 1.66 (slot 4) / 1.55 (slot 9) ≈ 1 + mean runners
on; league RBI/PA .1146 vs the .115 era constant.

**Result (pooled 158,169 batter-games, paired-t).**

| seed | model | batter-marginal | p | slot-only | p |
|---|---|---|---|---|---|
| 0 | 0.6331 | 0.6363 | <.0001 | 0.6367 | <.0001 |
| 1 | 0.6331 | 0.6363 | <.0001 | 0.6367 | <.0001 |
| 2 | 0.6330 | 0.6363 | <.0001 | 0.6367 | <.0001 |

Direction identical at every seed; magnitudes stable to the fourth decimal.

**Decision.** SHIPS (the significance + multi-seed bar is met, same
character as B7's aggregation wins). Ship work: daily-pipeline r̄ table
(as-of, one SQL aggregate at predict time) + exp_rbi in the batter
aggregation and batter_predictions write; /api/public players/feed columns;
players-page "RBI expected" column with translations. Known v1 limitation
(recorded): slot-average runner context, blind to tonight's specific
on-base environment — the B8b base-state upgrade (statcast reprocess,
migration 0012) is the queued sharpening.

---

## E9a/E9b/E14/B9a/LINEUP_XR — 2026-07-23 — Wave-2 snapshot wave: nothing ships

**Setup.** One rebuild, snapshot v20260723_014637 (17,067 rows x 174 cols,
leakage PASS on 11,854 games; default columns unchanged, so lgbm_runs+8s
@v20260716_083741 carries over as the paired baseline; current pointer
unmoved). One flag per run, ablation pooled + Mar-Jun slice.

**Results (8,713-ish paired; slice = 5,019 games).**

| variant | flag | pooled verdict | Mar-Jun slice |
|---|---|---|---|
| E9a +pri8 | priors | acc .5548 vs .5612, **McNemar p=.029 WORSE**; rest null | **.5471 vs .5553, p=.043 WORSE** |
| E9b +priB8 | priors_blend | null on all metrics (acc p=.48) | null (p=.69) |
| E14 +pyth8 | pyth | null (acc p=.66, AUC +.0009 p=.48) | null (AUC +.0008 p=.60) |
| B9a +def8 | defense | null; totals -.002 (p=.42) — hoped-for gain absent | — |
| +lxr8 | lineup_xr | null; acc -.44pp (p=.084 directional) — as pre-registered | — |

**Decisions.** All five REJECTED; flags stay off; columns remain in the
builder; current snapshot pointer stays at v20260716_083741.

**The load-bearing finding: E9 is closed.** The top queued pick-side lever
(E8g's early-season diagnosis) fails IN its own mechanism window — raw
prior-season team rates actively hurt March-June picks, and the
alpha-atlas-calibrated blend is inert. Reading: Elo already carries kappa=2/3
season carryover, so additional prior-rate columns add only correlated noise
to the linear Elo+SP core the ridge diagnostic identified. Whatever the
market knows early-season that we don't, it is NOT last season's team rates.
Remaining pick-side levers per the locked set: E15 SP_STUFF (process-based
SP quality — SP features carry picks and are noisiest exactly early-season),
the Wave-5 hv(+)log probability ship, and the umpire/totals track. Do not
revisit E9-style team-rate priors without a structurally different
information source (e.g., roster-projection-based priors).
