# Modeling deep-dive — 2026-07-23: the literature-driven cycle

A full experiment cycle run against the pick gap to the closing-line market
favorite (pooled −0.8pp, 2026 −2.0pp, concentrated March–June per E8g), built
from a user-gated literature review rather than ad-hoc candidates. Every
experiment followed the project methodology (walk-forward + `validation.ablation`
+ seeds 0/1/2 + tuning-log entry; selection on 2023–2025, 2026 confirm-only).
Individual tuning-log entries: E11/E12, E13, E10, E9a–LINEUP_XR (Wave 2), B8a,
E15, W5. Companion records: `docs/literature_review_2026-07.md` (sources,
approvals, locked experiment set), `docs/alpha_atlas_2026-07.md`,
`docs/umpire_crew_study_2026-07.md`.

Trigger: the record page showing ~53% winners called vs ~56% for the market
favorite (the 2026 slice of the standing gap), plus the queued E9/B8/B9
closeouts from the 2026-07-17 deep-dive.

---

## 1. Process: the gated literature review

Multi-agent pipeline: 7 discovery lanes verified sources (venue, year,
citations, working links, access level), then one summarizer agent per source
produced Objective/Method/Results/Conclusions + proposed experiments; the user
approved/denied each summary in batch, denials replaced from a bench until 10
were approved (3 rounds, 18 summaries total).

**Approved (5 academic / 5 practitioner):** Brown 2008 (AoAS, EB shrinkage) ·
Bukiet-Harold-Palacios 1997 (Oper. Res., Markov lineups) · Deshpande & Wyner
2017 (JQAS, framing) · Karlis & Ntzoufras 2003 (JRSS-D, bivariate Poisson) ·
Soto-Valero 2016 (IJCSS, MLB win-loss ML) · Savant OAA methodology ·
UmpScorecards methodology · Carleton stabilization points · FanGraphs
Stuff+/Location+/Pitching+ primer · Retrosheet game-log/umpire documentation.

**Denied:** Dixon-Coles 1997, Bayesball 2009, Glickman-Stern 1998, The Book,
Marcel, 538 mlb-elo, Tango RE24, Savant catcher framing. Revealed preference:
MLB-native + full primary access + directly actionable; recipes whose content
was already extracted and non-MLB effect magnitudes were dropped.

Corrections found during verification: Healey is TKDE **2015**; Soto-Valero is
single-author; 538's methodology page is dead (GitHub README survives);
Karlis-Ntzoufras open author PDFs exist; UmpScorecards moved to the ABS zone
definition in 2026.

## 2. Baseline (unchanged from 2026-07-17)

`lgbm_runs+8s` @v20260716_083741, pooled 2023-04→2026-07 (8,713 games):
win_acc .5612, AUC .5810, margin MAE 3.4778, total MAE 3.5331. New this cycle
(W0.1 harness): win log loss .6836 / Brier .2452 — **worse-calibrated than
Elo** (.6816/.2443), market ≈ .6780 on lined games. That inversion became the
cycle's pivot.

## 3. Wave 0 — infrastructure (all landed)

- **Harness**: `win_logloss`/`win_brier` in walkforward; paired per-game
  log-loss/Brier tests + `--months` slice in ablation — the metrics that make
  probability-only changes measurable at all.
- **Officials serve path**: migration 0009 `game_officials`; parser keeps all
  four umpires (was HP-only); S3 GUMBO re-parse recovered 17,283 full crews
  (100% agreement with `games.hp_umpire_id`); a pregame probe runs at every
  pipeline tick. Day-one probe data: officials post progressively through the
  afternoon (1 game at 14Z → +4/+3/+5/+1 at 18/20/21/22Z), and
  `schedule?hydrate=officials` works — no per-game fetches needed.
- **Retrosheet** (0010): 66,494 games 1998–2025, 99.6–100% full four-umpire
  crews in the modern era, plus team K/BB totals per game.
- **Alpha atlas**: reliability constants fitted from our own data
  (α(n)=n/(n+k)): team-offense K k≈515 PA (~2 weeks), BB ≈1,265, BABIP-routed
  rates 2,600–4,600 PA — the E9b blend schedule, measured not guessed.

## 4. Wave 1 — probability suite (the cycle's team-side win)

Offline transforms over stored predictions, fit on strictly-prior months
(fixing parked-E8c's in-sample flaw); seeds via the stored s1/s2 archives.

| variant | pooled log loss (vs .6836) | verdict |
|---|---|---|
| E12a Skellam | .6917, p<.0001 WORSE | REJECTED — independent-Poisson overconfidence, exactly as K&N's λ₃ identity predicts |
| E11a isotonic | AUC −.0037 (p=.007) | REJECTED — flattens ranking, no significant calibration gain |
| E11b OOS σ | .6832 (p=.015) | confirmed, smallest |
| E12b hetero-σ | .6830 (p=.0009; s1/s2 .0047/.0025) | CONFIRMED |
| **E11c log** | **.6813 (p=.0071; s1/s2 .019/.008)** | **CONFIRMED — the ship candidate; full effect holds Mar–Jun (−.0027, p=.0077)** |

Also closed: **E13** recency decay (incumbent wins the 2023–25 selection
window outright; the 2026-holdout observation that both decays beat the base
by +0.8–1.1pp is recorded for next cycle, not acted on) and **E10** lgbm+RF
ensemble (seed gate: the seed-0 margin edge p=.0009 collapsed to p=.31/.11 at
s1/s2 — the gate doing precisely its job).

## 5. Wave 2 — snapshot wave: E9 closed

One rebuild (v20260723_014637, 174 cols, leakage PASS), one flag per run,
baseline carried over cross-snapshot.

| variant | pooled | Mar–Jun slice |
|---|---|---|
| E9a PRIOR_* | acc **p=.029 WORSE** | **p=.043 WORSE** |
| E9b BLEND_* (atlas ks) | null | null |
| E14 PYTH/LOG5 | null | null |
| B9a DEF (BABIP-against, xHits-saved) | null (totals p=.42) | — |
| LINEUP_XR (Bukiet 24-state chain) | null (as pre-registered) | — |

**The load-bearing negative:** the cycle's top queued hypothesis — E9
early-season priors, the one lever with direct E8g evidence — fails *inside
its own mechanism window*. Elo already carries κ=2/3 of prior-season strength;
additional team-rate priors are correlated noise on the linear Elo+SP core the
ridge diagnostic identified. Whatever the market knows in March–June that we
don't, it is not last season's team rates. Do not revisit without a
structurally different source (roster-projection priors).

## 6. B8a — expected RBI: SHIPPED end-to-end

r̄(outcome, slot) (W=300, era-constant floors) over the per-PA heads:
exp_rbi = exp_pa × Σ_c p_mix[c]·r̄(c, slot). Pooled 158,169 batter-games,
seeds 0/1/2: **0.6331 vs 0.6363 (batter-marginal) and 0.6367 (slot-only) RBI
MAE, p<.0001 everywhere** — beating slot-only proves the outcome conditioning
itself. Shipped through migration 0011, the shared `modeling.batter_model`
r̄ machinery, the daily aggregation, `/api/batters` + public player endpoints,
and both hitter boards (EN "RBI expected" / JA 打点期待値). Deployed and
verified live. Known v1 limit: slot-average runner context — the B8b
base-state upgrade is queued with its data now in place.

## 7. Wave 3 — acquisitions and E15

- **B8b reprocess**: all 1,446 archived Statcast days re-parsed (5.1M pitches)
  into 22 new columns — true base-out state (on_1b/2b/3b), score state, zone
  bounds (sz_top/bot), spray, alignments, all fielder identities, spin_axis.
  Archive-only by design (Savant retro-revises); early-2019 lacks
  sz/alignments/spin in the archive itself (era gap, documented).
- **B9b OAA import** (0013): 29,418 rows 2016–2026, season + month buckets.
  Two live gotchas caught: the season params everyone would guess are silently
  ignored (`year` is honored; the loader now cross-checks the CSV's year
  column), and success rates arrive as percent strings. Bonus: infield OAA is
  backfilled to 2016 — the "2020+ only" caveat is outdated.
- **E15 SP stuff/location/pitching** (0014): per-pitch LightGBM run-value
  models (target `delta_run_exp`), each season scored by strictly-prior-season
  models; 128k pitcher-games. Feature columns = trailing ~1,500-pitch as-of
  means (min 80). **Picks: null pooled AND Mar–Jun** — the process-quality
  early-season thesis fails. **Totals: 3.5281 vs 3.5331 (p=.070)** — the
  cycle's best totals direction, parked without seed-spend (the E3 lesson).
  The sp_stuff⊕defense combined arm came out *weaker* (p=.37) — closed.

## 8. Wave 5 — combined round and the production ship

- **hv⊕log stack**: better than log at every seed, never significantly
  (p=.075/.083/.115) → simpler `log` ships; hvlog is the standing candidate as
  seasons accumulate.
- **2026 holdout** (selection hygiene): log .6872 vs raw .6995 (p=.016) — the
  raw head's miscalibration was worst in the current season and the ship
  recovers most of it.
- **Production**: bundle-time logistic calibrator (`cal_p`: fit on the 8,713
  graded walk-forward games; σ=4.466, coef [.73 margin-z, .50 elo-logit]),
  applied to the served lgbm p_home only; picks/margins/totals untouched; raw
  fallback + tripwire; pre-calibrator bundles retrain once. Deployed and
  verified live (5/5 slate games shrunk toward Elo; +1.5-run margin at even
  Elo: .631 raw → .570 served). Record-page copy explains it (EN/JA).
- **Benchmark vs closing lines** (7,885 lined games): log loss .6842 → .6817
  vs market .6780 — **~40% of the probability gap to the market closed**; the
  Elo-inversion fixed (.6817 vs elo .6818); pick agreement with the market
  rose .795 → .832 with accuracy unchanged at .5607 (calibration moves
  probability honesty, not sides — the crossings live in the coin-flip band
  E8c measured at .5074).

## 9. Umpire crew study (Wave-4 prep, from Retrosheet)

- **Rotation solved**: HP ← previous-game 1B at P=.966 (full counterclockwise
  cycle, every step ≥.925); rotation alone names the HP umpire for ~87–88% of
  games across 28 seasons. With the live probe catching posted assignments
  3–6h pregame, the serve path is essentially closed.
- **The sobering half**: per-ump K-factor year-over-year r collapsed
  .31 (1998–2006) → .14 → **.10 (2016–2024)** with between-ump spread
  shrinking monotonically — Mills' monitoring convergence on our own data,
  and a mechanistic explanation for E3/E8b's four insignificant attempts.
  The **BB factor holds at ~.29** → the Wave-4 feature leads with BB, shrinks
  K hard, and expects small effects (2026's ABS challenges clip further).
- Bridge audit: .976 mean date-level name agreement vs the API archive.

## 10. Results log (stored tags)

Team @v20260716_083741: `+sk8/+hv8/+sig8/+iso8/+log8/+hvlog8` (+_s1/_s2),
`lgbm_rf+ens8` (+seeds), `lgbm_runs_d8+8s/d9+8s`, `rf_runs+8s_s1/_s2`.
Team @v20260723_014637: `+pri8/+priB8/+pyth8/+def8/+lxr8`.
Team @v20260723_030056: `+stuff8`, `+sd8`. Batter: B8a verdicts in-harness
(seeds 0/1/2), exp_rbi in `batter_predictions` from ship date. New tables:
game_officials, retrosheet_gamelogs, oaa_import, pitch_stuff_games; widened:
statcast_pitches (22 cols), batter_predictions (exp_rbi). Migrations
0009–0014. Docs: literature_review, alpha_atlas, umpire_crew_study, this file.

## 11. Conclusions

**The central finding: against this market, the recoverable edge in public
performance data was calibration, not information.** Six new feature families
(priors, blends, Pyth/Log5, defense, lineup structure, pitch physics),
recency weighting, and an ensemble all closed null-or-harmful with recorded
verdicts — while the probability head, a pure modeling change, confirmed at
every seed, on the untouched 2026 holdout, and against the closing line. The
Elo+SP linear core identified by the ridge diagnostic is saturated; the
market's residual March–June edge (−0.9pp picks, .0037 log loss on lined
games) lives in information we have not tried — most plausibly
roster/projection priors and assignment/lineup timing.

**Shipped this cycle**: the calibrated probability head (pipeline + record
copy), B8a expected RBI (pipeline + API + boards), the officials/Retrosheet/
OAA/base-state/stuff data layer, and the harness's probability metrics.

**Open, by design**: Wave 4 umpire round (~2026-08-05 when the probe
fortnight matures; BB-led serve factor + the gated E3 retest); B8b RBI v2 and
own-data framing metrics (data ready); hvlog and E15-totals as next-season
candidates; roster-projection early-season priors as the one un-tried E9
successor.

**Methodology debts**: per-comparison p-values remain family-wise uncorrected
(standing caveat, mitigated by seed gates + the 2026 holdout); 2026 "closing"
lines remain retroactive ESPN captures; E15-totals deliberately not
seed-spent at p=.07; ops note — PowerShell-detached runners with `*>`
redirection silently break exit-code chains and write UTF-16 logs (two jobs
lost to it; Bash background jobs proved reliable).
