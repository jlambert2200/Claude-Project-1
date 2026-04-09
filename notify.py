"""Notification backends for sending Diamondbacks win alerts."""

import os
import subprocess
import smtplib
from email.message import EmailMessage


def format_message(win):
    """Build the win alert message text."""
    score = f"{win['dbacks_score']}-{win['opponent_score']}"
    location = "at home" if win["home_away"] == "home" else "on the road"
    return (
        f"The Diamondbacks win! \u26be\n"
        f"D-backs beat the {win['opponent_name']} {score} {location}!\n"
        f"Go D-backs! \ud83d\udc0d"
    )


# ---------------------------------------------------------------------------
# iMessage (macOS only — sends via Messages.app)
# ---------------------------------------------------------------------------

def send_imessage(win):
    """Send an iMessage using osascript on macOS."""
    to_number = os.environ["TO_PHONE_NUMBER"]
    body = format_message(win)

    script = (
        f'tell application "Messages"\n'
        f'  set targetService to 1st account whose service type = iMessage\n'
        f'  set targetBuddy to participant "{to_number}" of targetService\n'
        f'  send "{body}" to targetBuddy\n'
        f'end tell'
    )

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return "imessage-sent"


# ---------------------------------------------------------------------------
# Email-to-SMS (carrier gateway — works on any platform, no API key needed)
# ---------------------------------------------------------------------------

CARRIER_GATEWAYS = {
    "att":      "{number}@txt.att.net",
    "tmobile":  "{number}@tmomail.net",
    "verizon":  "{number}@vtext.com",
    "sprint":   "{number}@messaging.sprintpcs.com",
    "uscellular": "{number}@email.uscc.net",
    "boost":    "{number}@sms.myboostmobile.com",
    "cricket":  "{number}@sms.cricketwireless.net",
    "metro":    "{number}@mymetropcs.com",
    "googlefi": "{number}@msg.fi.google.com",
    "mint":     "{number}@tmomail.net",
}


def send_email_sms(win):
    """Send an SMS via carrier email gateway using SMTP."""
    carrier = os.environ["CARRIER"].lower()
    phone = os.environ["TO_PHONE_NUMBER"].lstrip("+1").replace("-", "")
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    if carrier not in CARRIER_GATEWAYS:
        raise ValueError(
            f"Unknown carrier '{carrier}'. "
            f"Supported: {', '.join(sorted(CARRIER_GATEWAYS))}"
        )

    to_addr = CARRIER_GATEWAYS[carrier].format(number=phone)
    body = format_message(win)

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg["Subject"] = ""
    msg.set_content(body)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)

    return f"email-sms-sent-to-{to_addr}"


# ---------------------------------------------------------------------------
# Dispatcher — picks the right backend based on NOTIFY_METHOD env var
# ---------------------------------------------------------------------------

BACKENDS = {
    "imessage": send_imessage,
    "email_sms": send_email_sms,
}


def send_win_text(win):
    """Send a win notification using the configured method."""
    method = os.environ.get("NOTIFY_METHOD", "imessage")
    if method not in BACKENDS:
        raise ValueError(
            f"Unknown NOTIFY_METHOD '{method}'. "
            f"Supported: {', '.join(sorted(BACKENDS))}"
        )
    return BACKENDS[method](win)
