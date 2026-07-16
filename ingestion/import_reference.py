"""Import reference tables: teams (StatsAPI), venues (StatsAPI), and the
Chadwick Bureau player-ID crosswalk.

Usage:
    python -m ingestion.import_reference            # teams + venues
    python -m ingestion.import_reference --chadwick # also the ID crosswalk
"""

import argparse
import io
import logging

import pandas as pd
import requests
from sqlalchemy import text

from core.db import get_engine
from ingestion import statsapi_client

log = logging.getLogger("import_reference")

CHADWICK_URL = "https://raw.githubusercontent.com/chadwickbureau/register/master/data/people-{shard}.csv"
CHADWICK_COLS = ["key_mlbam", "key_fangraphs", "key_bbref", "key_retro",
                 "name_first", "name_last", "mlb_played_first", "mlb_played_last"]


def import_teams(season: int = 2025) -> int:
    rows = [
        {
            "team_id": t["id"],
            "name": t.get("name"),
            "abbrev": t.get("abbreviation"),
            "league": t.get("league", {}).get("name"),
            "division": t.get("division", {}).get("name"),
            "venue_id": t.get("venue", {}).get("id"),
            "first_season": int(t["firstYearOfPlay"]) if t.get("firstYearOfPlay") else None,
            "active": t.get("active"),
        }
        for t in statsapi_client.teams(season)
    ]
    with get_engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO teams (team_id, name, abbrev, league, division,
                                   venue_id, first_season, active)
                VALUES (:team_id, :name, :abbrev, :league, :division,
                        :venue_id, :first_season, :active)
                ON CONFLICT (team_id) DO UPDATE SET
                    name = EXCLUDED.name, abbrev = EXCLUDED.abbrev,
                    league = EXCLUDED.league, division = EXCLUDED.division,
                    venue_id = EXCLUDED.venue_id, active = EXCLUDED.active,
                    updated_at = now()
            """),
            rows,
        )
    return len(rows)


def import_venues() -> int:
    rows = []
    for v in statsapi_client.venues():
        location = v.get("location", {})
        field_info = v.get("fieldInfo", {})
        coords = location.get("defaultCoordinates") or {}
        elevation = location.get("elevation")
        rows.append({
            "venue_id": v["id"],
            "name": v.get("name"),
            "city": location.get("city"),
            "state": location.get("stateAbbrev") or location.get("state"),
            "elevation": int(elevation) if elevation else None,
            "roof_type": field_info.get("roofType"),
            "capacity": field_info.get("capacity"),
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
        })
    with get_engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO venues (venue_id, name, city, state, elevation,
                                    roof_type, capacity, latitude, longitude)
                VALUES (:venue_id, :name, :city, :state, :elevation,
                        :roof_type, :capacity, :latitude, :longitude)
                ON CONFLICT (venue_id) DO UPDATE SET
                    name = EXCLUDED.name, city = EXCLUDED.city,
                    state = EXCLUDED.state, elevation = EXCLUDED.elevation,
                    roof_type = EXCLUDED.roof_type, capacity = EXCLUDED.capacity,
                    latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude,
                    updated_at = now()
            """),
            rows,
        )
    return len(rows)


def import_chadwick() -> int:
    """Load the MLBAM<->FanGraphs/BBRef/Retrosheet crosswalk for MLB players.

    The register is sharded people-0..f; we keep rows with an MLBAM id that
    actually reached MLB (mlb_played_first present) — ~23k rows.
    """
    frames = []
    for shard in "0123456789abcdef":
        url = CHADWICK_URL.format(shard=shard)
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), usecols=CHADWICK_COLS, low_memory=False)
        df = df.dropna(subset=["key_mlbam", "mlb_played_first"])
        frames.append(df)
        log.info("shard %s: %d MLB players", shard, len(df))
    all_players = pd.concat(frames).drop_duplicates(subset=["key_mlbam"])
    for col in ("key_mlbam", "key_fangraphs", "mlb_played_first", "mlb_played_last"):
        all_players[col] = all_players[col].astype("Int64")
    all_players = all_players.astype(object).where(all_players.notna(), None)
    records = [
        {
            "player_id": r["key_mlbam"], "key_fangraphs": r["key_fangraphs"],
            "key_bbref": r["key_bbref"], "key_retro": r["key_retro"],
            "name_first": r["name_first"], "name_last": r["name_last"],
            "mlb_played_first": r["mlb_played_first"], "mlb_played_last": r["mlb_played_last"],
        }
        for r in all_players.to_dict("records")
    ]
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM players_xref"))
        for i in range(0, len(records), 5000):
            conn.execute(
                text("""
                    INSERT INTO players_xref (player_id, key_fangraphs, key_bbref, key_retro,
                                              name_first, name_last, mlb_played_first, mlb_played_last)
                    VALUES (:player_id, :key_fangraphs, :key_bbref, :key_retro,
                            :name_first, :name_last, :mlb_played_first, :mlb_played_last)
                    ON CONFLICT (player_id) DO NOTHING
                """),
                records[i : i + 5000],
            )
    return len(records)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chadwick", action="store_true", help="also import the ID crosswalk")
    args = ap.parse_args()

    log.info("teams: %d", import_teams())
    log.info("venues: %d", import_venues())
    if args.chadwick:
        log.info("players_xref: %d", import_chadwick())


if __name__ == "__main__":
    main()
