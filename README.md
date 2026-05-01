# Telegram Signal Tracker

Monitors Telegram channels for stock recommendations, auto-parses them with Claude AI, tracks live prices, and fires alerts to your personal Telegram bot.

Built for Indian markets. Adaptable to any signal format.

---

## How It Works

Three processes run independently and share state through Google Sheets.

### `listener.py`
Connects as your Telegram user account via Telethon (not a bot — this is how it can read private groups you're a member of). Watches the groups you configure. When a new message arrives, sends it to Claude Haiku to determine if it's a trading signal. If it is, extracts ticker, entry price, stop loss, and targets, then appends a row to Google Sheets with status `ACTIVE`.

### `price_agent.py`
Polls every 5 minutes. Reads all `ACTIVE` rows from the sheet, fetches current prices via yfinance (tries NSE `.NS`, then BSE `.BO`, then raw ticker). If price crosses stop loss or comes within 2% of a target, sends a Telegram alert to your chat ID and updates the row status. Skips rows already marked `SL_HIT`, `T1_HIT`, `T2_HIT`, `T3_HIT`, or `CLOSED`.

### `bot.py`
Your private Telegram bot. Only responds to your chat ID. Query active signals or a summary on demand without opening the spreadsheet.

---

## Customizing for Your Use Case

This project parses Indian stock market recommendations that typically look like:

```
RELIANCE - BUY 2400-2450
SL: 2280 (weekly closing basis)
T1: 2600 | T2: 2800
Hold: 3-6 months | Allocation: 5%
```

Claude extracts: stock name, buy price/zone, stop loss (with type like weekly/daily closing), target prices (single or multiple), holding period, allocation %.

**You can adapt this to any signal format.** The only thing to change is the `PARSE_PROMPT` variable in `listener.py`. That string is the entire instruction Claude uses to interpret messages. Rewrite it to describe your format, update `append_signal()` to write the fields you care about, and update the Google Sheets columns to match.

What you can point this at:
- Crypto signals from a trading channel (BTC/ETH entries, targets, SL)
- US stock momentum alerts
- Options flow (strike, expiry, premium, direction)
- Forex signals (pair, entry zone, pips target)
- Any structured text that follows a consistent pattern

The price fetching, alert delivery, and sheet storage don't change.

---

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install telethon anthropic gspread google-auth python-telegram-bot yfinance python-dotenv requests
```

Requires Python 3.10+. On Python 3.9, see the troubleshooting section.

### 2. Get Telegram user API credentials

Go to [my.telegram.org](https://my.telegram.org) → API Development Tools → create an app. Save the `api_id` and `api_hash`. These let `listener.py` log in as your account.

### 3. Create a Telegram bot

Message [@BotFather](https://t.me/BotFather) → `/newbot` → follow prompts. Save the bot token.

Get your personal Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot).

### 4. Set up Google Sheets

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project
2. Enable **Google Sheets API** and **Google Drive API**
3. Go to IAM → Service Accounts → create one → download the JSON key → save as `credentials.json` in the project directory
4. Create a new Google Sheet
5. Share the sheet with the service account email (`client_email` field in `credentials.json`) as **Editor**
6. Copy the spreadsheet ID from the URL: `https://docs.google.com/spreadsheets/d/**<ID>**/edit`

### 5. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```env
# Telegram user credentials (from my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890

# Bot token (from BotFather) and your user ID
BOT_TOKEN=your_bot_token
YOUR_CHAT_ID=your_numeric_user_id

# Anthropic API key
ANTHROPIC_API_KEY=your_anthropic_key

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=credentials.json
SPREADSHEET_ID=your_spreadsheet_id

# Groups to monitor — comma-separated IDs or @usernames
MONITORED_GROUPS=-1001234567890,-1009876543210,@somegroup

# Alert when price is within this % of a target or stop loss
ALERT_THRESHOLD_PERCENT=2.0
```

**Finding group IDs**: Forward any message from the group to [@getidsbot](https://t.me/getidsbot). The numeric ID starts with `-100`.

### 6. Authenticate the listener

Run `listener.py` once manually. Telethon prompts for your phone number and the OTP Telegram sends you. This creates `listener_session.session`. Subsequent runs skip the prompt.

```bash
python listener.py
```

### 7. Run all three processes

```bash
# In three separate terminals:
python listener.py
python price_agent.py
python bot.py
```

For production, use a process manager like `supervisord`, `pm2`, or `systemd` to keep them running.

---

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/status` | All active signals with current price, T1, and SL |
| `/summary` | Signal counts by status (Active, T1/T2/T3 Hit, SL Hit, Closed) |
| `/help` | Command list |

The bot silently ignores all messages from users other than `YOUR_CHAT_ID`.

---

## Troubleshooting

### Python 3.9 type hint errors

`list[str]` and `dict[str, Any]` without imports require Python 3.10+. On Python 3.9, you'll get `TypeError` at startup. Fix: use `from typing import List, Dict` and replace bare `list[...]` / `dict[...]` annotations with `List[...]` / `Dict[...]`. The current code already uses `typing` imports for compatibility.

### SpreadsheetNotFound error

The service account doesn't have access to the sheet. Open the Google Sheet → Share → paste the service account email (found in `credentials.json` under `client_email`) → set role to Editor → Save.

### yfinance ticker not found

Yahoo Finance requires a suffix for Indian stocks: `.NS` for NSE, `.BO` for BSE. The price agent tries both automatically. If a ticker still returns `None`, verify the correct Yahoo Finance symbol by searching `TICKER.NS` on [finance.yahoo.com](https://finance.yahoo.com). Some stocks use a different symbol on Yahoo than on the exchange.

### Adding a new Telegram group

When the analyst creates a new channel or group:

1. Join it with your Telegram account
2. Forward any message from it to [@getidsbot](https://t.me/getidsbot) to get the group ID
3. Add the ID to `MONITORED_GROUPS` in your `.env` (comma-separated, no spaces)
4. Restart `listener.py`

No code changes needed.

---

## Architecture

```
Telegram groups
      │
      ▼
  listener.py ──── Claude Haiku ────► Google Sheets
  (Telethon user client)               (shared data store)
                                            │
                          ┌─────────────────┤
                          │                 │
                          ▼                 ▼
                   price_agent.py       bot.py
                   (polls every 5 min)  (query on demand)
                          │
                          ▼
                   Your Telegram chat
```

**`listener.py`** authenticates as your phone number (Telegram user client). This is why it can read private groups — the bot token approach cannot.

**`price_agent.py`** and **`bot.py`** use the bot token. They can only send messages.

**Google Sheets** is the only shared state. All three processes read/write it independently.

**`listener_session.session`** stores your Telegram auth token. Treat it like a password — it grants full access to your account. Add it to `.gitignore` and never commit it.
