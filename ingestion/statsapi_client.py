"""HTTP client for the MLB Stats API (statsapi.mlb.com).

Free, official, no key required. Retries with exponential backoff — budgeted
for API flakiness the way the NBA project's stats.nba.com scaffolding was,
though this API is far better behaved.
"""

import logging
import time

import requests

BASE = "https://statsapi.mlb.com"
TIMEOUT_SECONDS = 60
MAX_RETRIES = 4
# Regular season + all postseason rounds. Spring training and exhibitions
# are deliberately excluded (different context, different rosters).
GAME_TYPES = "R,F,D,L,W"

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers["User-Agent"] = "MLBStatsProject/0.1 (personal research)"


def get_json(path: str, params: dict | None = None) -> dict:
    delay = 2.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = _session.get(f"{BASE}{path}", params=params, timeout=TIMEOUT_SECONDS)
            if resp.status_code >= 500:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 400 <= status < 500:
                raise  # 4xx is permanent; don't burn retries
            if attempt == MAX_RETRIES:
                raise
        except (requests.RequestException, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise
            log.warning("attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, path, exc)
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


def schedule(start_date: str, end_date: str, game_types: str = GAME_TYPES,
             hydrate: str | None = None) -> list[dict]:
    """Flat list of schedule game dicts for a date range (inclusive).
    hydrate: e.g. 'probablePitcher' to embed probables in each game dict."""
    params = {"sportId": 1, "startDate": start_date, "endDate": end_date,
              "gameTypes": game_types}
    if hydrate:
        params["hydrate"] = hydrate
    data = get_json("/api/v1/schedule", params)
    return [g for d in data.get("dates", []) for g in d.get("games", [])]


def live_feed(game_pk: int) -> dict:
    """Full GUMBO feed: boxscore, plays, lineups, weather, officials, probables."""
    return get_json(f"/api/v1.1/game/{game_pk}/feed/live")


def teams(season: int) -> list[dict]:
    return get_json("/api/v1/teams", {"sportId": 1, "season": season}).get("teams", [])


def venues() -> list[dict]:
    return get_json("/api/v1/venues", {"hydrate": "location,fieldInfo"}).get("venues", [])
