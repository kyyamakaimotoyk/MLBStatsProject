# Wave 4 — umpire serve path (2026-08-10)

The probe-gated umpire round from the 2026-07 literature cycle
(docs/literature_review_2026-07.md "Wave 4"; crew study
docs/umpire_crew_study_2026-07.md; tuning-log entry E17). Verdict up front:
**every arm rejected; the umpire track closes with evidence**. The serve-path
infrastructure (probe results, rotation predictor, factor machinery) is kept
behind off flags and recorded here.

## 1. Probe fortnight — when do HP assignments become knowable?

196 regular-season games, 2026-07-23..2026-08-06, `game_officials` first-seen
timestamps (probe at every pipeline tick; earliest sighting preserved).

- 83.7% of HP assignments were captured pregame by a probe tick; the rest
  were first seen by the postgame feed import.
- **164/164 pregame captures matched the final HP ump** — a posted
  assignment never changed. A pregame sighting is 100% trustworthy.
- Median posting lead: 3.1h before first pitch (P10 2.1h, P90 4.1h); the
  posting wave lands 20–21Z.

Pregame availability at each UTC tick (share of the full slate; "usable" =
posted and the game has not started):

| tick | available | already started | usable |
|---|---|---|---|
| 14Z | .005 | .000 | .005 |
| 18Z | .056 | .148 | .000 |
| 20Z | .194 | .260 | .092 |
| 21Z | .597 | .332 | .423 |
| 22Z | .663 | .337 | .485 |
| 23Z | .770 | .480 | .449 |

Per game, at its **last pregame prediction tick** (14/18/21/23Z):
**59.7% of published predictions could carry the actual ump** — .966 for
games whose last tick is 21Z, .863 for 23Z, ~0 for day games (14Z/18Z-last).
Adding an officials overwrite to the 20Z scores-only tick would raise it to
66.8% (+7.1pp); 22Z adds ~nothing on top.

## 2. Pregame rotation predictor

Rule: HP(G) = the 1B umpire of the previous game of the same series (same
home/away pair, gap 1–3 days). Validated on API-era crews (full HP+1B
coverage 2019–2026):

| season | coverage | hit given covered | total named |
|---|---|---|---|
| 2019 | .678 | .968 | .656 |
| 2020 | .653 | .863 | .563 |
| 2021–2025 | .674–.680 | .924–.973 | .628–.660 |
| 2026 | .678 | .968 | .656 |

- **DH nightcaps are structurally unpredictable**: the game-2 plate ump is
  outside game 1's crew 99.3% of the time (304 nightcaps) — a reserve ump,
  not a rotation. Neutral fallback. The day AFTER a nightcap still follows
  1B→HP at .865 (vs .982 after normal days), so those stay predicted.
- Covered-but-miss (~2% ex-nightcaps) is crew substitution; "HP stayed HP"
  occurs 0% — the counterclockwise rotation itself is essentially exact.

## 3. Data findings that shaped the build

- **Chadwick does not bridge umpires.** `ingestion/import_reference.py`
  keeps only register rows with `mlb_played_first`, so career umpires never
  enter `players_xref`: 0/2,475 distinct ump-seasons resolved. (Name-overlap
  with `game_officials` matches 126/224 retrosheet HP umps, zero ambiguous
  names — the unmatched are pre-2019 retirees.) Consequence: factors are
  built from **own data only** (2019–2026, `game_officials` MLBAM ids ×
  `batter_game_lines` team K/BB/PA), no id bridge in any shipped path;
  Retrosheet remains study-only.
- **Ballasts replicate the era collapse on our own data**
  (scripts/ump_ballast_study.py, 536 ump-seasons ≥20 games, 342 YoY pairs):
  K factor YoY r = .093 → EB ballast n0 = 273 games (a full 90-game window
  keeps 25% of the raw deviation); BB r = .305 → n0 = 64 (keeps 58%).
  "BB-led, shrink K hard" is estimated, not hand-tuned. Trailing window
  1095 days, min 15 games, league floor 50k PA. Shrunken factor spreads:
  BB SD .033 (90% range ~.95–1.05), K SD .007.

## 4. Feature build

Inline `_ump_serve_lookup` in features/team_features.py (the `_ump_factors`
pattern — no new table, `max_date`-honoring, point-in-time verified exactly:
truncated build ≡ full build). Columns, all game-level:

- `UMP_SERVE_K` / `UMP_SERVE_BB` / `UMP_SERVE_KNOWN` (flag `ump_serve`):
  factors of the **rotation-predicted** ump; neutral 1.0 + KNOWN=0 for
  openers, nightcaps, and sub-window umps. KNOWN rate .581.
- `UMP_ACT_K` / `UMP_ACT_BB` (flag `ump_actual`): the same factors for the
  **actual** ump — the diagnostic ceiling; assumes assignment knowledge that
  is pregame-real for only ~60% of games, so it can never ship.
- `_FLAG_PREFIXES["umpire"]` narrowed `("UMP_",)` → `("UMP_K_FACTOR",)`:
  the cumulative flag filter would otherwise strip the new columns under
  the disabled E3 flag and produce a silent false null.

Snapshot v20260810_015624 (17,316 rows, flags off). Gates: leakage PASS
(11,854 × 248), flags-off column identity vs current PASS — and the
carry-over was verified **bit-identical** this cycle (+ub8 base arm vs
lgbm_runs+8s: 0 discordant picks, all paired tests p=1.0), upgrading the
E15/E16 cross-snapshot convention from "licensed" to "exact".

## 5. Results (E17)

Selection 2023–2025, 7,269 paired games vs lgbm_runs+8s @v20260716_083741;
totals MAE the pre-registered primary. Seed 0:

| arm | totals MAE | acc | AUC | log loss | Brier |
|---|---|---|---|---|---|
| +us8 serve | null p=.68 | null p=.79 | +.0035 p=.028 | −.0011 p=.038 | p=.031 |
| +ua8 ceiling | null p=.51 | null p=.11 | +.0035 p=.018 | p=.036 | p=.031 |
| +usw8 +wind (E3 retest) | null p=.13 | **worse, p=.039** | null p=.60 | null p=.63 | null p=.59 |

The seed-0 probability gains die on both pre-registered guards:

- **Era decay / ABS attenuation**: the gain is 2023 alone (AUC p=.038, LL
  p=.050); 2024 null (p=.24); 2025 null (p=.75); **2026 holdout
  sign-flipped** (LL A .6883 vs B .6873). The crew study's
  monitoring-convergence trend reproduced inside the walk-forward.
- **Seed gate**: s1 all null (LL p=.31, direction positive); s2 all null,
  direction **flipped**. The E10 one-seed pattern; ship bar (p<.05 +
  direction consistent 0/1/2) missed everywhere.

Totals MAE null is the **fifth** umpire-family totals failure
(E3 ×3, E8b, E17).

## 6. Decisions

- REJECTED: `ump_serve`, `ump_actual`, `ump_serve`+`wind_out`. Flags stay
  False; current snapshot stays v20260716_083741; no production change.
- **The ceiling arm closes the track**: with near-perfect assignment
  knowledge the factors still ship nothing, so no improvement to the
  predictor, probe cadence, or late-tick actuals overwrite changes the
  verdict. Do not re-propose per-ump K/BB factors without a structurally
  different signal — the queued UMP-KBB-STAB v2 (pitch-call residualized on
  B8b data) qualifies only if it first demonstrates a 2026+ ABS-era effect.
- The officials probe stays in orchestration.daily: ~one schedule call per
  tick, and it keeps accumulating the posting-time archive plus pregame
  crews in `game_officials`, which have product/display uses independent of
  modeling.
- Observation (not acted on): `UMP_SERVE_KNOWN` ≈ a series-opener
  indicator. If a context-family experiment ever wants that, test a clean
  `IS_SERIES_OPENER` on its own terms.

Stored artifacts: team predictions +us8[_s1,_s2], +ua8, +usw8, +ub8
@v20260810_015624 (registry rows kept); scripts/ump_ballast_study.py;
this doc; tuning-log E17.
