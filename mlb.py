"""MLB Stats API client for checking Diamondbacks game results."""

import requests
from datetime import date

DIAMONDBACKS_TEAM_ID = 109
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def get_todays_games():
    """Fetch today's Diamondbacks games from the MLB Stats API."""
    today = date.today().isoformat()
    params = {
        "sportId": 1,
        "date": today,
        "teamId": DIAMONDBACKS_TEAM_ID,
        "hydrate": "team,linescore",
    }
    resp = requests.get(MLB_SCHEDULE_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for game_date in data.get("dates", []):
        games.extend(game_date.get("games", []))
    return games


def check_for_wins():
    """Check if the Diamondbacks won any games today.

    Returns a list of win result dicts with game details, or an empty list.
    """
    games = get_todays_games()
    wins = []

    for game in games:
        status = game.get("status", {}).get("abstractGameState")
        if status != "Final":
            continue

        teams = game.get("teams", {})
        away = teams.get("away", {})
        home = teams.get("home", {})

        dbacks_is_home = home.get("team", {}).get("id") == DIAMONDBACKS_TEAM_ID
        dbacks = home if dbacks_is_home else away
        opponent = away if dbacks_is_home else home

        if dbacks.get("isWinner"):
            wins.append({
                "game_pk": game.get("gamePk"),
                "dbacks_score": dbacks.get("score"),
                "opponent_score": opponent.get("score"),
                "opponent_name": opponent.get("team", {}).get("name"),
                "home_away": "home" if dbacks_is_home else "away",
                "date": game.get("officialDate", date.today().isoformat()),
            })

    return wins
