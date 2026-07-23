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
    "travel": False,     # E8e: travel burden since last game (distance, TZ shift)
    "venue_env": False,  # E8f: rolling venue scoring environment
    # 2026-07 cycle Wave 2 (docs/literature_review_2026-07.md):
    "priors": False,        # E9a: prior-season team rates, kappa=2/3 shrunk
    "priors_blend": False,  # E9b: n/(n+k) blend of season-to-date with prior
    "pyth": False,          # E14: Pythagorean-expectation diff + Log5 p_home
    "defense": False,       # B9a: team BABIP-against + xHits-saved
    "lineup_xr": False,     # LINEUP_XR: Markov lineup expected runs
    "sp_stuff": False,      # E15: process-based SP quality (in-house Stuff+)
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
    "travel": ("HOME_TRAVEL_", "AWAY_TRAVEL_", "DIFF_TRAVEL_"),
    "venue_env": ("VENUE_",),
    "priors": ("HOME_PRIOR_", "AWAY_PRIOR_", "DIFF_PRIOR_"),
    "priors_blend": ("HOME_BLEND_", "AWAY_BLEND_", "DIFF_BLEND_"),
    "pyth": ("PYTH_", "LOG5_"),
    "defense": ("HOME_DEF_", "AWAY_DEF_", "DIFF_DEF_"),
    # more specific than the lineup prefixes, same trick as lineup_platoon
    "lineup_xr": ("HOME_LINEUP_XR", "AWAY_LINEUP_XR", "DIFF_LINEUP_XR"),
    "sp_stuff": ("HOME_SP_STUFF", "AWAY_SP_STUFF", "DIFF_SP_STUFF",
                 "HOME_SP_LOC", "AWAY_SP_LOC", "DIFF_SP_LOC",
                 "HOME_SP_PITCH", "AWAY_SP_PITCH", "DIFF_SP_PITCH"),
}

# Feature families for the drop-one ablation profiles (E8a). Profile
# "no_<family>" removes every column the family claims; family definitions
# mirror the builder blocks in features/team_features.py. HOME_/AWAY_/DIFF_
# columns are matched on their side-stripped base name, game-level columns on
# their full name.
_FORM_BASES = {"RUNS_PG_L10", "RUNS_PG_L30", "RA_PG_L10", "RA_PG_L30",
               "WOBA_L30", "XWOBA_CON_L30", "K_PCT_L30", "BB_PCT_L30",
               "N_PRIOR_GAMES", "REST_DAYS", "GAME_NUM"}
FAMILIES = ("form", "sp", "bullpen", "lineup", "elo", "park", "weather",
            "context", "travel", "priors", "defense")


def _family(col: str) -> str:
    base = col
    for side in ("HOME_", "AWAY_", "DIFF_"):
        if col.startswith(side):
            base = col[len(side):]
            break
    if base in _FORM_BASES:
        return "form"
    # PYTH_/LOG5_ are season-strength aggregates with their own prior blend —
    # grouped with the priors family, not form (form is a known diluter)
    if base.startswith(("PRIOR_", "BLEND_")) or col.startswith(("PYTH_", "LOG5_")):
        return "priors"
    if base.startswith("DEF_"):
        return "defense"
    if base.startswith("SP_"):
        return "sp"
    if base.startswith("BP_"):
        return "bullpen"
    if base.startswith("LINEUP_"):
        return "lineup"
    if base.startswith("TRAVEL_"):
        return "travel"
    if col.startswith("ELO_"):
        return "elo"
    if col.startswith(("PARK_", "VENUE_")):
        return "park"
    if col in ("TEMP_F", "WIND_SPEED_MPH", "IS_OPEN_AIR") or \
            col.startswith(("WIND_OUT", "UMP_")):
        return "weather"
    if col in ("IS_NIGHT", "IS_DOUBLEHEADER_G2"):
        return "context"
    return "other"

TARGETS = ("team_runs", "margin", "total", "batter_pa")


def select_features(columns: list[str], target: str, profile: str = "full",
                    enable_flags: tuple[str, ...] = ()) -> list[str]:
    """Return the model-facing feature columns for a target, in stable order.

    `columns` is the full column list of a feature-store snapshot; the return
    value is the subset the model for `target` may see. Odds columns never
    appear here — they are benchmark-only by schema and by convention.

    profile 'slim' (experiment E4) keeps only the Elo block, the starting-
    pitcher blocks, and the park factor. profile 'no_<family>' (experiment E8a)
    drops one family from FAMILIES for drop-one ablations. enable_flags
    force-enables named FEATURE_FLAGS for experiment runs without editing
    this file.
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
    elif profile.startswith("no_"):
        fam = profile[3:]
        if fam not in FAMILIES:
            raise ValueError(f"unknown profile {profile!r}")
        feats = [c for c in feats if _family(c) != fam]
    elif profile != "full":
        raise ValueError(f"unknown profile {profile!r}")
    return sorted(feats)
