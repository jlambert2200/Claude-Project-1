# Diamondbacks Win Text Alert

Sends your wife a text message every time the Arizona Diamondbacks win a baseball game.

## How it works

1. Polls the [MLB Stats API](https://statsapi.mlb.com) every 15 minutes (configurable)
2. Detects when a Diamondbacks game has ended with a D-backs win
3. Sends an SMS via Twilio with the score and opponent
4. Tracks notified games so you never get duplicate texts

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create a Twilio account

1. Sign up at [twilio.com](https://www.twilio.com)
2. Get a phone number from the Twilio console
3. Note your Account SID and Auth Token

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Your Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token |
| `TWILIO_FROM_NUMBER` | Your Twilio phone number (e.g. `+14155551234`) |
| `TO_PHONE_NUMBER` | Your wife's phone number (e.g. `+14155556789`) |
| `CHECK_INTERVAL_MINUTES` | How often to check for results (default: `15`) |

### 4. Run the app

```bash
python app.py
```

The app will check immediately on startup and then every 15 minutes. It runs continuously — use `Ctrl+C` to stop.

### Run in the background (optional)

```bash
nohup python app.py &
```

Or use a process manager like `systemd`, `supervisord`, or `pm2`.

## Example text message

> The Diamondbacks win! ⚾
> D-backs beat the Los Angeles Dodgers 5-3 at home!
> Go D-backs! 🐍
