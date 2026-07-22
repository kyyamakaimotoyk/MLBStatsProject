-- B8a (2026-07 cycle): slot-conditional expected RBI over the per-PA heads,
-- exp_rbi = sum over classes of E[n_c] x rbar(class, slot), rbar shrunk
-- W=300 toward class-global means (era constants below 10k PAs). Prediction
-- column only — actual RBIs have always been ingested (plays.rbi,
-- batter_game_lines.rbi). Ships to daily/API/site only on a significant,
-- seed-consistent walk-forward win vs the batter-marginal baseline.
ALTER TABLE batter_predictions ADD COLUMN IF NOT EXISTS exp_rbi REAL;
