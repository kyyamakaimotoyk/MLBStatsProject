"""E6b: pregame weather forecasts from Open-Meteo (free, keyless, global —
covers Toronto where the NWS does not).

Fixes the totals-model train/serve mismatch: models train on game-time
weather (TEMP_F, WIND_SPEED_MPH) but the daily pipeline served NaN. Now
open-air games get the forecast for the hour nearest first pitch; domes get
the indoor convention (72F, no wind) matching how the feed records them.

Wind DIRECTION (WIND_OUT_MPH) still serves NaN — computing out/in needs park
orientation data we don't have (queued as E6c, Seamheads has it).
"""

import logging

import pandas as pd
import requests

log = logging.getLogger("weather_forecast")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
INDOOR = {"temp_f": 72.0, "wind_mph": 0.0}


def fetch_forecasts(slate: pd.DataFrame, venues: pd.DataFrame) -> dict:
    """game_pk -> {'temp_f', 'wind_mph'} for each slate game.

    slate needs game_pk, venue_id, first_pitch_utc (ISO string);
    venues needs venue_id, latitude, longitude, roof_type.
    """
    vmap = venues.set_index("venue_id")
    out = {}
    for g in slate.itertuples():
        if g.venue_id not in vmap.index:
            continue
        v = vmap.loc[g.venue_id]
        if v.get("roof_type") != "Open":
            out[g.game_pk] = dict(INDOOR)
            continue
        if pd.isna(v.get("latitude")) or pd.isna(v.get("longitude")):
            continue
        try:
            resp = requests.get(FORECAST_URL, params={
                "latitude": float(v["latitude"]), "longitude": float(v["longitude"]),
                "hourly": "temperature_2m,wind_speed_10m",
                "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                "forecast_days": 3, "timezone": "UTC",
            }, timeout=30)
            resp.raise_for_status()
            hourly = resp.json()["hourly"]
            times = pd.to_datetime(hourly["time"])
            target = pd.Timestamp(g.first_pitch_utc).tz_localize(None)
            idx = int(np_abs_argmin(times, target))
            out[g.game_pk] = {"temp_f": float(hourly["temperature_2m"][idx]),
                              "wind_mph": float(hourly["wind_speed_10m"][idx])}
        except Exception as exc:
            log.warning("forecast for game %s failed: %s", g.game_pk, exc)
    log.info("forecasts fetched for %d/%d games", len(out), len(slate))
    return out


def np_abs_argmin(times, target) -> int:
    deltas = abs(times - target)
    return int(deltas.argmin())
