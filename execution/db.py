"""
Database initialization and helpers.
SQLite-backed storage for cases, conversations, lawyers, and call responses.
"""

import sqlite3
import os
from pathlib import Path

# Railway: set DB_PATH env var to a mounted volume path e.g. /data/lawbot.db
# Locally: defaults to .tmp/lawbot.db
_default = Path(__file__).parent.parent / ".tmp" / "lawbot.db"
DB_PATH = Path(os.environ.get("DB_PATH", str(_default)))


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                id          TEXT PRIMARY KEY,
                user_phone  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'intake',
                -- status: intake | researching | calling | complete
                case_json   TEXT,          -- structured case summary (JSON)
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id     TEXT NOT NULL,
                role        TEXT NOT NULL,  -- 'user' or 'assistant'
                content     TEXT NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );

            CREATE TABLE IF NOT EXISTS lawyers (
                id              TEXT PRIMARY KEY,
                case_id         TEXT NOT NULL,
                name            TEXT,
                firm            TEXT,
                phone           TEXT,
                address         TEXT,
                city            TEXT,
                state           TEXT,
                practice_areas  TEXT,       -- comma-separated
                google_place_id TEXT,
                rating          REAL,
                call_status     TEXT DEFAULT 'pending',
                -- pending | calling | answered | no_answer | declined | unreachable
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );

            CREATE TABLE IF NOT EXISTS call_responses (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                lawyer_id               TEXT NOT NULL,
                case_id                 TEXT NOT NULL,
                will_take_case          TEXT,   -- 'yes' | 'no' | 'maybe'
                fee_structure           TEXT,
                fee_range               TEXT,
                case_assessment         TEXT,
                next_steps              TEXT,
                contact_preference      TEXT,
                contact_detail          TEXT,
                notes                   TEXT,
                call_duration_seconds   INTEGER,
                recording_url           TEXT,
                twilio_call_sid         TEXT,
                full_transcript         TEXT,
                created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lawyer_id) REFERENCES lawyers(id),
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );

            -- Tracks real-world outcomes: did the lawyer work out?
            -- Keyed by google_place_id so reviews accumulate across all cases.
            CREATE TABLE IF NOT EXISTS lawyer_reviews (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                google_place_id TEXT NOT NULL,   -- links to lawyers.google_place_id
                lawyer_name     TEXT NOT NULL,
                case_id         TEXT NOT NULL,
                user_phone      TEXT NOT NULL,
                rating          INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                outcome         TEXT,            -- 'won' | 'settled' | 'lost' | 'dropped' | 'still_ongoing' | 'just_consulted'
                comment         TEXT,
                practice_area   TEXT,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );
        """)
    print(f"Database initialized at {DB_PATH}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_active_case(user_phone: str):
    """Return the most recent non-complete case for a user, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cases WHERE user_phone=? AND status != 'complete' ORDER BY created_at DESC LIMIT 1",
            (user_phone,)
        ).fetchone()
    return dict(row) if row else None


def get_messages(case_id: str):
    """Return all messages for a case in chronological order."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE case_id=? ORDER BY created_at ASC",
            (case_id,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def add_message(case_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (case_id, role, content) VALUES (?,?,?)",
            (case_id, role, content)
        )


def update_case(case_id: str, **kwargs):
    """Update arbitrary fields on a case row."""
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [case_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE cases SET {fields}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            values
        )


def get_lawyers_for_case(case_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM lawyers WHERE case_id=?", (case_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def save_lawyer_review(
    google_place_id: str,
    lawyer_name: str,
    case_id: str,
    user_phone: str,
    rating: int,
    outcome: str,
    comment: str,
    practice_area: str,
):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO lawyer_reviews
                (google_place_id, lawyer_name, case_id, user_phone,
                 rating, outcome, comment, practice_area)
            VALUES (?,?,?,?,?,?,?,?)
        """, (google_place_id, lawyer_name, case_id, user_phone,
              rating, outcome, comment, practice_area))


def get_lawyer_score(google_place_id: str) -> dict:
    """
    Return aggregated review stats for a lawyer by their Google Place ID.
    Returns avg_rating, review_count, outcome breakdown.
    """
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)            AS review_count,
                AVG(rating)         AS avg_rating,
                SUM(CASE WHEN outcome IN ('won','settled') THEN 1 ELSE 0 END) AS positive_outcomes,
                SUM(CASE WHEN outcome = 'lost' THEN 1 ELSE 0 END)             AS losses
            FROM lawyer_reviews
            WHERE google_place_id = ?
        """, (google_place_id,)).fetchone()

        comments = conn.execute("""
            SELECT rating, outcome, comment, created_at
            FROM lawyer_reviews
            WHERE google_place_id = ?
            ORDER BY created_at DESC
            LIMIT 5
        """, (google_place_id,)).fetchall()

    return {
        "review_count":      row["review_count"] or 0,
        "avg_rating":        round(row["avg_rating"], 1) if row["avg_rating"] else None,
        "positive_outcomes": row["positive_outcomes"] or 0,
        "losses":            row["losses"] or 0,
        "recent_comments":   [dict(c) for c in comments],
    }


if __name__ == "__main__":
    init_db()
