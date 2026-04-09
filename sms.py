"""Twilio SMS integration for sending win alerts."""

import os
from twilio.rest import Client


def get_twilio_client():
    """Create a Twilio client from environment variables."""
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    return Client(account_sid, auth_token)


def send_win_text(win):
    """Send an SMS about a Diamondbacks win."""
    client = get_twilio_client()
    from_number = os.environ["TWILIO_FROM_NUMBER"]
    to_number = os.environ["TO_PHONE_NUMBER"]

    score = f"{win['dbacks_score']}-{win['opponent_score']}"
    location = "at home" if win["home_away"] == "home" else "on the road"

    message_body = (
        f"The Diamondbacks win! \u26be\n"
        f"D-backs beat the {win['opponent_name']} {score} {location}!\n"
        f"Go D-backs! \ud83d\udc0d"
    )

    message = client.messages.create(
        body=message_body,
        from_=from_number,
        to=to_number,
    )
    return message.sid
