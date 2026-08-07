"""Daily prediction pipeline (Phase 5).

Morning run for a target date:
  1. refresh   — import any recent final games + Statcast days (ledger-driven)
  2. derived   — rebuild park factors (slate Elo is computed live; bundle
                 retrains refresh team_strength_pregame first)
  3. slate     — fetch schedule + probables, snapshot to probable_pitchers
  4. team      — load-or-retrain the runs model bundle (weekly staleness cap,
                 the NBA calibration-incident lesson), predict margin/total/
                 p_home for the slate with both lgbm_runs and the Elo baseline
  5. batter    — load-or-retrain the per-PA bundle, project lineups (last
                 posted lineup per team until real lineups land ~2-4h pregame),
                 predict stat lines + probability heads vs the probable SP
  6. sanity    — degeneracy tripwires on every output before anything ships

Model bundles live in S3 via core/artifact_store (joblib), keyed
team_runs_latest / batter_pa_latest, each carrying trained_through for the
staleness check.

Usage:
    python -m orchestration.daily                  # today
    python -m orchestration.daily --date 2026-07-15 --skip-ingest
    python -m orchestration.daily --scores-only    # same-day finals refresh
"""

import argparse
import logging
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import text

from core import artifact_store
from core.db import get_engine
from core.features import select_features
from features import batter_features as bf
from features import park_factors, team_features, team_rating
from ingestion import backfill_games, backfill_statcast, statsapi_client
from modeling import batter_model as bm
from modeling.team_models import EloBaseline, make
from orchestration import grades

log = logging.getLogger("daily")

VERSION = "daily_v1"
RETRAIN_AFTER_DAYS = 7
MAX_PA = 7


# ------------------------------------------------------------- bundles

def _load_bundle(name: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = artifact_store.load_artifact(name, Path(tmp) / name)
        if path is None:
            return None
        try:
            return joblib.load(path)
        except Exception as exc:
            log.warning("bundle %s unreadable (%s); retraining", name, exc)
            return None


def _save_bundle(name: str, bundle: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        joblib.dump(bundle, path)
        uri = artifact_store.save_artifact(path, name)
    log.info("saved bundle %s -> %s", name, uri)


def _stale(bundle: dict | None, target_date: str) -> bool:
    if bundle is None:
        return True
    age = (pd.Timestamp(target_date) - pd.Timestamp(bundle["trained_through"])).days
    return age > RETRAIN_AFTER_DAYS


# E11c calibration source: the validated walk-forward archive (update the
# constants when a newer archive ships). Verdicts: log loss .6813 vs .6836
# pooled at seeds 0/1/2; 2026 holdout .6872 vs .6995, p=.016.
CAL_P_ARCHIVE = ("lgbm_runs+8s", "elo+8s", "v20260716_083741")
CAL_P_MIN_GAMES = 1500


def _fit_p_calibrator() -> dict | None:
    """E11c (SHIPPED 2026-07-23): logistic p_home over [margin/sigma,
    logit(elo p)], fit on stored out-of-sample walk-forward predictions
    joined to finals — everything strictly historical, so serve-time use is
    point-in-time by construction (the B6 cal_hit pattern)."""
    from sklearn.linear_model import LogisticRegression

    lgbm_tag, elo_tag, ver = CAL_P_ARCHIVE
    d = pd.read_sql(text("""
        SELECT a.pred_margin, e.p_home AS elo_p,
               (g.home_score > g.away_score)::int AS win,
               g.home_score - g.away_score - a.pred_margin AS resid
        FROM model_predictions a
        JOIN model_predictions e
          ON e.game_pk = a.game_pk AND e.model_version = a.model_version
         AND e.model_type = :elo_tag
        JOIN games g ON g.game_pk = a.game_pk AND g.is_final
        WHERE a.model_type = :lgbm_tag AND a.model_version = :ver
    """), get_engine(), params={"lgbm_tag": lgbm_tag, "elo_tag": elo_tag,
                                "ver": ver})
    if len(d) < CAL_P_MIN_GAMES:
        log.warning("p calibrator: only %d graded rows (<%d); p_home stays raw",
                    len(d), CAL_P_MIN_GAMES)
        return None
    sigma = max(float(d["resid"].std()), 1.0)
    ep = np.clip(d["elo_p"].to_numpy(float), 1e-6, 1 - 1e-6)
    X = np.column_stack([d["pred_margin"].to_numpy(float) / sigma,
                         np.log(ep / (1 - ep))])
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(X, d["win"].to_numpy())
    log.info("p calibrator fit on %d graded games (sigma %.3f, coef %s)",
             len(d), sigma, np.round(lr.coef_[0], 3).tolist())
    return {"lr": lr, "sigma": sigma, "n_fit": int(len(d))}


def _team_bundle(target_date: str) -> dict:
    bundle = _load_bundle("team_runs_latest.joblib")
    # bundles predating the E11c calibrator retrain once to pick it up
    if not _stale(bundle, target_date) and bundle.get("cal_p") is not None:
        log.info("team bundle fresh (trained through %s)", bundle["trained_through"])
        return bundle
    log.info("training team models on all data ...")
    # build_features() reads team_strength_pregame; without this, every weekly
    # retrain trains on Elo frozen at the last manual features.team_rating run
    team_rating.refresh()
    df = team_features.build_features()
    feats = select_features(list(df.columns), "team_runs")
    model = make("lgbm_runs")
    model.fit(df, feats)
    elo = EloBaseline()
    elo.fit(df, feats)
    bundle = {"model": model, "elo": elo, "feats": feats,
              "cal_p": _fit_p_calibrator(),
              "trained_through": str(df["game_date"].max())[:10]}
    _save_bundle("team_runs_latest.joblib", bundle)
    return bundle


def _batter_bundle(target_date: str) -> dict:
    bundle = _load_bundle("batter_pa_latest.joblib")
    if not _stale(bundle, target_date):
        log.info("batter bundle fresh (trained through %s)", bundle["trained_through"])
        return bundle
    log.info("training per-PA batter model on all data (several minutes) ...")
    comp = bf.build()
    pa = comp["pa"]
    feats = select_features(list(pa.columns), "batter_pa")
    model = bm.BatterPAModel()
    model.fit(pa, feats)

    engine = get_engine()
    w = pd.read_sql(text("""
        SELECT AVG(CASE WHEN pg.player_id IS NOT NULL THEN 1.0 ELSE 0.0 END) AS w
        FROM plays p
        LEFT JOIN pitcher_game_lines pg
          ON pg.game_pk = p.game_pk AND pg.player_id = p.pitcher_id AND pg.is_starter
    """), engine)["w"].iloc[0]
    league_row = {
        "q_vs_right": float((pa["pitch_hand"] == "R").mean()),
        "pitcher_means": {c: float(pa[c].mean()) for c in feats if c.startswith("P_")},
        "same_hand_mean": float(pa["SAME_HAND"].mean()),
    }
    slot_pa = pd.read_sql(text("""
        SELECT l.batting_order AS lineup_slot,
               (l.team_id = g.home_team_id) AS is_home, b.pa
        FROM lineups l
        JOIN games g USING (game_pk)
        JOIN batter_game_lines b USING (game_pk, player_id)
        WHERE g.is_final AND l.batting_order BETWEEN 1 AND 9 AND b.pa IS NOT NULL
          AND COALESCE(g.scheduled_innings, 9) = 9
    """), engine).astype({"pa": int})
    # B3 (shipped 2026-07-17): isotonic calibrator for the p_hit head, fit on
    # stored out-of-sample predictions vs outcomes (walk-forward backfill +
    # prior daily runs). p_hr stays raw — its calibration gain never cleared
    # significance (never ship a calibrator without demonstrated benefit).
    cal_hit = None
    cal_rows = pd.read_sql(text("""
        SELECT DISTINCT ON (bp.game_pk, bp.player_id)
               bp.p_hit, (bg.h >= 1)::int AS hit1
        FROM batter_predictions bp
        JOIN batter_game_lines bg
          ON bg.game_pk = bp.game_pk AND bg.player_id = bp.player_id
        JOIN games g ON g.game_pk = bp.game_pk AND g.is_final
        WHERE bp.p_hit IS NOT NULL AND bg.h IS NOT NULL
        ORDER BY bp.game_pk, bp.player_id,
                 (bp.model_version = 'daily_v1') DESC, bp.created_at DESC
    """), engine)
    if len(cal_rows) >= 10_000:
        from sklearn.isotonic import IsotonicRegression
        cal_hit = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        cal_hit.fit(cal_rows["p_hit"].to_numpy(float), cal_rows["hit1"].to_numpy(float))
        log.info("p_hit isotonic calibrator fit on %d graded predictions", len(cal_rows))
    bundle = {"model": model, "feats": feats, "w": float(w),
              "league_row": league_row,
              "pa_dists": bm.build_pa_dists(slot_pa, MAX_PA),
              "cal_hit": cal_hit,
              "trained_through": str(pa["game_date"].max())[:10]}
    _save_bundle("batter_pa_latest.joblib", bundle)
    return bundle


# ------------------------------------------------------------- pipeline

def refresh_ingest(target_date: str) -> None:
    start = (pd.Timestamp(target_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(target_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    backfill_games.seed_range(start, end)
    backfill_games.run(workers=4, sleep=0.1)
    backfill_statcast.run(sleep=0.5)


def probe_officials(target_date: str) -> None:
    """Pregame officials probe (2026-07 cycle, W0.2): capture umpire
    assignments for today's not-yet-started games at every pipeline tick.
    game_officials keeps the FIRST sighting's captured_at (ingestion.officials
    upsert), so the ticks accumulate the empirical officials-post-time
    distribution vs first_pitch_utc — the measurement the umpire serve-path
    design (Wave 4) is gated on. Verified 2026-07-22: officials are absent
    from the boxscore ~5h pregame, so pregame coverage is expected to come
    from the late ticks only. Best-effort; never blocks the pipeline."""
    from datetime import datetime, timezone

    from ingestion import officials as officials_writer

    tick = f"probe_{datetime.now(timezone.utc):%H}Z"

    def _rows(pk: int, raw) -> list[dict]:
        return [
            {"game_pk": pk, "official_type": o.get("officialType"),
             "official_id": o.get("official", {}).get("id"),
             "official_name": o.get("official", {}).get("fullName")}
            for o in (raw or []) if o.get("officialType")
        ]

    try:
        games = statsapi_client.schedule(target_date, target_date, hydrate="officials")
    except Exception as exc:
        log.warning("officials probe: schedule fetch failed: %s", exc)
        return
    previews = [g for g in games
                if g.get("status", {}).get("abstractGameState") == "Preview"]
    found = 0
    try:
        with get_engine().begin() as conn:
            for g in previews:
                pk = g["gamePk"]
                rows = _rows(pk, g.get("officials"))
                source = f"{tick}_sched"
                if not rows:
                    try:
                        rows = _rows(pk, statsapi_client.boxscore(pk).get("officials"))
                        source = tick
                    except Exception:
                        continue
                if rows:
                    officials_writer.upsert(conn, rows, source=source)
                    found += 1
    except Exception as exc:
        log.warning("officials probe failed: %s", exc)
        return
    log.info("officials probe %s: %d/%d preview games had officials posted",
             tick, found, len(previews))


def refresh_scores(target_date: str) -> None:
    """Same-day score refresh (the evening schedule): import any games that
    have gone final through today, so results and pick grading reach the site
    the same night instead of at the next morning run. Yesterday is included
    for games that cross midnight ET. Games ledger only — a partially played
    date must never enter the statcast_day ledger, or the next full run would
    import an incomplete day and mark it done; the morning run seeds statcast
    once the slate is complete."""
    start = (pd.Timestamp(target_date) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    backfill_games.seed_range(start, target_date, seed_statcast=False)
    backfill_games.run(workers=4, sleep=0.1)


def fetch_slate(target_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (slate, posted_lineups). Posted lineups appear ~2-4h pregame;
    the hydrate returns the nine in batting order (validated against the live
    feed's battingOrder)."""
    games = statsapi_client.schedule(target_date, target_date,
                                     hydrate="probablePitcher,lineups")
    rows, posted = [], []
    for g in games:
        if g.get("status", {}).get("abstractGameState") != "Preview":
            continue
        lu = g.get("lineups") or {}
        for side_key, side in (("homePlayers", "home"), ("awayPlayers", "away")):
            players = lu.get(side_key) or []
            if len(players) >= 9:
                team_id = g["teams"][side]["team"]["id"]
                posted += [{"game_pk": g["gamePk"], "team_id": team_id,
                            "player_id": p["id"], "lineup_slot": slot}
                           for slot, p in enumerate(players[:9], start=1)]
        rows.append({
            "game_pk": g["gamePk"],
            "game_date": g["officialDate"],
            "first_pitch_utc": g.get("gameDate"),
            "season": int(g["season"]),
            "game_type": g.get("gameType"),
            "day_night": g.get("dayNight"),
            "game_number": g.get("gameNumber"),
            "venue_id": g.get("venue", {}).get("id"),
            "home_team_id": g["teams"]["home"]["team"]["id"],
            "away_team_id": g["teams"]["away"]["team"]["id"],
            "home_probable_id": g["teams"]["home"].get("probablePitcher", {}).get("id"),
            "away_probable_id": g["teams"]["away"].get("probablePitcher", {}).get("id"),
        })
    slate = pd.DataFrame(rows)
    if not slate.empty:
        records = slate.astype(object).where(slate.notna(), None).to_dict("records")
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO probable_pitchers (game_pk, source, home_pitcher_id, away_pitcher_id)
                VALUES (:game_pk, 'daily', :home_probable_id, :away_probable_id)
            """), [{k: r[k] for k in ("game_pk", "home_probable_id", "away_probable_id")}
                   for r in records])
            # Skeleton rows so predictions for unplayed games can be labeled
            # (matchup, date) by the API; the feed import overwrites on final.
            conn.execute(text("""
                INSERT INTO games (game_pk, season, game_type, game_date, status,
                                   home_team_id, away_team_id, venue_id, day_night,
                                   game_number, is_final)
                VALUES (:game_pk, :season, :game_type, :game_date, 'Scheduled',
                        :home_team_id, :away_team_id, :venue_id, :day_night,
                        :game_number, FALSE)
                ON CONFLICT (game_pk) DO NOTHING
            """), [{k: r[k] for k in ("game_pk", "season", "game_type", "game_date",
                                      "home_team_id", "away_team_id", "venue_id",
                                      "day_night", "game_number")}
                   for r in records])
    log.info("slate for %s: %d games (%d with both probables)", target_date, len(slate),
             int((slate["home_probable_id"].notna() & slate["away_probable_id"].notna()).sum())
             if not slate.empty else 0)
    return slate, pd.DataFrame(posted)


def _game_lineups(slate: pd.DataFrame, posted: pd.DataFrame,
                  projected: pd.DataFrame) -> pd.DataFrame:
    """One lineup per (game, team): the POSTED lineup where available, else
    the team's projection — per game, so doubleheaders resolve correctly."""
    posted_keys = (set(zip(posted["game_pk"], posted["team_id"]))
                   if len(posted) else set())
    parts = []
    for g in slate.itertuples():
        for team_id in (g.home_team_id, g.away_team_id):
            if (g.game_pk, team_id) in posted_keys:
                sub = posted[(posted["game_pk"] == g.game_pk)
                             & (posted["team_id"] == team_id)].copy()
                sub["source"] = "posted"
            else:
                sub = projected[projected["team_id"] == team_id][
                    ["team_id", "player_id", "lineup_slot"]].copy()
                sub["game_pk"] = g.game_pk
                sub["source"] = "projected"
            parts.append(sub)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["game_pk", "team_id", "player_id", "lineup_slot", "source"])
    n_posted = out[out["source"] == "posted"].groupby(["game_pk", "team_id"]).ngroups
    n_proj = out[out["source"] == "projected"].groupby(["game_pk", "team_id"]).ngroups
    log.info("lineups: %d posted, %d projected (team-games)", n_posted, n_proj)
    return out


def predict_team(slate: pd.DataFrame, target_date: str, asof: str,
                 lineups: pd.DataFrame | None = None,
                 weather: dict | None = None) -> pd.DataFrame:
    bundle = _team_bundle(target_date)
    rows = team_features.build_prediction_rows(slate, asof, lineups=lineups,
                                               weather=weather)
    warnings = []
    out = []
    for name, model in (("lgbm_runs", bundle["model"]), ("elo", bundle["elo"])):
        preds = model.predict(rows, bundle["feats"])
        preds["game_pk"] = rows["game_pk"].to_numpy()
        preds["model_type"] = name
        out.append(preds)
        if ((preds["p_home"] < 0.10) | (preds["p_home"] > 0.90)).any():
            warnings.append(f"{name}: p_home outside [0.10, 0.90]")
        if not preds["pred_total"].between(5, 14).all():
            warnings.append(f"{name}: pred_total outside [5, 14]")
        mean_p = preds["p_home"].mean()
        if not 0.40 <= mean_p <= 0.68:
            warnings.append(f"{name}: slate mean p_home {mean_p:.3f} outside [0.40, 0.68]")
    # E11c (shipped 2026-07-23): calibrated p_home for the lgbm head —
    # logistic over [margin/sigma, logit(elo p)] from the bundle calibrator.
    # Picks (pred_margin) and totals are untouched; raw p stays if the
    # calibrator is absent.
    cal = bundle.get("cal_p")
    if cal is not None:
        ep = np.clip(out[1]["p_home"].to_numpy(float), 1e-6, 1 - 1e-6)
        X = np.column_stack([out[0]["pred_margin"].to_numpy(float) / cal["sigma"],
                             np.log(ep / (1 - ep))])
        out[0]["p_home"] = cal["lr"].predict_proba(X)[:, 1]
        # The published pick is p_home vs .5 and must agree with the margin
        # head's sign — the calibrator alone crosses .5 against the margin in
        # 14.9% of archive games, a coin toss either way (663-633; clip
        # log-loss delta -0.0001, tuning log 2026-07-27). Epsilon keeps the
        # side unambiguous under both > and >= comparisons.
        mgn = out[0]["pred_margin"].to_numpy(float)
        ph = out[0]["p_home"].to_numpy(float)
        out[0]["p_home"] = np.where(mgn > 0, np.maximum(ph, 0.5 + 1e-6),
                                    np.minimum(ph, 0.5 - 1e-6))
        if ((out[0]["p_home"] < 0.10) | (out[0]["p_home"] > 0.90)).any():
            warnings.append("lgbm_runs: calibrated p_home outside [0.10, 0.90]")
    all_preds = pd.concat(out, ignore_index=True)

    records = all_preds.assign(model_version=VERSION, data_through_date=asof)
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO model_predictions
                (game_pk, model_type, model_version, data_through_date,
                 pred_home_runs, pred_away_runs, pred_margin, pred_total, p_home)
            VALUES (:game_pk, :model_type, :model_version, :data_through_date,
                    :pred_home_runs, :pred_away_runs, :pred_margin, :pred_total, :p_home)
            ON CONFLICT (game_pk, model_type, model_version) DO UPDATE SET
                data_through_date = EXCLUDED.data_through_date,
                pred_home_runs = EXCLUDED.pred_home_runs,
                pred_away_runs = EXCLUDED.pred_away_runs,
                pred_margin = EXCLUDED.pred_margin,
                pred_total = EXCLUDED.pred_total,
                p_home = EXCLUDED.p_home, created_at = now()
        """), records[["game_pk", "model_type", "model_version", "data_through_date",
                       "pred_home_runs", "pred_away_runs", "pred_margin",
                       "pred_total", "p_home"]].to_dict("records"))
    for w in warnings:
        log.warning("TRIPWIRE %s", w)
    all_preds.attrs["warnings"] = warnings
    return all_preds


def _projected_lineups() -> pd.DataFrame:
    """Most recent posted starting lineup per team (v1 projection; real
    lineups land ~2-4h pregame and are a queued upgrade)."""
    return pd.read_sql(text("""
        WITH latest AS (
            SELECT DISTINCT ON (l.team_id) l.team_id, l.game_pk
            FROM lineups l JOIN games g USING (game_pk)
            ORDER BY l.team_id, g.game_date DESC, g.game_pk DESC
        )
        SELECT l.team_id, l.player_id, l.batting_order AS lineup_slot
        FROM lineups l JOIN latest USING (team_id, game_pk)
    """), get_engine())


def predict_batters(slate: pd.DataFrame, target_date: str, asof: str,
                    lineups: pd.DataFrame | None = None) -> pd.DataFrame:
    bundle = _batter_bundle(target_date)
    comp = bf.build_asof(asof)
    if lineups is None:
        lineups = _game_lineups(slate, pd.DataFrame(), _projected_lineups())
    players = pd.read_sql(text("SELECT player_id, bats, throws FROM players"), get_engine())

    rows = []
    for g in slate.itertuples():
        for side in ("home", "away"):
            team = g.home_team_id if side == "home" else g.away_team_id
            sp_id = g.away_probable_id if side == "home" else g.home_probable_id
            nine = lineups[(lineups["game_pk"] == g.game_pk)
                           & (lineups["team_id"] == team)]
            for b in nine.itertuples():
                rows.append({
                    "game_pk": g.game_pk, "season": g.season, "venue_id": g.venue_id,
                    "player_id": b.player_id, "lineup_slot": b.lineup_slot,
                    "is_home": side == "home",
                    "sp_id": sp_id if not pd.isna(sp_id) else None,
                })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.merge(players[["player_id", "bats"]], on="player_id", how="left")
    frame = frame.merge(players.rename(columns={"player_id": "sp_id",
                                                "throws": "sp_throws"})[["sp_id", "sp_throws"]],
                        on="sp_id", how="left")

    feats = bundle["feats"]
    vs_lg = bm.assemble_matchup(frame, comp, bundle["league_row"], comp["park"],
                                per_game=False)
    p_lg = bundle["model"].predict_proba(vs_lg, feats)
    has_sp = frame["sp_id"].notna().to_numpy()
    probs = p_lg.copy()
    if has_sp.any():
        vs_sp = bm.assemble_matchup(frame[has_sp], comp, None, comp["park"],
                                    per_game=False)
        p_sp = bundle["model"].predict_proba(vs_sp, feats)
        w = bundle["w"]
        probs[has_sp] = w * p_sp + (1 - w) * p_lg[has_sp]
    # B2 (shipped): K probability blended back toward the batter marginal
    probs = bm.blend_k(probs, bm.marginal_probs(vs_lg))

    dist = bm.pa_lookup(bundle["pa_dists"])(frame["lineup_slot"].to_numpy(),
                                            frame["is_home"].to_numpy())
    agg = bm.aggregate_game(probs, dist)
    # B3 (shipped): calibrate the p_hit head when the bundle carries a
    # calibrator (older bundles predate it and stay raw until retrain)
    if bundle.get("cal_hit") is not None:
        agg["p_hit"] = bundle["cal_hit"].predict(agg["p_hit"])
    # B8a (shipped 2026-07-23): slot-conditional expected RBI. rbar computed
    # as-of; probs here are post-B2-blend (walk-forward evaluated pre-blend —
    # K rbar is 0 and the blend's rescale is second-order, the B6 vintage
    # convention). Walk-forward: 0.6331 vs 0.6363 marginal, p<.0001, 3 seeds.
    rmat, _ = bm.rbi_table(bm.rbi_events(max_date=asof))
    agg["exp_rbi"] = agg["exp_pa"] * (
        probs * rmat[frame["lineup_slot"].to_numpy(int)]).sum(axis=1)

    warnings = []
    if not np.all((agg["p_hit"] > 0.20) & (agg["p_hit"] < 0.90)):
        warnings.append("batter: p_hit outside [0.20, 0.90]")
    if not np.all((agg["exp_pa"] > 2.5) & (agg["exp_pa"] < 5.5)):
        warnings.append("batter: exp_pa outside [2.5, 5.5]")
    for w_ in warnings:
        log.warning("TRIPWIRE %s", w_)

    result = frame[["game_pk", "player_id", "sp_id", "lineup_slot"]].copy()
    for k in ("exp_pa", "exp_h", "exp_tb", "exp_hr", "exp_bb", "exp_k",
              "p_hit", "p_hr", "p_tb2", "p_bb", "exp_rbi"):
        result[k] = agg[k]
    records = result.assign(model_version=VERSION, data_through_date=asof)
    records = records.astype(object).where(records.notna(), None)
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO batter_predictions
                (game_pk, player_id, model_version, data_through_date, sp_id,
                 lineup_slot, exp_pa, exp_h, exp_tb, exp_hr, exp_bb, exp_k,
                 p_hit, p_hr, p_tb2, p_bb, exp_rbi)
            VALUES (:game_pk, :player_id, :model_version, :data_through_date, :sp_id,
                    :lineup_slot, :exp_pa, :exp_h, :exp_tb, :exp_hr, :exp_bb, :exp_k,
                    :p_hit, :p_hr, :p_tb2, :p_bb, :exp_rbi)
            ON CONFLICT (game_pk, player_id, model_version) DO UPDATE SET
                data_through_date = EXCLUDED.data_through_date,
                sp_id = EXCLUDED.sp_id, lineup_slot = EXCLUDED.lineup_slot,
                exp_pa = EXCLUDED.exp_pa, exp_h = EXCLUDED.exp_h,
                exp_tb = EXCLUDED.exp_tb, exp_hr = EXCLUDED.exp_hr,
                exp_bb = EXCLUDED.exp_bb, exp_k = EXCLUDED.exp_k,
                p_hit = EXCLUDED.p_hit, p_hr = EXCLUDED.p_hr,
                p_tb2 = EXCLUDED.p_tb2, p_bb = EXCLUDED.p_bb,
                exp_rbi = EXCLUDED.exp_rbi, created_at = now()
        """), records.to_dict("records"))

    # B7 (shipped 2026-07-17): starter-scoped heads. exp_k/bb/h = w_sp x
    # sum over the opposing nine of exp_pa x P(outcome | vs this SP), with
    # w_sp = the starter's own expected PA share (clip(IP_per_start/9,
    # .40, .85); walk-forward: K MAE 1.812 vs 1.888 SP-marginal, p<.0001).
    if has_sp.any():
        from features.batter_features import CLASSES
        i_k = CLASSES.index("K")
        i_bb = CLASSES.index("BB")
        hit_idx = [CLASSES.index(c) for c in ("1B", "2B", "3B", "HR")]
        sp_look = team_features._sp_lookup(team_features._load_starts(asof))
        game_dates = {g.game_pk: pd.Timestamp(g.game_date).to_datetime64()
                      for g in slate.itertuples()}
        sub = frame[has_sp]
        sp_rows = pd.DataFrame({
            "game_pk": sub["game_pk"].to_numpy(),
            "sp_id": sub["sp_id"].to_numpy(),
            "k": agg["exp_pa"][has_sp] * p_sp[:, i_k],
            "bb": agg["exp_pa"][has_sp] * p_sp[:, i_bb],
            "h": agg["exp_pa"][has_sp] * p_sp[:, hit_idx].sum(axis=1),
        })
        sp_g = sp_rows.groupby(["game_pk", "sp_id"], as_index=False).agg(
            n_batters=("k", "size"), k=("k", "sum"), bb=("bb", "sum"), h=("h", "sum"))
        sp_g = sp_g[sp_g["n_batters"] == 9].copy()
        if len(sp_g):
            w_sp = []
            for r in sp_g.itertuples():
                ip = sp_look(int(r.sp_id), game_dates[r.game_pk]) \
                    .get("SP_IP_PER_START_L10", np.nan)
                w_sp.append(bundle["w"] if ip is None or np.isnan(ip)
                            else float(np.clip(ip / 9.0, 0.40, 0.85)))
            sp_g["w_sp"] = w_sp
            for c in ("k", "bb", "h"):
                sp_g[c] = sp_g["w_sp"] * sp_g[c]
            sp_recs = sp_g.rename(columns={"k": "exp_k", "bb": "exp_bb", "h": "exp_h"}) \
                .assign(model_version=VERSION, data_through_date=asof)
            sp_recs = sp_recs.astype(object).where(sp_recs.notna(), None)
            with get_engine().begin() as conn:
                conn.execute(text("""
                    INSERT INTO pitcher_predictions
                        (game_pk, sp_id, model_version, data_through_date,
                         w_sp, n_batters, exp_k, exp_bb, exp_h)
                    VALUES (:game_pk, :sp_id, :model_version, :data_through_date,
                            :w_sp, :n_batters, :exp_k, :exp_bb, :exp_h)
                    ON CONFLICT (game_pk, sp_id, model_version) DO UPDATE SET
                        data_through_date = EXCLUDED.data_through_date,
                        w_sp = EXCLUDED.w_sp, n_batters = EXCLUDED.n_batters,
                        exp_k = EXCLUDED.exp_k, exp_bb = EXCLUDED.exp_bb,
                        exp_h = EXCLUDED.exp_h, created_at = now()
                """), sp_recs.to_dict("records"))
            log.info("wrote %d starter predictions", len(sp_recs))

    result.attrs["warnings"] = warnings
    return result


def summarize(slate, team_preds, batter_preds) -> None:
    teams = pd.read_sql(text("SELECT team_id, abbrev FROM teams"), get_engine())
    abbrev = teams.set_index("team_id")["abbrev"]
    names = pd.read_sql(text("SELECT player_id, full_name FROM players"), get_engine()) \
        .set_index("player_id")["full_name"]

    print(f"\n=== slate: {len(slate)} games ===")
    lgbm = team_preds[team_preds["model_type"] == "lgbm_runs"].set_index("game_pk")
    elo = team_preds[team_preds["model_type"] == "elo"].set_index("game_pk")
    for g in slate.itertuples():
        l, e = lgbm.loc[g.game_pk], elo.loc[g.game_pk]
        print(f"  {abbrev.get(g.away_team_id, '?'):3s} @ {abbrev.get(g.home_team_id, '?'):3s}"
              f"  p_home lgbm {l['p_home']:.3f} / elo {e['p_home']:.3f}"
              f" | margin {l['pred_margin']:+.2f} | total {l['pred_total']:.2f}")
    if len(batter_preds):
        print("\n  top 5 HR probabilities today:")
        for r in batter_preds.nlargest(5, "p_hr").itertuples():
            print(f"    {names.get(r.player_id, r.player_id):24s} p_hr {r.p_hr:.3f}"
                  f"  exp_tb {r.exp_tb:.2f}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    # Site clock is US Eastern (MLB's schedule date). The Fargate container
    # runs UTC, where local "today" rolls to tomorrow at 8pm ET — mid-slate —
    # so the default must be timezone-explicit, never Timestamp.now().
    ap.add_argument("--date",
                    default=str(pd.Timestamp.now(tz="America/New_York").date()))
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument("--scores-only", action="store_true",
                    help="import games that have gone final and exit")
    args = ap.parse_args()
    target = args.date
    asof = (pd.Timestamp(target) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    probe_officials(target)  # every tick, before any heavy work (best-effort)

    if args.scores_only:
        refresh_scores(target)
        # Finals landing is exactly what turns a prediction into a grade, so
        # the rollups have to move on this tick too — otherwise the site's
        # record would lag the scores it is showing beside it.
        grades.refresh()
        return

    if not args.skip_ingest:
        refresh_ingest(target)
    park_factors.main()

    slate, posted = fetch_slate(target)

    # Benchmark lines (best-effort; never blocks predictions): morning line
    # for today, last available line for yesterday as the closing capture.
    from ingestion import odds_espn
    for capture_date, closing in ((target, False), (asof, True)):
        try:
            odds_espn.capture(capture_date, closing=closing)
        except Exception as exc:
            log.warning("odds capture %s failed: %s", capture_date, exc)

    if slate.empty:
        log.info("no games scheduled for %s", target)
        return
    # E6b: pregame weather forecasts (best-effort; NaN on failure is the
    # pre-E6b behavior, never blocks predictions)
    weather = None
    try:
        from ingestion import weather_forecast
        venues = pd.read_sql(text(
            "SELECT venue_id, latitude, longitude, roof_type FROM venues"), get_engine())
        weather = weather_forecast.fetch_forecasts(slate, venues)
    except Exception as exc:
        log.warning("weather forecasts failed: %s", exc)

    game_lineups = _game_lineups(slate, posted, _projected_lineups())
    team_preds = predict_team(slate, target, asof, lineups=game_lineups,
                              weather=weather)
    batter_preds = predict_batters(slate, target, asof, lineups=game_lineups)
    # Serving rollups last: they read the predictions this run just wrote.
    grades.refresh()
    summarize(slate, team_preds, batter_preds)
    warnings = team_preds.attrs.get("warnings", []) + batter_preds.attrs.get("warnings", [])
    print(f"\n{'!!! ' + str(len(warnings)) + ' TRIPWIRE WARNINGS' if warnings else 'all sanity checks passed'}")


if __name__ == "__main__":
    main()
