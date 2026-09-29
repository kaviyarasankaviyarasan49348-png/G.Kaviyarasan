"""SQLite persistence for users and recommendation history."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DATABASE_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                full_name TEXT DEFAULT '',
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                category TEXT NOT NULL,
                budget REAL NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id, id DESC);
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def create_user(username: str, email: str, full_name: str, password_hash: str) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO users (username, email, full_name, password_hash, created_at) VALUES (?,?,?,?,?)",
            (username, email, full_name, password_hash, _now()),
        )
        return cur.lastrowid


def get_user_by_login(identifier: str):
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (identifier, identifier)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str):
    with get_conn() as c:
        row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def user_exists(username: str, email: str) -> bool:
    with get_conn() as c:
        row = c.execute(
            "SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)
        ).fetchone()
        return row is not None


def add_history(user_id: int, category: str, budget: float, request: dict, response: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO history (user_id, category, budget, request_json, response_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (user_id, category, budget, json.dumps(request), json.dumps(response), _now()),
        )
        return cur.lastrowid


def _row_to_history(row, include_plan: bool) -> dict:
    d = {
        "id": row["id"],
        "category": row["category"],
        "budget": row["budget"],
        "created_at": row["created_at"],
        "request": json.loads(row["request_json"]),
    }
    plan = json.loads(row["response_json"])
    d["summary"] = plan.get("summary", "")
    d["estimated_total"] = plan.get("estimated_total", 0)
    if include_plan:
        d["plan"] = plan
    return d


def list_history(user_id: int, category: str | None = None, limit: int = 100, include_plan=False):
    sql = "SELECT * FROM history WHERE user_id = ?"
    params: list = [user_id]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as c:
        return [_row_to_history(r, include_plan) for r in c.execute(sql, params).fetchall()]


def get_history_item(user_id: int, history_id: int):
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM history WHERE id = ? AND user_id = ?", (history_id, user_id)
        ).fetchone()
        return _row_to_history(row, True) if row else None


def count_history_by_category(user_id: int) -> dict:
    with get_conn() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) n FROM history WHERE user_id = ? GROUP BY category", (user_id,)
        ).fetchall()
        return {r["category"]: r["n"] for r in rows}
