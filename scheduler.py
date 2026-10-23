import asyncio
import logging
import time
from contextlib import suppress
from html import escape

from aiogram.exceptions import TelegramAPIError

import db
from config import TEST_BOOST, TEST_BOOST_USER
from draw import pick_winners


def link(r):
    return f'<a href="tg://user?id={r["user_id"]}">{escape(r["name"])}</a>'


async def post(bot, chat_id, winners):
    """Пост с поздравлением: {winner} заменяется на победителей, внизу — контакты админов для выдачи приза."""
    text = db.get("post_text").replace("{winner}", winners)
    if contacts := db.prize_contacts():
        text += "\n\nЗа призом пиши: " + ", ".join(contacts)
    if photo := db.get("post_photo"):
        if len(text) <= 1024:  # лимит подписи; считаем с тегами, то есть с запасом
            return await bot.send_photo(chat_id, photo, caption=text)
        await bot.send_photo(chat_id, photo)
    return await bot.send_message(chat_id, text)


async def announce(bot, chat_id, winners):
    msg = await post(bot, chat_id, winners)
    try:
        await bot.pin_chat_message(chat_id, message_id=msg.message_id, disable_notification=True)
    except TelegramAPIError:
        return logging.warning("не удалось закрепить итоги: нужно право «Закреплять сообщения»")
    if old := db.get("pinned_id"):
        try:
            await bot.unpin_chat_message(chat_id, message_id=int(old))
        except TelegramAPIError:
            pass  # старое сообщение могли удалить или открепить вручную
    db.put("pinned_id", msg.message_id)


async def run_draw(bot):
    p = db.period()
    rows = db.top(p["id"], int(db.get("top_n")))
    ids = pick_winners([(r["user_id"], r["cnt"]) for r in rows], int(db.get("winners_count")))
    by_id = {r["user_id"]: r for r in rows}
    now = int(time.time())
    # БД меняем до отправки, чтобы второй вызов не разыграл тот же период
    for place, uid in enumerate(ids, 1):
        db.add_winner(p["id"], by_id[uid], place, now)
    db.close_period()
    db.open_period(now)
    if TEST_BOOST_USER:  # в начале периода, чтобы накрутка была видна в статистике
        db.boost(db.period()["id"], TEST_BOOST_USER, TEST_BOOST)
    if not ids:
        return
    winners = ", ".join(link(by_id[u]) for u in ids)
    try:
        if not db.get("chat_id"):
            raise RuntimeError("чат не привязан (/bind)")
        await announce(bot, int(db.get("chat_id")), winners)
    except Exception as e:  # победители уже записаны, поэтому предупреждаем админов, а не теряем итог
        logging.exception("не удалось объявить итоги в чат")
        for admin in db.admin_ids():
            with suppress(TelegramAPIError):
                await bot.send_message(admin, f"⚠️ Не удалось объявить итоги в чате: {escape(str(e))}\nПобедители: {winners}")


async def scheduler(bot):
    while True:
        try:
            p = db.period()
            if p["ends_at"] and p["ends_at"] <= time.time():
                await run_draw(bot)
        except Exception:
            logging.exception("ошибка розыгрыша")
        await asyncio.sleep(30)
