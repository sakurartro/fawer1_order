import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
TZ = ZoneInfo(os.getenv("BOT_TZ", "Europe/Moscow"))
DB_PATH = "bot.db"

MIN_LEN = 5      # короче — сообщение не засчитывается
COOLDOWN = 10    # секунд между засчитанными сообщениями одного человека


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")
