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

from core.features_io import META_COLS

# Meta columns of the per-PA batter frame (features/batter_features.py builds
# it; it is not snapshotted — see that module's docstring).
BATTER_META_COLS = ["game_pk", "game_date", "season", "at_bat_index",
                    "batter_id", "pitcher_id", "pitch_hand"]

# flag -> column prefixes it controls. Disabled flags drop matching columns.
# Flag flips are experiments: they ship only with a tuning-log entry.
FEATURE_FLAGS: dict[str, bool] = {
    "umpire": False,    # E3: HP umpire strikeout tendency (UMP_K_FACTOR)
    "wind_out": False,  # E3: signed out/in wind component (WIND_OUT_MPH)
    "lineup": True,     # E5b SHIPPED 2026-07-15: lineup strength + missing regulars
                        # (margin MAE p=.020, AUC p=.009 vs baseline)
    "lineup_platoon": False,  # E5c: vs-hand lineup rates against the probable SP
    "arsenal_cross": False,   # B4: per-pitch-class quality x pitcher mix (parked)
}
_FLAG_PREFIXES: dict[str, tuple[str, ...]] = {
    "umpire": ("UMP_",),
    "wind_out": ("WIND_OUT",),
    "lineup": ("HOME_LINEUP_", "AWAY_LINEUP_", "DIFF_LINEUP_"),
    # more specific than the lineup prefixes: a disabled flag removes its
    # matches even when the broader lineup flag is enabled
    "lineup_platoon": ("HOME_LINEUP_VS_HAND", "AWAY_LINEUP_VS_HAND",
                       "DIFF_LINEUP_VS_HAND", "HOME_LINEUP_SAME_HAND_SHARE",
                       "AWAY_LINEUP_SAME_HAND_SHARE", "DIFF_LINEUP_SAME_HAND_SHARE"),
    "arsenal_cross": ("B_XWOBA_F", "B_XWOBA_B", "B_XWOBA_O", "B_ARSENAL_"),
}

TARGETS = ("team_runs", "margin", "total", "batter_pa")


def select_features(columns: list[str], target: str, profile: str = "full",
                    enable_flags: tuple[str, ...] = ()) -> list[str]:
    """Return the model-facing feature columns for a target, in stable order.

    `columns` is the full column list of a feature-store snapshot; the return
    value is the subset the model for `target` may see. Odds columns never
    appear here — they are benchmark-only by schema and by convention.

    profile 'slim' (experiment E4) keeps only the Elo block, the starting-
    pitcher blocks, and the park factor. enable_flags force-enables named
    FEATURE_FLAGS for experiment runs without editing this file.
    """
    if target not in TARGETS:
        raise ValueError(f"Unknown target {target!r}; expected one of {TARGETS}")
    meta = BATTER_META_COLS if target == "batter_pa" else META_COLS
    feats = [c for c in columns if c not in meta and not c.startswith("TARGET_")]
    for flag, enabled in FEATURE_FLAGS.items():
        if not (enabled or flag in enable_flags):
            prefixes = _FLAG_PREFIXES.get(flag, ())
            feats = [c for c in feats if not c.startswith(prefixes)]
    if profile == "slim":
        feats = [c for c in feats
                 if c.startswith("ELO_") or "_SP_" in c or "_LINEUP_" in c
                 or c == "PARK_PF_RUNS"]
    elif profile != "full":
        raise ValueError(f"unknown profile {profile!r}")
    return sorted(feats)
