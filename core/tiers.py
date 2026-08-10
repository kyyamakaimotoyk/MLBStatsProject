"""Pick-confidence tiers — the single source of the Strong/Lean rule.

A pick is a STRONG pick when the calibrated probability of the pick itself
(max(p, 1-p) of the served p_home, which is calibrated and sign-coherent)
clears STRONG_MIN. Everything else is LEAN. Frozen 2026-08-10 from
scripts/confidence_tier_study.py over the 8,713-game walk-forward archive:
strong = .6169 accuracy [CI .599-.634] at 33.6% coverage, every season
>= .6072 including the 2026 drift year, Mar-Jun .6194 — the tier holds in
the window where the pooled record is weakest.

The threshold is a published product boundary: changing it changes what the
site's tiered track record means, so treat it like a schema change — new
tuning-log entry, `orchestration.grades --full` rebuild, and the site copy
reviewed. Do not read it into any feature builder; tiers are presentation.
"""

STRONG_MIN = 0.58
TIER_STRONG = "strong"
TIER_LEAN = "lean"


def tier_of(pick_prob: float) -> str:
    """Tier for a pick the model gives `pick_prob` chance of winning."""
    return TIER_STRONG if pick_prob >= STRONG_MIN else TIER_LEAN
