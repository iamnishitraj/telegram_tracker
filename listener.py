import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import Message
import anthropic
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
MONITORED_GROUPS_RAW = os.environ["MONITORED_GROUPS"]

MONITORED_GROUPS: List[Any] = []
for _g in MONITORED_GROUPS_RAW.split(","):
    _g = _g.strip()
    if _g:
        try:
            MONITORED_GROUPS.append(int(_g))
        except ValueError:
            MONITORED_GROUPS.append(_g)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PARSE_PROMPT = """You are a trading signal parser for Indian stock markets. Analyze the following Telegram message and extract any trading signals.

Return a JSON object with these fields (use null if not found):
- ticker: stock ticker/symbol as a string (e.g. "RELIANCE", "TCS", "NIFTY")
- action: "BUY" or "SELL" or null
- entry_price: entry/buy price as a number or null
- target1: first target price as a number or null
- target2: second target price as a number or null
- target3: third target price as a number or null
- stop_loss: stop loss price as a number or null
- is_signal: true if this is a clear trading signal, false otherwise

Message:
{message}

Return ONLY valid JSON, no explanation or markdown."""


def get_sheets_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    return gspread.authorize(creds)


def ensure_sheet_headers(sheet: gspread.Worksheet) -> None:
    headers = sheet.row_values(1)
    expected = [
        "Timestamp", "Group", "Ticker", "Action", "Entry Price",
        "Target 1", "Target 2", "Target 3", "Stop Loss",
        "Status", "Current Price", "Message",
    ]
    if headers != expected:
        sheet.update("A1:L1", [expected])
        logger.info("Sheet headers initialized")


def append_signal(
    sheet: gspread.Worksheet,
    group_name: str,
    parsed: Dict[str, Any],
    raw_message: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        now,
        group_name,
        parsed.get("ticker") or "",
        parsed.get("action") or "",
        parsed.get("entry_price") or "",
        parsed.get("target1") or "",
        parsed.get("target2") or "",
        parsed.get("target3") or "",
        parsed.get("stop_loss") or "",
        "ACTIVE",
        "",
        raw_message[:500],
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Signal appended: %s %s", parsed.get("ticker"), parsed.get("action"))


def parse_signal(ai_client: anthropic.Anthropic, message_text: str) -> Optional[Dict[str, Any]]:
    try:
        response = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[
                {"role": "user", "content": PARSE_PROMPT.format(message=message_text)}
            ],
        )
        text = response.content[0].text.strip()
        parsed = json.loads(text)
        if parsed.get("is_signal"):
            return parsed
        return None
    except Exception as exc:
        logger.warning("Parse error: %s", exc)
        return None


async def main() -> None:
    logger.info("Starting listener...")

    sheet: Optional[gspread.Worksheet] = None
    try:
        gc = get_sheets_client()
        sh = gc.open_by_key(SPREADSHEET_ID)
        sheet = sh.sheet1
        ensure_sheet_headers(sheet)
        logger.info("Google Sheets connected")
    except Exception as exc:
        logger.error("Sheets error: %s", exc)

    ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    tg_client = TelegramClient("listener_session", API_ID, API_HASH)
    await tg_client.start(phone=PHONE)
    logger.info("Telegram user client started")

    group_names: Dict[int, str] = {}
    for gid in MONITORED_GROUPS:
        try:
            entity = await tg_client.get_entity(gid)
            group_names[gid] = getattr(entity, "title", str(gid))
        except Exception as exc:
            logger.warning("Could not resolve group %s: %s", gid, exc)
            group_names[gid] = str(gid)

    @tg_client.on(events.NewMessage(chats=MONITORED_GROUPS))
    async def handler(event: events.NewMessage.Event) -> None:
        msg: Message = event.message
        text: str = msg.text or getattr(msg, "message", "") or ""
        if not text or len(text) < 10:
            return

        chat_id = event.chat_id
        group_name = group_names.get(chat_id, str(chat_id))
        logger.info("[%s] New message (%d chars)", group_name, len(text))

        parsed = parse_signal(ai_client, text)
        if parsed and sheet:
            append_signal(sheet, group_name, parsed, text)

    logger.info("Monitoring %d groups", len(MONITORED_GROUPS))
    await tg_client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
