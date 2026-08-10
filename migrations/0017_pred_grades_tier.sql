-- Pick-confidence tier on the published track record (2026-08 cycle).
--
-- 'strong' = the calibrated probability of the pick itself was >= 0.58 at
-- publish time (core/tiers.py::STRONG_MIN — the frozen rule from
-- scripts/confidence_tier_study.py); everything else is 'lean'. The site
-- leads with the strong-tier record, so the tier is resolved once, on write,
-- like everything else in this table:
--
--   * daily_v1 rows store the served calibrated p_home, so their tier is
--     max(p_home, 1 - p_home) >= 0.58 directly (the serve-time coherence
--     clip preserves magnitude; flip-zone games clamp to .5 -> lean).
--   * historical walk-forward rows store the RAW sigma-squash p_home, so
--     orchestration/grades.py joins the E11c calibrated archive
--     (lgbm_runs+log8) and tiers on the calibrated probability of the
--     published pick — the same numbers the tier study measured.
--
-- Derived column in a derived table: run
-- `python -m orchestration.grades --full` after applying this so all
-- history is tiered.
ALTER TABLE pred_grades
    ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'lean'
        CHECK (tier IN ('strong', 'lean'));
