import time

from aiogram import F, Router
from aiogram.filters import Command

import db
from config import COOLDOWN, MIN_LEN

router = Router()
GROUPS = F.chat.type.in_({"group", "supergroup"})
last_counted = {}  # user_id -> monotonic времени последнего засчитанного сообщения
chat_admins = {}   # chat_id -> (до какого момента кэш валиден, {user_id})


async def chat_admin_ids(bot, chat_id):
    expires, ids = chat_admins.get(chat_id, (0, set()))
    if expires < time.monotonic():
        ids = {a.user.id for a in await bot.get_chat_administrators(chat_id)}
        chat_admins[chat_id] = (time.monotonic() + 3600, ids)
    return ids


@router.message(F.migrate_to_chat_id)
async def migrated(m):
    if str(m.chat.id) == db.get("chat_id"):
        db.put("chat_id", m.migrate_to_chat_id)


@router.message(GROUPS, Command("bind"), F.from_user)
async def bind(m):
    if db.is_admin(m.from_user.id):
        db.put("chat_id", m.chat.id)
        await m.reply("Чат привязан, считаю активность.")


@router.message(GROUPS, F.from_user, ~F.from_user.is_bot)
async def count(m, bot):
    if str(m.chat.id) != db.get("chat_id") or m.sender_chat or m.is_automatic_forward:
        return
    text = (m.text or m.caption or "").strip()
    uid = m.from_user.id
    if len(text) < MIN_LEN or text.startswith("/"):
        return
    if time.monotonic() - last_counted.get(uid, -COOLDOWN) < COOLDOWN:
        return
    if db.is_admin(uid) or uid in await chat_admin_ids(bot, m.chat.id):
        return
    last_counted[uid] = time.monotonic()
    db.add_count(db.period()["id"], m.from_user)
