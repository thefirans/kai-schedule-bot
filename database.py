"""
Database layer — stores user credentials and settings in SQLite.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "bot.db"


@dataclass
class User:
    chat_id: int
    nau_username: str
    nau_password: str
    reminder_minutes: int = 10
    is_active: bool = True
    active_week: int = 1  # current semester week (1-18)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id         INTEGER PRIMARY KEY,
                nau_username    TEXT NOT NULL,
                nau_password    TEXT NOT NULL,
                reminder_minutes INTEGER DEFAULT 10,
                is_active       INTEGER DEFAULT 1,
                active_week     INTEGER DEFAULT 1,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule_cache (
                chat_id     INTEGER,
                week        INTEGER,
                day         TEXT,
                time_start  TEXT,
                time_end    TEXT,
                name        TEXT,
                lesson_type TEXT,
                teacher     TEXT,
                room        TEXT,
                groups_info TEXT DEFAULT '',
                tags        TEXT DEFAULT '',
                cached_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id)
            )
        """)
        # Migration: add active_week column if missing (for existing DBs)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN active_week INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass  # column already exists


def save_user(user: User):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (chat_id, nau_username, nau_password, reminder_minutes, is_active, active_week)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                nau_username = excluded.nau_username,
                nau_password = excluded.nau_password,
                reminder_minutes = excluded.reminder_minutes,
                is_active = excluded.is_active,
                active_week = excluded.active_week
        """, (user.chat_id, user.nau_username, user.nau_password,
              user.reminder_minutes, user.is_active, user.active_week))


def get_user(chat_id: int) -> Optional[User]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if not row:
        return None
    return User(
        chat_id=row["chat_id"],
        nau_username=row["nau_username"],
        nau_password=row["nau_password"],
        reminder_minutes=row["reminder_minutes"],
        is_active=bool(row["is_active"]),
        active_week=row["active_week"],
    )


def get_all_active_users() -> list[User]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()
    return [
        User(
            chat_id=r["chat_id"],
            nau_username=r["nau_username"],
            nau_password=r["nau_password"],
            reminder_minutes=r["reminder_minutes"],
            is_active=True,
            active_week=r["active_week"],
        )
        for r in rows
    ]


def delete_user(chat_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedule_cache WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))


def update_reminder_minutes(chat_id: int, minutes: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET reminder_minutes = ? WHERE chat_id = ?", (minutes, chat_id))


def update_active_week(chat_id: int, week: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET active_week = ? WHERE chat_id = ?", (week, chat_id))


def cache_lessons(chat_id: int, lessons: list, active_week: int):
    """Replace cached schedule and update active week."""
    with get_conn() as conn:
        conn.execute("DELETE FROM schedule_cache WHERE chat_id = ?", (chat_id,))
        for l in lessons:
            conn.execute("""
                INSERT INTO schedule_cache
                (chat_id, week, day, time_start, time_end, name, lesson_type, teacher, room, groups_info, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chat_id, l.week, l.day, l.time_start, l.time_end,
                l.name, l.lesson_type, l.teacher, l.room,
                l.groups, ",".join(l.tags),
            ))
        conn.execute("UPDATE users SET active_week = ? WHERE chat_id = ?", (active_week, chat_id))


def get_cached_lessons(chat_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_cache WHERE chat_id = ? ORDER BY week, day, time_start",
            (chat_id,),
        ).fetchall()
    return [dict(r) for r in rows]