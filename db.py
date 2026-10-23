import sqlite3
import time

# shortcut: синхронный sqlite3 блокирует loop на микросекунды при каждом сообщении, перейти на aiosqlite при очень нагруженном чате
conn: sqlite3.Connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS draw_dates(at INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS periods(
    id INTEGER PRIMARY KEY AUTOINCREMENT, started_at INTEGER, ends_at INTEGER, closed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS counts(
    period_id INTEGER, user_id INTEGER, username TEXT, name TEXT, cnt INTEGER,
    PRIMARY KEY(period_id, user_id));
CREATE TABLE IF NOT EXISTS winners(
    period_id INTEGER, user_id INTEGER, name TEXT, username TEXT, place INTEGER, cnt INTEGER, drawn_at INTEGER);
"""

DEFAULTS = {"winners_count": "1", "top_n": "10", "mode": "repeat", "interval_days": "7",
    "post_text": "🎉 Поздравляем, {winner}! Ты выиграл приз!\n\nПишите сообщения в чате — следующий розыгрыш скоро.",
    "post_photo": ""}


def init(path):
    global conn
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(admins)")}
    for col, ddl in (("username", "TEXT"), ("show", "INTEGER DEFAULT 1")):
        if col not in cols:  # миграция старой БД
            conn.execute(f"ALTER TABLE admins ADD COLUMN {col} {ddl}")
    for k, v in DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
    period()


def get(key):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def put(key, value):
    conn.execute(
        "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def is_admin(user_id):
    return conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None


def add_admin(user_id, username):
    conn.execute(
        "INSERT INTO admins(user_id, username) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
        (user_id, username),
    )


def admin_ids():
    return [r[0] for r in conn.execute("SELECT user_id FROM admins")]


def set_show(user_id, show):
    conn.execute("UPDATE admins SET show=? WHERE user_id=?", (show, user_id))


def prize_contacts():
    return [f"@{r[0]}" for r in conn.execute("SELECT username FROM admins WHERE show=1 AND username IS NOT NULL")]


def dates():
    return [r[0] for r in conn.execute("SELECT at FROM draw_dates WHERE at > ? ORDER BY at", (int(time.time()),))]


def add_dates(items):
    conn.executemany("INSERT OR IGNORE INTO draw_dates VALUES (?)", [(x,) for x in items])


def clear_dates():
    conn.execute("DELETE FROM draw_dates")


def next_end(start, now):
    if get("mode") == "repeat":
        return start + int(get("interval_days")) * 86400
    return conn.execute("SELECT MIN(at) FROM draw_dates WHERE at > ?", (now,)).fetchone()[0]


def open_period(now=None):
    now = now or int(time.time())
    conn.execute("INSERT INTO periods(started_at, ends_at) VALUES (?,?)", (now, next_end(now, now)))


def period():
    row = conn.execute("SELECT * FROM periods WHERE closed=0").fetchone()
    if row is None:  # страховка: открытый период должен быть всегда
        open_period()
        row = conn.execute("SELECT * FROM periods WHERE closed=0").fetchone()
    return row


def close_period():
    conn.execute("UPDATE periods SET closed=1 WHERE closed=0")


def refresh_end():
    p, now = period(), int(time.time())
    end = next_end(p["started_at"], now)
    if end and end <= now:  # новый интервал короче уже прошедшего: считаем срок от сейчас, а не разыгрываем мгновенно
        end = next_end(now, now)
    conn.execute("UPDATE periods SET ends_at=? WHERE id=?", (end, p["id"]))


def add_count(period_id, user):
    conn.execute(
        """INSERT INTO counts VALUES (?,?,?,?,1) ON CONFLICT(period_id, user_id)
           DO UPDATE SET cnt=cnt+1, username=excluded.username, name=excluded.name""",
        (period_id, user.id, user.username, user.full_name),
    )


def boost(period_id, username, n):
    w = conn.execute(
        "SELECT user_id, name FROM winners WHERE username=? COLLATE NOCASE ORDER BY drawn_at DESC LIMIT 1", (username,)
    ).fetchone()
    if w:
        conn.execute(
            "INSERT INTO counts VALUES (?,?,?,?,?) ON CONFLICT(period_id, user_id) DO UPDATE SET cnt=cnt+?",
            (period_id, w["user_id"], username, w["name"], n, n),
        )


def top(period_id, n):
    return conn.execute(
        "SELECT * FROM counts WHERE period_id=? ORDER BY cnt DESC, user_id LIMIT ?", (period_id, n)
    ).fetchall()


def add_winner(period_id, row, place, now):
    conn.execute(
        "INSERT INTO winners VALUES (?,?,?,?,?,?,?)",
        (period_id, row["user_id"], row["name"], row["username"], place, row["cnt"], now),
    )


def history(n):
    return conn.execute("SELECT * FROM winners ORDER BY drawn_at DESC, place LIMIT ?", (n,)).fetchall()
