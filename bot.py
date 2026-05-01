import logging
import os
from typing import Optional, List

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
YOUR_CHAT_ID = int(os.environ["YOUR_CHAT_ID"])
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COL_TICKER = 2
COL_ACTION = 3
COL_ENTRY = 4
COL_T1 = 5
COL_SL = 8
COL_STATUS = 9
COL_CURRENT = 10


def get_sheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON, scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).sheet1


def is_authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == YOUR_CHAT_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "👋 <b>TG Signal Bot</b>\n\n"
        "/status — Active signals\n"
        "/summary — Signal stats\n"
        "/help — Show commands",
        parse_mode="HTML",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        sheet = get_sheet()
        rows: List[List[str]] = sheet.get_all_values()[1:]
        active = [r for r in rows if len(r) > COL_STATUS and r[COL_STATUS].upper() == "ACTIVE"]

        if not active:
            await update.message.reply_text("No active signals.")
            return

        lines = [f"<b>Active Signals ({len(active)})</b>"]
        for r in active[:20]:
            ticker = r[COL_TICKER] if len(r) > COL_TICKER else "?"
            action = r[COL_ACTION] if len(r) > COL_ACTION else "?"
            entry = r[COL_ENTRY] if len(r) > COL_ENTRY else "?"
            current = r[COL_CURRENT] if len(r) > COL_CURRENT and r[COL_CURRENT] else None
            t1 = r[COL_T1] if len(r) > COL_T1 and r[COL_T1] else None
            sl = r[COL_SL] if len(r) > COL_SL and r[COL_SL] else None

            line = f"• <b>{ticker}</b> {action} @ {entry}"
            if current:
                line += f" | Now: {current}"
            if t1:
                line += f" | T1: {t1}"
            if sl:
                line += f" | SL: {sl}"
            lines.append(line)

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception as exc:
        logger.error("Status error: %s", exc)
        await update.message.reply_text(f"Error: {exc}")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    try:
        sheet = get_sheet()
        rows: List[List[str]] = sheet.get_all_values()[1:]

        counts: dict = {}
        for r in rows:
            if len(r) > COL_STATUS:
                s = r[COL_STATUS].upper()
                counts[s] = counts.get(s, 0) + 1

        total = sum(counts.values())
        msg = (
            f"<b>Signal Summary</b>\n"
            f"Total: {total}\n"
            f"Active: {counts.get('ACTIVE', 0)}\n"
            f"T1 Hit: {counts.get('T1_HIT', 0)}\n"
            f"T2 Hit: {counts.get('T2_HIT', 0)}\n"
            f"T3 Hit: {counts.get('T3_HIT', 0)}\n"
            f"SL Hit: {counts.get('SL_HIT', 0)}\n"
            f"Closed: {counts.get('CLOSED', 0)}"
        )
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as exc:
        logger.error("Summary error: %s", exc)
        await update.message.reply_text(f"Error: {exc}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "<b>Commands</b>\n"
        "/start — Welcome\n"
        "/status — View active signals\n"
        "/summary — Signal stats\n"
        "/help — This message",
        parse_mode="HTML",
    )


def main() -> None:
    logger.info("Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("help", help_cmd))
    logger.info("Bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
