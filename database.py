import sqlite3
import json

DB_FILE = "users.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            server_id INTEGER DEFAULT 21,
            interval_min INTEGER DEFAULT 5,
            monitor_active INTEGER DEFAULT 0,
            watchlist TEXT DEFAULT '[]',
            notified TEXT DEFAULT '[]'
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "server_id": row[1],
            "interval_min": row[2],
            "monitor_active": bool(row[3]),
            "watchlist": json.loads(row[4]),
            "notified": set(json.loads(row[5]))
        }
    else:
        # создаём дефолтную запись
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return {
            "user_id": user_id,
            "server_id": 21,
            "interval_min": 5,
            "monitor_active": False,
            "watchlist": [],
            "notified": set()
        }

def update_user(user_id: int, **kwargs):
    allowed = ["server_id", "interval_min", "monitor_active", "watchlist", "notified"]
    for k in kwargs:
        if k not in allowed:
            raise ValueError(f"Invalid field: {k}")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for k, v in kwargs.items():
        if k == "notified":
            v = json.dumps(list(v))
        elif k == "watchlist":
            v = json.dumps(v)
        elif k == "monitor_active":
            v = int(v)
        c.execute(f"UPDATE users SET {k}=? WHERE user_id=?", (v, user_id))
    conn.commit()
    conn.close()

def get_all_active_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE monitor_active=1")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]