# Diamondbacks Win Text Alert

Sends your wife a text message every time the Arizona Diamondbacks win a baseball game.

## How it works

1. Polls the [MLB Stats API](https://statsapi.mlb.com) every 15 minutes (configurable)
2. Detects when a Diamondbacks game has ended with a D-backs win
3. Sends a text via **iMessage** or **email-to-SMS** carrier gateway
4. Tracks notified games so you never get duplicate texts

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Then pick a notification method:

### Option A: iMessage (macOS only — recommended)

Requires running on a Mac with Messages.app signed into iMessage.

```env
NOTIFY_METHOD=imessage
TO_PHONE_NUMBER=+14155556789
```

That's it — no API keys, no accounts, no cost.

### Option B: Email-to-SMS (any platform — free)

Uses your email to send a text through your wife's carrier SMS gateway. Works on Mac, Linux, or Windows.

```env
NOTIFY_METHOD=email_sms
TO_PHONE_NUMBER=+14155556789
CARRIER=verizon
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password
```

**Supported carriers:** att, tmobile, verizon, sprint, uscellular, boost, cricket, metro, googlefi, mint

> **Gmail users:** You'll need an [App Password](https://myaccount.google.com/apppasswords) (not your regular password).

### 3. Run the app

```bash
python app.py
```

The app checks immediately on startup and then every 15 minutes. Runs continuously — `Ctrl+C` to stop.

### Run in the background (optional)

```bash
nohup python app.py &
```

Or use a process manager like `systemd`, `supervisord`, or `pm2`.

## Example text message

> The Diamondbacks win! ⚾
> D-backs beat the Los Angeles Dodgers 5-3 at home!
> Go D-backs! 🐍
