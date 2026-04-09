"""Diamondbacks Win Text Alert - sends an SMS every time the D-backs win."""

import os
import json
import logging
import time

import schedule
from dotenv import load_dotenv

from mlb import check_for_wins
from notify import send_win_text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

NOTIFIED_GAMES_FILE = "notified_games.json"


def load_notified_games():
    """Load the set of game IDs we've already sent texts for."""
    if os.path.exists(NOTIFIED_GAMES_FILE):
        with open(NOTIFIED_GAMES_FILE) as f:
            return set(json.load(f))
    return set()


def save_notified_games(game_ids):
    """Persist the set of notified game IDs."""
    with open(NOTIFIED_GAMES_FILE, "w") as f:
        json.dump(list(game_ids), f)


def check_and_notify():
    """Check for new Diamondbacks wins and send texts for any we haven't notified about."""
    log.info("Checking for Diamondbacks wins...")
    notified = load_notified_games()

    try:
        wins = check_for_wins()
    except Exception:
        log.exception("Failed to fetch game data")
        return

    if not wins:
        log.info("No wins found right now.")
        return

    for win in wins:
        game_id = str(win["game_pk"])
        if game_id in notified:
            log.info("Already notified for game %s — skipping.", game_id)
            continue

        log.info(
            "D-backs win! %s-%s vs %s. Sending text...",
            win["dbacks_score"],
            win["opponent_score"],
            win["opponent_name"],
        )
        try:
            result = send_win_text(win)
            log.info("Text sent! Result: %s", result)
            notified.add(game_id)
            save_notified_games(notified)
        except Exception:
            log.exception("Failed to send text for game %s", game_id)


def main():
    interval = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))
    log.info("Starting Diamondbacks Win Alert — checking every %d minutes.", interval)

    # Run once immediately on start
    check_and_notify()

    schedule.every(interval).minutes.do(check_and_notify)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
