# Modeling deep-dive — 2026-07-17

A systematic review of both models (team: winner + total runs; player: per-PA batter
model and its derived products), the feature families feeding them, and an
experimental loop over prune/add candidates. Every experiment here follows the
project methodology (§2); anything that ships also gets its own entry in
`docs/model_tuning_log.md` (hard rule).

Trigger for this review (product + modeling):

1. **Player product is undifferentiated on hits.** The players page shows
   "Hits expected" ≈ 0.9–1.2 for essentially everyone, and the hitter-calls skill
   curve itself admits "most starters do get a hit". Need real differentiators
   (HR/RBI for batters, K/BB for pitchers) and a decision on de-emphasizing hits.
2. **Team model trails the market.** Tighten the gap to the closing-line favorite;
   also fix the unintuitive "when we take the other side" record card.
3. **Feature-family audit.** Are the families we compute earning their keep, and
   which new data families (weather, travel, umpire, framing, fielding, base-state)
   are worth acquiring?

---

## 1. Current state (verified 2026-07-17)

### 1.1 Team model

- `lgbm_runs`: two Poisson LightGBM heads (home/away runs) on a shared row;
  margin/total/p_home derived (p_home = Φ(margin/σ), σ = in-sample train residual
  std — known to run slightly hot; no calibration layer exists).
- Hyperparams are the NBA-instinct conservative set (400 trees, lr .03, 15 leaves,
  min_child 50) — **never swept on MLB data**.
- Feature snapshot `team/v20260716_083741`: 16,985 games (2019–2026), 110 built
  columns, 95 model-facing under default flags.
- Pooled walk-forward 2023-04→2026-07 (8,713 games): **win_acc .5612, AUC .5810,
  margin MAE 3.4778, total MAE 3.5331** (registry run 747).
- Elo baseline (rebuilt with 2019+ burn-in): .5563 / .5789 / 3.4801 / 3.5790 —
  the tree model now leads or ties everywhere, decisively on totals.

### 1.2 Team model vs the market (closing no-vig favorite, plausibility-guarded)

Computed from stored predictions × `odds_lines` (n = 7,889 lined regular-season
games 2023–2026):

| slice | n | model acc | market acc | disagree share | disagree record |
|---|---|---|---|---|---|
| pooled | 7,889 | .5605 | .5685 | 19.8% | 746–813 (.4785) |
| 2023 | 2,368 | .5714 | .5735 | 16.5% | 193–198 (.4936) |
| 2024 | 2,385 | .5669 | .5723 | 21.3% | 248–259 (.4892) |
| 2025 | 1,692 | .5538 | .5632 | 21.7% | 175–192 (.4768) |
| 2026 | 1,444 | .5402 | .5602 | 20.4% | 130–164 (.4422) |

Reading: the pooled gap is −0.8pp and **widening — 2026 alone is −2.0pp** and
disagreement picks there run 44%. Elo shows the same 2026 dip (.5416), so the
degradation is environment-wide, not tree-specific. Totals gap vs market:
3.533 vs ~3.466 (halved by the 2019–21 backfill, E7).

Caveat recorded: all 1,445 "closing" lines for 2026 were captured 2026-07-15..17
by the ESPN backfill (ESPN retains the last pregame line, so these are
approximate closing lines, captured retroactively). 2025 coverage stops
2025-08-17 (SBR archive end).

### 1.3 Batter model

- 8-class per-PA LightGBM (OUT/K/BB/HBP/1B/2B/3B/HR), 44 production features
  (48 built; 4 arsenal-cross columns gated off — B4 parked).
- Aggregation: empirical PA-count distribution by (slot, home) × analytic
  closed forms; SP mixture p = w·p_vs_SP + (1−w)·p_vs_league with league w ≈ .576;
  B2 K-blend (α=.5 to batter marginal) shipped.
- 2026 out-of-sample (run 748, 109,249 PAs): per-PA log loss 1.4701 vs marginal
  1.4807 vs league 1.4930. Real skill, monotone in training data.
- **No calibration layer in production** (B3 isotonic parked at 4-season scale,
  turned significant at 8 seasons — confirmation queued, run here as B6).
- **No pitcher model** — the pitchers board sums whole-game opposing-lineup
  batter expectations by `sp_id` live in the API.
- **No RBI output** (no base-runner state anywhere in the schema) and **no
  fielding data at all** (reached-on-error maps to OUT).

### 1.4 The product problem, quantified (2026 season, pa_v3, n=25,887)

Percentiles of the live predictions vs observed starter batter-games:

| stat | p5 | p50 | p95 | p95/p5 | pred mean | obs mean |
|---|---|---|---|---|---|---|
| exp_h | 0.666 | 0.901 | 1.126 | **1.7×** | 0.898 | 0.874 |
| p_hit | 0.513 | 0.633 | 0.721 | 1.4× | 0.627 | 0.6075 |
| exp_tb | 1.025 | 1.472 | 1.943 | 1.9× | 1.475 | 1.442 |
| p_tb2 | 0.253 | 0.367 | 0.462 | 1.8× | 0.363 | 0.352 |
| exp_bb | 0.182 | 0.313 | 0.547 | 3.0× | 0.333 | 0.360 |
| exp_k | 0.500 | 0.870 | 1.292 | 2.6× | 0.879 | 0.882 |
| exp_hr | 0.052 | 0.118 | 0.229 | **4.4×** | 0.126 | 0.124 |
| p_hr | 0.051 | 0.113 | 0.209 | 4.1× | 0.118 | 0.1165 |

Two facts together settle the product question:

1. **Spread**: hits is the *most compressed* stat we publish (1.4–1.7×);
   HR is the most differentiated (4.1–4.4×), K and BB in between (2.6–3.0×).
2. **Skill**: hits is also where the model adds the *least* over a batter's own
   marginal rates (2026 MAE 0.6803 vs 0.6826 baseline — near-parity), while
   BB is the largest persistent edge (0.4723 vs 0.4849), K wins with the B2
   blend, and p_hr has strong ranking power (top decile homers at 18.8% vs
   5.4% bottom decile) with good calibration (Brier .1014 vs .1017 baseline;
   pred HR rate .1183 vs obs .1165).

Decision (product): **de-emphasize hits, lead with HR (and TB/K/BB)** — details
in §5. "Gets a hit" stays as a secondary column (it is honest and calibrated),
but it stops being the headline number.

### 1.5 Feature families in the team snapshot (producer-side inventory)

| family | columns (per side + DIFF) | status |
|---|---|---|
| A. team rolling form | RUNS_PG/RA_PG L10/L30, WOBA_L30, XWOBA_CON_L30, K/BB_PCT_L30, N_PRIOR_GAMES, REST_DAYS, GAME_NUM | on; E4 says dilutes picks |
| B. starting pitcher | SP_KNOWN, SP_N_STARTS, SP_DAYS_REST, SP_IP_PER_START_L10, SP_K/BB_PCT_L10, SP_ERA_L10, SP_WOBA/XWOBA_CON_AGAINST_L10, SP_THROWS_L | on |
| C. bullpen | BP_PITCHES_L3, BP_ERA_L30 | on |
| D. schedule/context | IS_NIGHT, IS_DOUBLEHEADER_G2 (+ rest in A) | on; **no travel features** |
| E. park | PARK_PF_RUNS (runs-only, no handedness) | on |
| F. weather/umpire | TEMP_F, WIND_SPEED_MPH, IS_OPEN_AIR; UMP_K_FACTOR + WIND_OUT_MPH flag-gated **off** (E3 parked) | E6b forecast feed now serves TEMP/WIND pregame |
| G. Elo | ELO_HOME/AWAY/DIFF/P_HOME | on |
| H. lineup strength | LINEUP_WOBA/K/BB/HR/XWOBA_CON/SAMPLE_PA, DEV_WOBA, MISSING_WOBA, N_REG_OUT (E5b shipped); VS_HAND block gated off (E5c rejected) | on |

Batter frame: batter/pitcher shrunken 8-class profiles + platoon splits,
sample sizes, xwOBA-contact, pitcher arsenal (velo, breaking/offspeed %, whiff),
SAME_HAND, IS_HOME, PARK_PF_RUNS; arsenal-cross gated off.

### 1.6 Data families we have but don't use, and don't have at all

Available in-house, unused or under-used:
- **HP umpire** (id+name 100% populated on finals) — UMP_K_FACTOR built, gated off,
  and unavailable at serve time (assignments are published pregame by MLB, but our
  ingest fills them postgame — a serve-path gap, not a data gap).
- **Wind direction** (games.wind_dir postgame) — WIND_OUT_MPH built, gated off;
  pregame serve needs park orientation (E6c, Seamheads has it).
- **Venue coordinates** (0007, for the weather feed) — enables **travel features**
  (distance, time zones) that E4 flagged as the kind of information Elo can't see.
  Never built. → E8e below.
- **Venue scoring drift** — park factor is a 3-prior-season static ratio; a rolling
  venue run environment could catch within-season drift (roof usage, weather
  regimes, humidor changes). → E8f below.
- **Raw Statcast JSON in S3** — includes base-runner state (on_1b/on_2b/on_3b)
  we never parsed into `statcast_pitches`. This is the unlock for RBI modeling.

Not owned at all:
- **Fielding**: no OAA/DRS, no errors/putouts/assists in boxscore lines, and
  EVENT_MAP erases reached-on-error into OUT. Cheapest useful acquisitions:
  (a) Savant OAA leaderboards (annual/monthly CSV import → new reference table),
  (b) errors from `plays` event text parsing, (c) team defensive-efficiency from
  batted-ball outcomes we already have (BABIP-against by team). A team-level DEF
  family is a legitimate E-candidate after this cycle; player-level fielding
  products need (a).
- **Catcher framing** — Savant publishes it; would feed both the totals model
  (called-strike environment) and the batter K head. Queued behind fielding.
- **True closing lines for 2026** — The Odds API or similar would fix the
  approximate-closing caveat; benchmark-only, so low modeling priority.

---

## 2. Methodology (unchanged, restated for this doc)

- **Walk-forward**: expanding window, monthly retrain, test = regular-season
  games of the month, start 2023-04, on snapshot `v20260716_083741` unless a
  rebuild is stated. Pooled n = 8,713 (2023-04 → 2026-07).
- **Pairing/significance**: `validation.ablation` — exact McNemar on picks,
  paired-t on per-game |error| (margin & total), 2000-resample paired bootstrap
  on AUC. Per-comparison p-values, no family-wise correction (stated caveat);
  direction consistency across seeds is required for shipping.
- **Multi-seed**: anything that ships gets seeds 0/1/2 confirmation.
- **Hyperparameter sweep hygiene** (new this doc): the sweep (E8d) selects on
  pooled 2023–2025 only; 2026 is held out untouched until the single chosen
  config is confirmed there, plus multi-seed. This keeps the pooled walk-forward
  honest for the winner.
- **Batter harness**: season-level walk-forward (train < S, test S), per-PA log
  loss vs league/marginal baselines, game-level MAE/Brier on matched
  probable-started games; B1–B4 blend variants computed in-harness.
- Odds are benchmarks only, never features (schema + convention). Nothing here
  changes that.

---

## 3. Experiment battery — team model (E8 series)

Each experiment lists hypothesis → setup → result → decision.
Baselines: `lgbm_runs+8s` and `elo+8s` at v20260716_083741 (stored).

### E8a — feature-family drop-one ablation matrix

**Hypothesis.** E4 (4-season data) showed the ~40 form/bullpen columns dilute
win picks. With 8-season training and the lineup block now shipped, quantify
each family's marginal contribution; prune any family whose removal is
significantly positive or flat on all four metrics (fewer features = less
dilution risk and a cleaner base for new families).

**Setup.** `select_features` gains drop-one profiles (`no_form`, `no_sp`,
`no_bullpen`, `no_lineup`, `no_elo`, `no_park`, `no_weather`, `no_context`) —
still the single source of truth, just richer profiles. One walk-forward per
profile (tag `+noX8`), ablation vs `lgbm_runs+8s`, plus the E4 `slim` profile
rerun on 8-season data (`+slim8`).

**Result** (Δ = drop-family minus full baseline; 8,713 paired games; bold =
significant):

| family dropped | acc Δ | p | margin MAE Δ | p | total MAE Δ | p | AUC Δ | p |
|---|---|---|---|---|---|---|---|---|
| form | −.0010 | .76 | −.0050 | .067 | +.0027 | .35 | **+.0037** | **.022** |
| sp | **−.0094** | **.025** | **+.0156** | **.001** | +.0064 | .14 | **−.0098** | **.001** |
| bullpen | −.0025 | .37 | −.0007 | .73 | +.0029 | .17 | +.0009 | .49 |
| lineup | −.0020 | .60 | +.0036 | .36 | **+.0085** | **.019** | −.0017 | .44 |
| elo | **−.0082** | **.021** | **+.0078** | **.024** | +.0003 | .90 | **−.0065** | **.003** |
| park | −.0016 | .59 | −.0020 | .38 | **+.0099** | **.002** | +.0018 | .22 |
| weather | −.0017 | .58 | +.0017 | .51 | **+.0166** | **<.0001** | −.0003 | .80 |
| context | −.0040 | .13 | −.0004 | .81 | **+.0047** | **.016** | +.0009 | .46 |

Slim rerun (`+slim8` vs full): pick/margin/AUC parity (p=.55/.44/.40), totals
significantly worse (+.0142, p=.004) — E4's conclusion replicates at 8 seasons.

**Reading.** The model is really two models wearing one feature set:
*picks/margin run on SP + Elo only*; *totals run on weather + park + lineup +
context (+ the SP block directionally)*. Bullpen contributes nothing anywhere.
The form block is actively diluting probability ranking — dropping it
significantly improves AUC (+.0037, p=.022) and directionally improves margin
MAE, at no significant cost anywhere.

**Decision.** (a) Bullpen and form are confirmed non-contributors for picks;
form is a *harmful* dilutor for AUC. no_form went to multi-seed confirmation
(seeds 1/2) — see results log — before any default flip. (b) No family is
prunable for the totals product; weather is its most valuable family, which
retroactively justifies E6b (forecast serving). (c) Future pick-model features
must beat the SP+Elo core, not the aggregate.

### E8b — E3 retest: umpire K factor + out/in wind at 8 seasons

**Hypothesis.** The ~−.005 totals-MAE effect that appeared three times at
p=.13–.25 on 4-season data clears significance with 8-season training and the
2026 window added (tuning log predicted "likely becomes shippable as seasons
accumulate").

**Setup.** `--enable-flags umpire,wind_out --tag +uw8`, ablation vs baseline,
totals MAE primary. Note the serve-path asymmetry: both columns are NaN at
prediction time today (umpire unknown in our pregame ingest; wind direction
needs E6c park orientation), so a positive result ships the flags for the
backtest/registry path only, with the serve gap documented as its own work item.

**Result.** Total MAE 3.5303 vs 3.5331 (p=.229) — the ~−.003 effect appears a
**fourth** time and fails significance a fourth time. AUC +.0022 (p=.104),
margin −.0022 (p=.30), acc −.0017 (p=.55). The effect did not strengthen with
8-season training the way E7 predicted.

**Decision.** Flags stay off. Retired as a standing retest — do not run E3
again until the serve path exists (pregame umpire capture + E6c park
orientation), at which point it rides along with that ship decision.

### E8c — Elo/LGBM probability blend (offline, then model class if it earns it)

**Hypothesis.** lgbm_runs and Elo tie on pooled pick accuracy (.5605/.5604) but
disagree on ~18% of games; a probability blend reduces variance and may beat
both (the cheap, principled version of "close the market gap" before buying
new data). This is NOT the rejected E1 classifier head — picks can flip.

**Setup.** Offline sweep α ∈ [0,1] over stored predictions, per-season +
pooled accuracy, McNemar vs both parents. Ship path if positive: a stacked
model type in `team_models.py` + walk-forward + multi-seed.

**Result.** Best α=.3 (elo-leaning): pooled .5638 vs lgbm .5612 (McNemar
p=.57) and vs elo .5594 (p=.13). Directionally positive at every α in
[.2, .6], but never significant — and the α choice itself is in-sample.
A related diagnostic: when lgbm and Elo agree (77% of games) accuracy is
.5792; when they split it is .5074 — coin-flip. The models genuinely
disagree only where neither knows anything.

**Decision.** Parked, not shipped (would violate the significance bar). The
agreement diagnostic is product-usable though: lgbm/elo split is a
low-confidence signal that costs nothing to surface. Revisit the blend as
seasons accumulate.

### E8d — first hyperparameter sweep on MLB data

**Hypothesis.** The NBA-carryover conservative params were never tuned for MLB;
a modest sweep (leaves, min_child_samples, lr×trees, colsample) finds a config
that beats the incumbent on 2023–2025 pooled walk-forward and confirms on the
held-out 2026 + seeds.

**Setup.** Custom in-process sweep (one snapshot load, 15 configs), selection
on pooled 2023–2025 only (7,269 games); winner would then confirm on the
held-out 2026 + seeds.

**Result.** **The incumbent wins outright** (.5654 acc; next best .5634).
Deeper trees degrade monotonically (31 leaves .5606, 63 leaves .5565);
slower learning (800×.015), stronger regularization, and column-sampling
variants all land within noise below the incumbent. `num_leaves: 7` edges
margin/total MAE (3.4548/3.5253 vs 3.4587/3.5299) but costs 0.4pp accuracy.

**Decision.** Keep the incumbent hyperparameters; nothing to confirm on 2026.
The NBA-instinct conservative regime is validated on MLB data, and
hyperparameters are ruled out as the source of the market gap. Do not re-sweep
until the feature set changes materially.

### E8e — travel features (new family, from venue coordinates)

**Hypothesis.** Travel burden (distance since last game, time-zone shift,
first-game-of-trip) is information Elo cannot see (E4's explicit ask). Adding a
flag-gated TRAVEL block improves picks/margin without hurting totals.

**Setup.** New columns in team_features (`TRAVEL_KM` haversine from the
previous game's venue, `TRAVEL_TZ_DELTA` signed zone shift from longitude, per
side + DIFF), flag `travel` default off, snapshot rebuild `v20260717_023946`
(121 cols, **leakage gate PASS** on 11,854 games), walk-forward with
`--enable-flags travel`, cross-snapshot ablation vs `lgbm_runs+8s` (identical
default features, so the baseline carries over).

**Result.** Null on all four metrics: acc −.0020 (p=.45), margin MAE −.0022
(p=.29), total MAE +.0013 (p=.51), AUC +.0010 (p=.42).

**Decision.** Rejected; flag stays off (columns remain in the builder for
future revisits). REST_DAYS + Elo evidently already carry what MLB travel
burden is worth. The E4 "information Elo can't see" shortlist narrows to
early-season priors and framing/umpire serve paths.

### E8f — venue scoring drift (totals-focused)

**Hypothesis.** A rolling venue run environment (last ~40 games at the venue vs
league, shrunk) captures within-season scoring drift that the static
3-prior-season park factor misses; helps total MAE (the E6 "venue scoring
drift" queue item).

**Setup.** `VENUE_ENV_L40` (last-40-games venue total-runs vs trailing-365d
league mean; game-level column), flag `venue_env` default off, same rebuilt
snapshot as E8e, walk-forward + ablation on totals MAE. Also a combined
travel+venue_env run.

**Result.** Total MAE 3.5319 vs 3.5331 (p=.64) — the hypothesized totals gain
is absent. AUC +.0023 (p=.091) is directionally interesting but not the
target and not significant. Combined run: null everywhere.

**Decision.** Rejected; flag stays off. The static 3-prior-season park factor
plus game-time weather already capture what the rolling venue environment
sees. The remaining totals ideas requiring NEW information: game-day roof
open/closed status, forecast wind direction vs park orientation (E6c), and
umpire serve path — all acquisition projects, not feature rearrangements.

### E8h — model-family suite: RF, PyTorch NN, sklearn HGB, ridge, XGB rerun

**Hypothesis.** With the feature side exhausted (E8a–f), test whether a
different learner family extracts more from the same snapshot — the
hoopmodel/NBA pattern (LightGBM vs XGBoost vs RandomForest vs a PyTorch MLP
vs a linear floor). The plan's gate — "no NNs until trees plateau" — is met
by this cycle's results.

**Setup.** `modeling/team_models.py` gains four families in the same
runs-two-head structure: `rf_runs` (RandomForest, 500 trees, min_leaf 15,
native-NaN), `hgb_runs` (sklearn HistGradientBoosting, Poisson loss,
conservative), `ridge_runs` (impute+scale+Ridge — linear floor), `nn_runs`
(PyTorch MLP with the NBA architecture: 128→64→32, BatchNorm+ReLU+Dropout .3,
Adam 1e-3, 80 epochs, median-impute + standardize; torch is CPU-only and
deliberately kept out of requirements.txt). Plus an `xgb_runs` rerun on the
8-season snapshot. Walk-forward + ablation vs `lgbm_runs+8s` each.

**Result** (vs lgbm_runs+8s, 8,713 paired games):

| family | acc | AUC | margin MAE | total MAE | verdict |
|---|---|---|---|---|---|
| xgb | .5608 (p=.90) | .5813 | 3.4812 | 3.5373 | parity — E0 replicated at 8 seasons |
| sklearn HGB | .5542 (**p=.043**) | .5770 | 3.4845 | 3.5428 (**p=.009**) | significantly worse |
| RandomForest | .5607 (p=.89) | .5845 (p=.088) | **3.4712 (p=.043)** | 3.5381 | pick parity, real margin-MAE edge |
| ridge | .5566 (p=.25) | .5820 | 3.4731 | 3.5335 | startlingly close — the pick signal is mostly linear |
| PyTorch MLP | .5431 (**p=.0014**) | .5564 (**p<.0001**) | 3.5884 (**p<.0001**) | 3.6743 (**p<.0001**) | decisively worse everywhere |

**Decision.** LightGBM stays the workhorse. The NBA lesson replicates on MLB
exactly: **the NN loses to trees on tabular sports data by wide, significant
margins** — do not revisit without a structurally different design (e.g.
embeddings over raw sequences, not an MLP on the tabular row). RF is the one
positive surprise (margin MAE p=.043, AUC direction) — parked as an
lgbm+RF margin-ensemble candidate (E10), multi-seed gated. The ridge result
is diagnostic gold: most of the extractable pick signal is linear in Elo+SP,
which is why feature-side and learner-side changes keep failing to move
accuracy.

### E8g — early-season diagnostic (analysis only)

**Question.** Is the widening market gap concentrated early-season (April 2026
window win_acc was .5102) where features are NaN-heavy and shrinkage is light?
Per-month gap decomposition from stored predictions.

**Result** (7,717 lined games, model−market accuracy gap by month-of-season):

| month | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct |
|---|---|---|---|---|---|---|---|---|
| gap | −5.6pp | −1.8pp | −0.3pp | −3.3pp | −0.6pp | **+2.1pp** | +0.1pp | +13pp (n=15) |

The model **beats the market from August on** and loses it March–June; 2026's
−2.0pp season gap is entirely first-half (Mar −9.2, Apr −3.3, May −1.7,
Jun −2.5, Jul +1.2 so far). Also: in disagreement games, no model-confidence
bucket rescues the picks (all < .50), so "trust our disagreements when
confident" is not a viable rule.

**Decision.** Early-season handling is the highest-leverage open direction for
the pick gap (the PROJECT_PLAN §8 item — heavier April shrinkage / prior
carryover with decay — was never implemented; note E2's cross-season *form
windows* failed, but priors-with-decay is a different mechanism). Queued as
E9 with a concrete design; not attempted inside this cycle.

---

## 4. Experiment battery — player model (B series continued)

### B6 — B3 confirmation: isotonic calibration of p_hit/p_hr at 8 seasons

**Hypothesis.** The E7 observation (p_hit Brier .23349 vs .23376, p<.0001
pooled with 8-season training) replicates across seeds and holds on the 2026
window → ship a production calibrator (fit on stored prior-season predictions
at bundle-train time).

**Setup.** `walkforward_batter --seasons 2023 2024 2025 2026 --no-preds`,
seeds 0/1/2, pooled B3 verdict from the harness (156,837 batter-games).

**Result.** p_hit Brier .23380/.23385/.23383 vs raw .23408/.23410/.23406 —
**p<.0001 at every seed**, stable magnitude, direction never flips. p_hr:
p=.33/.17/.17 — never significant (consistent with every earlier round).

**Decision.** **SHIPS for p_hit only.** Production: the batter bundle now
carries an isotonic calibrator fit at train time on stored out-of-sample
predictions vs outcomes (≥10k graded rows required), applied to the p_hit
head in the daily aggregation. p_hr stays raw — never ship a calibrator
without demonstrated benefit (NBA E13). Tuning-log entry: B6.

### B7 — starter K/BB heads by aggregation (new pitcher product)

**Hypothesis.** The per-PA model already contains a pitcher product: predicted
starter strikeouts = Σ over the opposing lineup of (expected PAs vs the SP) ×
P(K | vs SP). This beats (a) the SP's own shrunken marginal K rate and (b) the
whole-game approximation w·Σexp_k currently implied by the pitchers board.
Same construction for BB and hits allowed.

**Setup.** Extend `walkforward_batter` with a per-(game, SP) evaluation:
predicted starter K/BB/H-allowed vs `pitcher_game_lines` actuals, baselines =
the SP's own shrunken marginal rates aggregated identically and the w-scaled
whole-game board sum. Variants: league-constant w vs per-SP workload share
(`clip(SP_IP_PER_START_L10/9, .40, .85)`). Seasons 2023–2026, seeds 0/1/2
(17,374 starter-games).

**Result** (pooled MAE; all paired-t p<.0001 unless noted, all seeds agree):

| head | workload-scaled model | league-w model | SP-marginal | board sum (w-scaled) |
|---|---|---|---|---|
| K | **1.812** | 1.856 | 1.888 | 1.876 |
| BB | **1.025** | 1.032 | 1.036 (p=.015–.026) | — |
| H allowed | **1.769** | 1.792 | 1.819 | — |

Notable: per-SP workload — rejected for the *batter* mixing weight (B1) —
is decisively right for *pitcher-level counts*, where innings variance
dominates.

**Decision.** **SHIPS.** `migrations/0008` adds `pitcher_predictions`; the
daily pipeline writes starter-scoped heads per (game, SP) with the
workload-scaled aggregation; `/api/public/pitchers` serves them
(`sp_exp_k/bb/h`); the pitchers board leads with a real starter pitching
line instead of unlabeled whole-game lineup sums. Tuning-log entry: B7.

### B8 — RBI: feasibility decision

To be precise about what is and isn't missing: **actual RBIs are fully
ingested** (`plays.rbi` per event, `batter_game_lines.rbi` per game) and
already displayed on player pages. The gap is *prediction*: RBI is a
context stat — it depends on how many runners are on base when you bat —
and no curated table carries per-PA base-runner state (plays has no
base-state columns; curated statcast_pitches has no on_1b/2b/3b).

Two implementation tiers, in order:

1. **v1, buildable from data we already own** (no acquisition needed):
   `plays` records the RBI count *of each event*, so we can estimate
   r̄(outcome, slot) = shrunken mean RBI when outcome class c occurs from
   lineup slot s (optionally conditioned on the team's on-base environment),
   and aggregate E[RBI] = Σ_c E[n_c] × r̄(c, slot) from the per-PA outcome
   distribution — the same closed-form pattern as every other head. Validated
   in walk-forward against a batter-marginal RBI baseline before it ships.
   Limitation: slot-average runner context, blind to tonight's specific
   lineup on-base quality above/below slot norms.
2. **v2, needs the S3 reprocess**: the archived raw Statcast CSVs carry
   on_1b/on_2b/on_3b — reprocessing (no re-scrape) gives true per-PA
   base-state, upgrading r̄ to base-state-conditional run-in probabilities
   and enabling lineup-specific runners-on distributions.

**Decision: v1 queued as the next batter-side experiment (B8a); the S3
base-state reprocess queued behind it (B8b).** Not attempted inside this
cycle; the product meanwhile leads with HR (validated).

### B9 (assessment) — fielding

No fielding data exists in the DB and none is used anywhere (§1.6). Cheapest
path to value, in order: team defensive efficiency from our own batted-ball
data (helps the TEAM model's run-prevention side), then Savant OAA import for
player-level surfaces. Queued behind B7/B8; no experiment this cycle.

---

## 5. Product changes (SHIPPED this cycle — site, API, and pipeline deployed)

1. **Players page hitter board** now leads with "Homers" (p_hr — 4.4× spread,
   real ranking power) and "2+ total bases" (p_tb2); "Gets a hit" is demoted
   to a de-emphasized last column; the bare "Hits expected" number (0.9–1.2
   for everyone) is **removed**. A footnote explains why: most starters get a
   hit on any night, so hit probability runs 50–70% for nearly everyone.
2. **Pitchers board** now shows a real starter line — "Ks expected", "Walks
   expected", "Hits allowed expected" — from the validated B7 starter-scoped
   heads (`sp_exp_k` avg ≈ 4.6 vs the old unlabeled whole-game ≈ 7.8), sorted
   by starter Ks. Copy and footnote rewritten to say exactly what the numbers
   cover.
3. **Record page "take the other side" card rewritten**: metric unchanged
   (W–L), copy now reads *"our picks against the market favorite / we called
   the upset N times this window — this is how those calls went."* Dead-even
   market lines no longer count as disagreements (consistency fix with the
   skill curve).
4. **Record page hitter section reframed around HR**: a new "Skill curve —
   the home-run watch" chart (each night's top-5 HR picks graded against the
   night's base rate, cumulative homers above chance) leads the section; the
   hit-calls curve stays as the secondary, explicitly labeled the easier
   test. `/api/public/batter-results` extended with the per-day HR-watch
   grading fields.
5. **Not shipped, documented**: E[RBI] (blocked on base-state data — B8),
   fielding surfaces (no data — B9), lgbm/elo-split "low confidence" badge
   (candidate follow-up; the "coin flip" badge already covers ≤55%).

---

## 6. Results log

All team runs: snapshot `v20260716_083741` unless noted, expanding monthly
walk-forward 2023-04→2026-07, n=8,713 paired regular-season games, ablation =
`validation.ablation`. Tags are stored model_types in `model_predictions`.

| run | tag | acc | AUC | margin MAE | total MAE | verdict |
|---|---|---|---|---|---|---|
| baseline | `lgbm_runs+8s` | .5612 | .5810 | 3.4778 | 3.5331 | — |
| Elo baseline | `elo+8s` | .5563 | .5789 | 3.4801 | 3.5790 | — |
| E8b ump+wind | `+uw8` | .5595 | .5832 | 3.4756 | 3.5303 | 4th insignificant totals result (p=.23) → flags stay off, retest retired until a serve path exists |
| E8a slim | `+slim8` | .5592 | .5826 | 3.4752 | 3.5473 | picks parity, totals −(p=.004) → full stays |
| E8a drop-one ×8 | `+no*8` | — | — | — | — | SP+Elo carry picks; weather/park/lineup/context carry totals; bullpen inert; form dilutes AUC (see §3) |
| E8a no_form seeds | `+noform8_s1/s2` | s1 +.0036 | s1 +.0024 (p=.13) | — | — | **AUC direction flips at seed 2 (−.0006)** → seed noise; no default flip. Form confirmed inert-to-harmful for picks, but removal is not a robust win |
| E8d sweep (15 cfgs, 2023–25 only) | in-process | best = incumbent .5654 | — | — | — | incumbent hyperparams validated; deeper trees monotonically worse |
| E8c blend (offline) | α=.3 | .5638 pooled | — | — | — | +.26pp vs lgbm, p=.57 → parked; lgbm/elo split games are coin-flips (.5074) — usable as a low-confidence signal |

E8g (diagnostic): the market gap is a first-half-of-season phenomenon
(Mar −5.6pp → Aug +2.1pp); model beats the market Aug–Oct. Early-season
priors/shrinkage (E9) is the top queued pick-side experiment.

| E8e travel | `+trav` @v20260717_023946 | .5592 | .5820 | 3.4756 | 3.5344 | REJECTED — null on all four (p≥.29) |
| E8f venue env | `+venv` @v20260717_023946 | .5600 | .5833 | 3.4764 | 3.5319 | REJECTED — totals p=.64 |
| E8e+f combined | `+tv` @v20260717_023946 | .5607 | .5816 | 3.4770 | 3.5314 | null |
| E8h xgb rerun | `xgb_runs+8s` | .5608 | .5813 | 3.4812 | 3.5373 | parity with lgbm (E0 replicated) |
| E8h sklearn HGB | `hgb_runs+8s` | .5542 | .5770 | 3.4845 | 3.5428 | worse: acc p=.043, totals p=.009 |
| E8h RandomForest | `rf_runs+8s` | .5607 | .5845 | **3.4712** | 3.5381 | acc parity; margin MAE better p=.043, AUC +.0035 (p=.088) — parked as ensemble candidate |
| E8h ridge floor | `ridge_runs+8s` | .5566 | .5820 | 3.4731 | 3.5335 | remarkably close — the pick signal is mostly linear (Elo+SP) |
| E8h PyTorch MLP | `nn_runs+8s` | .5431 | .5564 | 3.5884 | 3.6743 | REJECTED — worse everywhere, all p≤.0014 (NBA lesson replicated) |

Batter rounds (pooled 2023–2026, seeds 0/1/2):

- **B6 (=B3 confirm)**: p_hit isotonic Brier −.00025 at p<.0001 every seed →
  **SHIPPED** (p_hit only; p_hr never significant). Calibrator lives in the
  batter bundle, fit on 156,837 graded stored predictions.
- **B7 starter heads**: K MAE 1.812 (workload-scaled) vs 1.888 SP-marginal;
  BB 1.025 vs 1.036; H 1.769 vs 1.819 — all seeds, all p≤.026 →
  **SHIPPED** (migrations/0008, daily aggregation, API + board).

---

## 7. Conclusions & decisions

**Are we using the correct features?** Mostly yes, and we now know *which
features serve which product*. The pick model is effectively SP + Elo; the
totals model is effectively weather + park + lineup + context. Bullpen is
dead weight everywhere (kept only because removal buys nothing either);
form is dead weight for picks and mildly useful for totals. Nothing in the
current families should be pruned (no removal wins robustly across seeds),
and no cheap new family (travel, venue drift) or alternative learner earns
a slot. Hyperparameters are validated as-is.

**Where the remaining pick gap lives.** The −0.8pp pooled gap to the closing
line is a March–June phenomenon; the model already beats the market
August–October. The highest-leverage queued work, in order:

1. **E9 — early-season priors** (never implemented): heavier shrinkage toward
   priors in April, prior-season *rates* carried with decay (distinct from
   E2's rejected cross-season form windows), and possibly market-free
   preseason team priors (projected rosters). Direct evidence: E8g.
2. **Serve-path acquisitions** (turn parked features into live ones):
   pregame HP-umpire capture (statsapi officials appear pregame), E6c park
   orientation (Seamheads) for WIND_OUT, game-day roof status. E3's totals
   effect (~−.003, 4× directionally positive) only matters once servable.
3. **B8 — RBI**: a v1 needs no new data — `plays.rbi` per event gives
   slot-conditional RBI-per-outcome rates, so E[RBI] = Σ E[n_c] × r̄(c, slot)
   is a closed-form head over the existing per-PA model (B8a, walk-forward
   gated). The S3 raw-Statcast reprocess (on_1b/2b/3b) upgrades it to true
   base-state conditioning (B8b).
4. **B9 — fielding/defense**: team defensive efficiency from our own
   batted-ball data first (feeds run-prevention), Savant OAA import for
   player surfaces later. No fielding data exists in the DB today.
5. **RF ensemble check** (from E8h): RF margin-MAE edge (p=.043 single seed)
   + AUC direction suggests a small lgbm+RF margin average could be worth
   one experiment (E10 candidate), multi-seed gated.

**What shipped from this cycle**: B6 (p_hit isotonic calibration in the
daily bundle), B7 (starter-scoped K/BB/H heads: migration 0008, daily
aggregation, API, board), the product reframing around differentiating
stats (HR/TB leading batters, K/BB leading pitchers, hits de-emphasized,
HR-watch skill curve), and the record-page market-card copy fix. Model picks
and totals themselves are unchanged — every team-side candidate failed the
significance bar, which is the honest outcome of a systematic loop on a
market this efficient.

**Methodology debt recorded**: E6b (forecast feed) shipped 2026-07-16
without its own tuning-log entry — noted here and rectified by reference;
per-comparison p-values remain un-corrected for the family of tests (stated
caveat, mitigated by multi-seed direction-consistency gates); 2026 "closing"
lines are retroactive ESPN captures (approximate closers).
