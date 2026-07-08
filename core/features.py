"""Single source of truth for feature selection.

Every consumer — training, prediction, experiments — MUST get its feature list
from select_features(). The NBA project's worst recurring bug was three modules
each holding a private copy of the feature-pattern list, which silently dropped
shipped features (Elo, lineup synergy) before they reached the model. Do not
duplicate this logic anywhere.

Ablation candidates are gated by FEATURE_FLAGS (the NBA ENABLE_E9/E10/E11
pattern): features stay built in the feature store; flags decide whether they
reach the model. Flag flips are experiments and get a tuning-log entry.
"""

FEATURE_FLAGS: dict[str, bool] = {
    # Populated from Phase 2 onward, e.g.:
    # "umpire": False,           # HP umpire K/BB tendencies (Phase 3 ablation)
    # "catcher_framing": False,  # Phase 4 ablation candidate
}

TARGETS = ("team_runs", "margin", "total", "batter_pa")


def select_features(columns: list[str], target: str) -> list[str]:
    """Return the model-facing feature columns for a target, in stable order.

    `columns` is the full column list of a feature-store snapshot; the return
    value is the subset the model for `target` may see. Odds columns never
    appear here — they are benchmark-only by schema and by convention.

    Implemented in Phase 2 with the first feature build.
    """
    if target not in TARGETS:
        raise ValueError(f"Unknown target {target!r}; expected one of {TARGETS}")
    raise NotImplementedError("Phase 2: implemented with the first feature build")
