import asyncio
import logging
import os
from typing import Optional, List, Dict

import requests
from dotenv import load_dotenv
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
YOUR_CHAT_ID = os.environ["YOUR_CHAT_ID"]
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
ALERT_THRESHOLD_PERCENT = float(os.getenv("ALERT_THRESHOLD_PERCENT", "2.0"))

CHECK_INTERVAL_SECONDS = 300  # every 5 minutes

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column indexes (0-based, matching sheet layout)
COL_TICKER = 2
COL_ACTION = 3
COL_ENTRY = 4
COL_T1 = 5
COL_T2 = 6
COL_T3 = 7
COL_SL = 8
COL_STATUS = 9
COL_CURRENT = 10


def get_sheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).sheet1


def send_telegram_alert(message: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": YOUR_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.error("Alert send failed: %s", exc)


def get_current_price(ticker: str) -> Optional[float]:
    """Try NSE (.NS) first, then BSE (.BO), then raw ticker."""
    for suffix in [".NS", ".BO", ""]:
        try:
            symbol = ticker.upper() + suffix
            info = yf.Ticker(symbol).fast_info
            price = info.last_price
            if price and price > 0:
                return float(price)
        except Exception:
            pass
    return None


def near_threshold(current: float, target: float, threshold_pct: float) -> bool:
    if target <= 0:
        return False
    return abs((current - target) / target) * 100 <= threshold_pct


def safe_float(val: object) -> Optional[float]:
    try:
        v = float(str(val).replace(",", ""))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def process_row(
    row_idx: int,
    row: List[str],
    sheet: gspread.Worksheet,
) -> Optional[str]:
    """Check one sheet row; return alert text if a threshold is hit."""
    if len(row) < COL_STATUS + 1:
        return None

    ticker = str(row[COL_TICKER]).strip()
    action = str(row[COL_ACTION]).strip().upper()
    status = str(row[COL_STATUS]).strip().upper()

    if not ticker or status in ("SL_HIT", "CLOSED", "T3_HIT"):
        return None

    current_price = get_current_price(ticker)
    if current_price is None:
        return None

    sheet.update_cell(row_idx + 2, COL_CURRENT + 1, current_price)

    sl = safe_float(row[COL_SL]) if len(row) > COL_SL else None
    t1 = safe_float(row[COL_T1]) if len(row) > COL_T1 else None
    t2 = safe_float(row[COL_T2]) if len(row) > COL_T2 else None
    t3 = safe_float(row[COL_T3]) if len(row) > COL_T3 else None

    alerts: List[str] = []

    # Stop-loss check
    sl_hit = (
        (action == "BUY" and sl and current_price <= sl) or
        (action == "SELL" and sl and current_price >= sl)
    )
    if sl_hit:
        alerts.append(
            f"🛑 SL HIT: <b>{ticker}</b> @ ₹{current_price:.2f} (SL: ₹{sl:.2f})"
        )
        sheet.update_cell(row_idx + 2, COL_STATUS + 1, "SL_HIT")
    else:
        # Target checks
        targets: List[tuple] = [(t1, "T1"), (t2, "T2"), (t3, "T3")]
        for target_price, label in targets:
            if target_price and near_threshold(current_price, target_price, ALERT_THRESHOLD_PERCENT):
                alerts.append(
                    f"🎯 {label} NEAR: <b>{ticker}</b> @ ₹{current_price:.2f}"
                    f" ({label}: ₹{target_price:.2f})"
                )
                if action == "BUY" and current_price >= target_price:
                    sheet.update_cell(row_idx + 2, COL_STATUS + 1, f"{label}_HIT")

    return "\n".join(alerts) if alerts else None


async def run_price_checks() -> None:
    logger.info("Price agent started (interval: %ds)", CHECK_INTERVAL_SECONDS)

    while True:
        try:
            sheet = get_sheet()
            all_rows = sheet.get_all_values()

            if len(all_rows) <= 1:
                logger.info("No signals in sheet yet")
            else:
                data_rows = all_rows[1:]
                alert_messages: List[str] = []

                for i, row in enumerate(data_rows):
                    msg = process_row(i, row, sheet)
                    if msg:
                        alert_messages.append(msg)
                    await asyncio.sleep(0.5)  # avoid Sheets rate limits

                if alert_messages:
                    send_telegram_alert("\n\n".join(alert_messages))
                    logger.info("Sent %d alert(s)", len(alert_messages))
                else:
                    logger.info("Checked %d row(s) — no alerts", len(data_rows))

        except Exception as exc:
            logger.error("Price check error: %s", exc)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_price_checks())
