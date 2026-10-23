import hmac
import time
from contextlib import suppress
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import db
from config import ADMIN_PASSWORD, TZ, fmt
from scheduler import post, run_draw

# /start и /reg_admin доступны всем, остальное — только зарегистрированным админам в личке
reg_router = Router()
reg_router.message.filter(F.chat.type == "private")
router = Router()


class IsAdmin(Filter):
    async def __call__(self, event):
        return db.is_admin(event.from_user.id)


router.message.filter(F.chat.type == "private", IsAdmin())
router.callback_query.filter(IsAdmin())


class Form(StatesGroup):
    password = State()
    winners = State()
    topn = State()
    interval = State()
    dates = State()
    text = State()
    photo = State()


MAX_FAILS = 5


def kb(*rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


BACK = [("« Назад", "menu")]


async def show(event, text, markup):
    if hasattr(event, "data"):  # CallbackQuery
        with suppress(TelegramBadRequest):  # «message is not modified»
            await event.message.edit_text(text, reply_markup=markup)
        with suppress(TelegramBadRequest):  # розыгрыш мог идти долго, и запрос устарел
            await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


def schedule_text():
    if db.get("mode") == "repeat":
        return f"каждые {db.get('interval_days')} дн."
    ds = db.dates()
    return "по датам: " + (", ".join(fmt(x) for x in ds) if ds else "не заданы")


def main_menu():
    p = db.period()
    text = (
        f"Админ-панель\nЧат: {db.get('chat_id') or 'не привязан (отправь /bind в нужном чате)'}\n"
        f"Срок: {schedule_text()}\nКонец периода: {fmt(p['ends_at']) if p['ends_at'] else '⚠️ не задан, розыгрыша не будет (добавь даты в «Срок»)'}"
    )
    return text, kb(
        [("📊 Статистика", "stats")],
        [(f"🏆 Победителей: {db.get('winners_count')}", "set_winners")],
        [(f"🔝 Размер топа: {db.get('top_n')}", "set_topn")],
        [("⏱ Срок", "sched")],
        [("📝 Текст поста", "set_text"), ("🖼 Фото", "set_photo")],
        [("👁 Предпросмотр", "preview")],
        [("🎲 Разыграть сейчас", "now")],
        [("📜 История", "history")],
    )


def sched_menu():
    rows = [[("🔁 Повтор", "mode_repeat"), ("📅 Даты", "mode_dates")]]
    if db.get("mode") == "dates":
        rows.append([("➕ Добавить даты", "add_dates"), ("🗑 Очистить даты", "clear_dates")])
    return f"Срок розыгрыша: {schedule_text()}", kb(*rows, BACK)


@reg_router.message(Command("start"))
async def start(m, state: FSMContext):
    await state.clear()
    await m.answer("Бот работает. Админам: /admin")


@reg_router.message(Command("reg_admin"))
async def reg_admin(m, state: FSMContext):
    await state.set_state(Form.password)
    await m.answer("Введи пароль:")


@reg_router.message(Form.password, F.text)
async def check_password(m, state: FSMContext):
    uid = m.from_user.id
    with suppress(TelegramBadRequest):  # пароль не должен оставаться в чате
        await m.delete()
    fails = int(db.get(f"fails:{uid}") or 0)
    if fails >= MAX_FAILS:
        await state.clear()
        return await m.answer("Слишком много попыток.")
    if not hmac.compare_digest(m.text.encode(), ADMIN_PASSWORD.encode()):
        db.put(f"fails:{uid}", fails + 1)
        return await m.answer("Неверный пароль, попробуй ещё раз или /start для отмены.")
    db.add_admin(uid, m.from_user.username)
    await state.clear()
    if not m.from_user.username:
        return await m.answer("Ты админ. У тебя нет @username, поэтому в постах о победе указать тебя нельзя. Панель: /admin")
    await m.answer(
        f"Ты админ. Указывать твой @{m.from_user.username} внизу поста о победе, чтобы победители писали тебе за призом?",
        reply_markup=kb([("Да", "show_1"), ("Нет", "show_0")]),
    )


@router.callback_query(F.data.in_({"show_1", "show_0"}))
async def set_show(cb):
    db.set_show(cb.from_user.id, int(cb.data[-1]))
    await cb.message.edit_text("Сохранено. Выбор можно изменить, повторив /reg_admin. Панель: /admin")
    await cb.answer()


@router.message(Command("admin"))
async def admin(m, state: FSMContext):
    await state.clear()
    db.add_admin(m.from_user.id, m.from_user.username)  # обновляем username, если сменился
    await show(m, *main_menu())


@router.callback_query(F.data == "menu")
async def menu(cb, state: FSMContext):
    await state.clear()
    await show(cb, *main_menu())


@router.callback_query(F.data == "stats")
async def stats(cb):
    rows = db.top(db.period()["id"], 10)
    text = "\n".join(f"{i}. {escape(r['name'])} — {r['cnt']}" for i, r in enumerate(rows, 1)) or "Пока нет сообщений."
    await show(cb, "📊 Топ текущего периода:\n" + text, kb(BACK))


@router.callback_query(F.data == "history")
async def history(cb):
    rows = db.history(10)
    text = "\n".join(f"{fmt(r['drawn_at'])} — {escape(r['name'])}, {r['cnt']} сообщ." for r in rows) or "Пока пусто."
    await show(cb, "📜 Последние победители:\n" + text, kb(BACK))


@router.callback_query(F.data == "now")
async def now(cb):
    await show(cb, "Разыграть сейчас? Статистика периода обнулится.", kb([("Да, разыграть", "now_yes"), ("Отмена", "menu")]))


@router.callback_query(F.data == "now_yes")
async def now_yes(cb):
    await run_draw(cb.bot)
    await show(cb, *main_menu())


@router.callback_query(F.data.in_({"set_winners", "set_topn"}))
async def ask_number(cb, state: FSMContext):
    winners = cb.data == "set_winners"
    await state.set_state(Form.winners if winners else Form.topn)
    await cb.message.answer("Сколько победителей? (1–10, не больше размера топа)" if winners else "Размер топа? (1–100, не меньше числа победителей)")
    await cb.answer()


async def save_number(m, state, key, lo, hi):
    if not (m.text or "").strip().isdecimal() or not lo <= int(m.text) <= hi:
        return await m.answer(f"Нужно число от {lo} до {hi}.")
    db.put(key, int(m.text))
    await state.clear()
    await show(m, *main_menu())


@router.message(Form.winners)
async def set_winners(m, state: FSMContext):
    await save_number(m, state, "winners_count", 1, min(10, int(db.get("top_n"))))


@router.message(Form.topn)
async def set_topn(m, state: FSMContext):
    await save_number(m, state, "top_n", int(db.get("winners_count")), 100)


@router.callback_query(F.data == "sched")
async def sched(cb):
    await show(cb, *sched_menu())


@router.callback_query(F.data == "mode_repeat")
async def mode_repeat(cb, state: FSMContext):
    await state.set_state(Form.interval)
    await cb.message.answer("Каждые сколько дней проводить розыгрыш? (1–365)")
    await cb.answer()


@router.message(Form.interval)
async def set_interval(m, state: FSMContext):
    if not (m.text or "").strip().isdecimal() or not 1 <= int(m.text) <= 365:
        return await m.answer("Нужно число от 1 до 365.")
    db.put("mode", "repeat")
    db.put("interval_days", int(m.text))
    db.refresh_end()
    await state.clear()
    await show(m, *main_menu())


@router.callback_query(F.data == "mode_dates")
async def mode_dates(cb):
    db.put("mode", "dates")
    db.refresh_end()
    await show(cb, *sched_menu())


@router.callback_query(F.data == "add_dates")
async def add_dates(cb, state: FSMContext):
    await state.set_state(Form.dates)
    await cb.message.answer(f"Введи дату(ы), каждую с новой строки: ДД.ММ.ГГГГ ЧЧ:ММ (время {TZ.key})")
    await cb.answer()


def parse_dates(text):
    out = []
    for line in text.strip().splitlines():
        ts = int(datetime.strptime(line.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=TZ).timestamp())
        if ts <= time.time():
            raise ValueError("дата в прошлом")
        out.append(ts)
    return out


@router.message(Form.dates)
async def set_dates(m, state: FSMContext):
    try:
        items = parse_dates(m.text or "")
    except ValueError:
        return await m.answer("Не разобрал: формат ДД.ММ.ГГГГ ЧЧ:ММ, дата должна быть в будущем. Попробуй ещё раз.")
    db.add_dates(items)
    db.refresh_end()
    await state.clear()
    await show(m, *sched_menu())


@router.callback_query(F.data == "clear_dates")
async def clear_dates(cb):
    db.clear_dates()
    db.refresh_end()
    await show(cb, *sched_menu())


@router.callback_query(F.data == "set_text")
async def ask_text(cb, state: FSMContext):
    await state.set_state(Form.text)
    await cb.message.answer(
        "Текущий текст:\n\n" + escape(db.get("post_text"))
        + "\n\nПришли новый (до 900 символов, форматирование Telegram сохранится). "
        "{winner} заменится на упоминание победителя."
    )
    await cb.answer()


@router.message(Form.text, F.text)
async def set_text(m, state: FSMContext):
    if len(m.html_text) > 900:  # лимит подписи к фото 1024, остаток — под контакты админов
        return await m.answer("Слишком длинно, максимум 900 символов.")
    db.put("post_text", m.html_text)
    await state.clear()
    await show(m, *main_menu())


@router.callback_query(F.data == "set_photo")
async def ask_photo(cb, state: FSMContext):
    await state.set_state(Form.photo)
    await cb.message.answer("Пришли фото для поста (как фото, не файлом).", reply_markup=kb([("🗑 Убрать фото", "photo_clear")], BACK))
    await cb.answer()


@router.message(Form.photo, F.photo)
async def set_photo(m, state: FSMContext):
    db.put("post_photo", m.photo[-1].file_id)
    await state.clear()
    await show(m, *main_menu())


@router.callback_query(F.data == "photo_clear")
async def photo_clear(cb, state: FSMContext):
    db.put("post_photo", "")
    await state.clear()
    await show(cb, *main_menu())


@router.callback_query(F.data == "preview")
async def preview(cb):
    me = cb.from_user
    await post(cb.bot, cb.message.chat.id, f'<a href="tg://user?id={me.id}">{escape(me.full_name)}</a>')
    await cb.answer()
