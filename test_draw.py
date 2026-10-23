import random
from types import SimpleNamespace

import db
from draw import pick_winners


def test_pick_winners():
    top = [(1, 50), (2, 5), (3, 1)]
    for k in range(5):
        w = pick_winners(top, k, random.Random(k))
        assert len(w) == min(k, 3) and len(set(w)) == len(w) and set(w) <= {1, 2, 3}
    assert pick_winners([], 1) == []
    wins = sum(pick_winners(top, 1, random.Random(i)) == [1] for i in range(500))
    assert wins > 400  # вес лидера 50/56


def test_period_reset():
    db.init(":memory:")
    user = SimpleNamespace(id=7, username="u", full_name="User")
    first = db.period()["id"]
    db.add_count(first, user)
    db.add_count(first, user)
    assert db.top(first, 10)[0]["cnt"] == 2
    db.close_period()
    db.open_period()
    second = db.period()["id"]
    assert second != first and db.top(second, 10) == []
    assert db.top(first, 10)[0]["cnt"] == 2  # история не стирается


def test_dates_mode():
    db.init(":memory:")
    db.put("mode", "dates")
    assert db.next_end(0, 0) is None
    db.add_dates([100, 200])
    assert db.next_end(0, 150) == 200


def test_post_and_announce():
    import asyncio
    from types import SimpleNamespace as U

    import scheduler
    db.init(":memory:")
    calls = []

    class Bot:
        async def send_photo(self, chat, photo, caption=None):
            calls.append(("photo", caption))
            return U(message_id=1)

        async def send_message(self, chat, text):
            calls.append(("msg", text))
            return U(message_id=2)

        async def pin_chat_message(self, chat, message_id, disable_notification):
            calls.append(("pin", message_id))

        async def unpin_chat_message(self, chat, message_id):  # как в aiogram: message_id только по имени
            calls.append(("unpin", message_id))

    db.put("post_photo", "F")
    db.put("pinned_id", 9)
    asyncio.run(scheduler.announce(Bot(), 5, "W"))
    assert calls == [("photo", "🎉 Поздравляем, W! Ты выиграл приз!\n\nПишите сообщения в чате — следующий розыгрыш скоро."), ("pin", 1), ("unpin", 9)]
    calls.clear()
    db.put("post_text", "x" * 2000)  # не влезает в подпись → фото и текст отдельно, закрепляем текст
    asyncio.run(scheduler.announce(Bot(), 5, "W"))
    assert [c[0] for c in calls] == ["photo", "msg", "pin", "unpin"] and calls[0][1] is None and calls[2][1] == 2


def test_refresh_end_never_in_past():
    import time
    db.init(":memory:")
    p = db.period()
    db.conn.execute("UPDATE periods SET started_at=? WHERE id=?", (int(time.time()) - 10 * 86400, p["id"]))
    db.put("interval_days", 1)  # прошло 10 дней, новый интервал 1 день
    db.refresh_end()
    assert db.period()["ends_at"] > time.time()
