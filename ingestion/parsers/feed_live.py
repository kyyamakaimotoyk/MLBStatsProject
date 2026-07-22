"""Parse a GUMBO live feed into row dicts for the core tables.

parse() is pure (dict in, dicts out) so it can be re-run over archived raw
JSON from S3 without touching the network.
"""


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _wind(weather: dict) -> tuple[int | None, str | None]:
    """'10 mph, Out To CF' -> (10, 'Out To CF')"""
    w = weather.get("wind") or ""
    if "mph" not in w:
        return None, (w or None)
    speed_part, _, dir_part = w.partition(",")
    try:
        return int(speed_part.strip().split()[0]), (dir_part.strip() or None)
    except (ValueError, IndexError):
        return None, w


def _ip_to_outs(ip) -> int | None:
    """Innings pitched '5.2' -> 17 outs."""
    if ip in (None, ""):
        return None
    whole, _, frac = str(ip).partition(".")
    try:
        return int(whole) * 3 + (int(frac) if frac else 0)
    except ValueError:
        return None


def parse(feed: dict) -> dict:
    gd = feed.get("gameData", {})
    ld = feed.get("liveData", {})
    game_pk = feed["gamePk"]

    linescore = ld.get("linescore", {})
    ls_teams = linescore.get("teams", {})
    weather = gd.get("weather", {})
    game_info = gd.get("gameInfo", {})
    wind_speed, wind_dir = _wind(weather)

    officials = [
        {
            "game_pk": game_pk,
            "official_type": o.get("officialType"),
            "official_id": o.get("official", {}).get("id"),
            "official_name": o.get("official", {}).get("fullName"),
        }
        for o in ld.get("boxscore", {}).get("officials", [])
        if o.get("officialType")
    ]
    hp_umpire_id = hp_umpire_name = None
    for o in officials:
        if o["official_type"] == "Home Plate":
            hp_umpire_id, hp_umpire_name = o["official_id"], o["official_name"]
            break

    game = {
        "game_pk": game_pk,
        "season": _int(gd.get("game", {}).get("season")),
        "game_type": gd.get("game", {}).get("type"),
        "game_date": gd.get("datetime", {}).get("officialDate"),
        "first_pitch_utc": game_info.get("firstPitch") or gd.get("datetime", {}).get("dateTime"),
        "status": gd.get("status", {}).get("detailedState"),
        "home_team_id": gd.get("teams", {}).get("home", {}).get("id"),
        "away_team_id": gd.get("teams", {}).get("away", {}).get("id"),
        "venue_id": gd.get("venue", {}).get("id"),
        "day_night": gd.get("datetime", {}).get("dayNight"),
        "doubleheader": gd.get("game", {}).get("doubleHeader"),
        "game_number": _int(gd.get("game", {}).get("gameNumber")),
        "scheduled_innings": _int(linescore.get("scheduledInnings")),
        "innings_played": len(linescore.get("innings", [])) or None,
        "home_score": ls_teams.get("home", {}).get("runs"),
        "away_score": ls_teams.get("away", {}).get("runs"),
        "weather_condition": weather.get("condition"),
        "temp_f": _int(weather.get("temp")),
        "wind_speed_mph": wind_speed,
        "wind_dir": wind_dir,
        "attendance": _int(game_info.get("attendance")),
        "duration_minutes": _int(game_info.get("gameDurationMinutes")),
        "hp_umpire_id": hp_umpire_id,
        "hp_umpire_name": hp_umpire_name,
        "is_final": gd.get("status", {}).get("abstractGameState") == "Final",
    }

    players = []
    for p in gd.get("players", {}).values():
        players.append({
            "player_id": p.get("id"),
            "full_name": p.get("fullName"),
            "birth_date": p.get("birthDate"),
            "bats": p.get("batSide", {}).get("code"),
            "throws": p.get("pitchHand", {}).get("code"),
            "primary_position": p.get("primaryPosition", {}).get("abbreviation"),
            "mlb_debut": p.get("mlbDebutDate"),
            "height": p.get("height"),
            "weight": _int(p.get("weight")),
            "active": p.get("active"),
        })

    probables = gd.get("probablePitchers", {})
    probable = {
        "game_pk": game_pk,
        "home_pitcher_id": probables.get("home", {}).get("id"),
        "away_pitcher_id": probables.get("away", {}).get("id"),
    }

    # Keyed by player_id: in a suspended game resumed after a trade, the same
    # player can appear in BOTH teams' boxscores (e.g. game_pk 746942). Keep
    # the entry with more playing time; the PK is (game_pk, player_id).
    lineups_by_pid, batters_by_pid, pitchers_by_pid = {}, {}, {}
    for side in ("home", "away"):
        box_side = ld.get("boxscore", {}).get("teams", {}).get(side, {})
        team_id = box_side.get("team", {}).get("id")
        is_home = side == "home"
        for entry in box_side.get("players", {}).values():
            pid = entry.get("person", {}).get("id")
            if pid is None:
                continue
            order_raw = _int(entry.get("battingOrder"))
            slot = order_raw // 100 if order_raw else None
            is_starter_bat = bool(order_raw) and order_raw % 100 == 0

            batting = entry.get("stats", {}).get("batting", {})
            if batting:
                h = _int(batting.get("hits")) or 0
                doubles = _int(batting.get("doubles")) or 0
                triples = _int(batting.get("triples")) or 0
                hr = _int(batting.get("homeRuns")) or 0
                ab = _int(batting.get("atBats")) or 0
                bb = _int(batting.get("baseOnBalls")) or 0
                hbp = _int(batting.get("hitByPitch")) or 0
                sf = _int(batting.get("sacFlies")) or 0
                sac = _int(batting.get("sacBunts")) or 0
                batter_line = {
                    "game_pk": game_pk, "player_id": pid, "team_id": team_id,
                    "is_home": is_home, "is_starter": is_starter_bat,
                    "batting_order_slot": slot,
                    "pa": _int(batting.get("plateAppearances")) or (ab + bb + hbp + sf + sac),
                    "ab": ab, "r": _int(batting.get("runs")), "h": h,
                    "doubles": doubles, "triples": triples, "hr": hr,
                    "tb": h + doubles + 2 * triples + 3 * hr,
                    "rbi": _int(batting.get("rbi")), "bb": bb,
                    "so": _int(batting.get("strikeOuts")), "hbp": hbp,
                    "sb": _int(batting.get("stolenBases")),
                    "cs": _int(batting.get("caughtStealing")),
                    "sf": sf, "sac": sac, "lob": _int(batting.get("leftOnBase")),
                }
                existing = batters_by_pid.get(pid)
                if existing is None or (batter_line["pa"] or 0) > (existing["pa"] or 0):
                    batters_by_pid[pid] = batter_line

            if is_starter_bat and pid not in lineups_by_pid:
                positions = entry.get("allPositions") or []
                start_pos = (positions[0].get("abbreviation") if positions
                             else entry.get("position", {}).get("abbreviation"))
                lineups_by_pid[pid] = {
                    "game_pk": game_pk, "player_id": pid, "team_id": team_id,
                    "batting_order": slot, "start_position": start_pos,
                }

            pitching = entry.get("stats", {}).get("pitching", {})
            if pitching:
                pitcher_line = {
                    "game_pk": game_pk, "player_id": pid, "team_id": team_id,
                    "is_home": is_home,
                    "is_starter": _int(pitching.get("gamesStarted")) == 1,
                    "outs": _ip_to_outs(pitching.get("inningsPitched")),
                    "batters_faced": _int(pitching.get("battersFaced")),
                    "h": _int(pitching.get("hits")), "r": _int(pitching.get("runs")),
                    "er": _int(pitching.get("earnedRuns")),
                    "bb": _int(pitching.get("baseOnBalls")),
                    "so": _int(pitching.get("strikeOuts")),
                    "hr": _int(pitching.get("homeRuns")),
                    "hbp": _int(pitching.get("hitByPitch")),
                    "pitches": _int(pitching.get("numberOfPitches"))
                               or _int(pitching.get("pitchesThrown")),
                    "strikes": _int(pitching.get("strikes")),
                }
                existing = pitchers_by_pid.get(pid)
                if existing is None or (pitcher_line["outs"] or 0) > (existing["outs"] or 0):
                    pitchers_by_pid[pid] = pitcher_line

    plays_by_index = {}
    for p in ld.get("plays", {}).get("allPlays", []):
        about = p.get("about", {})
        result = p.get("result", {})
        matchup = p.get("matchup", {})
        idx = about.get("atBatIndex")
        if idx is None:
            continue
        plays_by_index[idx] = {
            "game_pk": game_pk, "at_bat_index": idx,
            "inning": about.get("inning"), "is_top": about.get("isTopInning"),
            "batter_id": matchup.get("batter", {}).get("id"),
            "pitcher_id": matchup.get("pitcher", {}).get("id"),
            "bat_side": matchup.get("batSide", {}).get("code"),
            "pitch_hand": matchup.get("pitchHand", {}).get("code"),
            "event": result.get("event"), "event_type": result.get("eventType"),
            "description": result.get("description"), "rbi": result.get("rbi"),
            "outs_post": p.get("count", {}).get("outs"),
            "home_score_post": result.get("homeScore"),
            "away_score_post": result.get("awayScore"),
        }

    return {
        "game": game,
        "players": players,
        "probable": probable,
        "officials": officials,
        "lineups": list(lineups_by_pid.values()),
        "batter_lines": list(batters_by_pid.values()),
        "pitcher_lines": list(pitchers_by_pid.values()),
        "plays": list(plays_by_index.values()),
    }
