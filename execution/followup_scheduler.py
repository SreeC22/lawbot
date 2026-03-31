"""
Follow-up scheduler.
Runs as a background process (or cron job).
Checks for pending follow-up messages and sends them.

Run as a cron job every hour:
  0 * * * * cd /path/to/lawbot && python execution/followup_scheduler.py

Or keep it running in the background:
  python followup_scheduler.py --loop
"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from db import get_conn
from feedback_handler import send_followup_prompt

load_dotenv()


def run_due_followups():
    """Send any follow-ups that are due now."""
    with get_conn() as conn:
        # Create table in case it doesn't exist yet
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_followups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone  TEXT NOT NULL,
                case_id     TEXT NOT NULL,
                send_at     DATETIME NOT NULL,
                sent        INTEGER DEFAULT 0
            )
        """)
        due = conn.execute("""
            SELECT id, user_phone, case_id
            FROM scheduled_followups
            WHERE sent = 0 AND send_at <= datetime('now')
        """).fetchall()

    if not due:
        print("[scheduler] No follow-ups due.")
        return

    print(f"[scheduler] {len(due)} follow-up(s) due.")
    for row in due:
        try:
            send_followup_prompt(row["user_phone"], row["case_id"])
            with get_conn() as conn:
                conn.execute(
                    "UPDATE scheduled_followups SET sent=1 WHERE id=?", (row["id"],)
                )
            print(f"[scheduler] Sent follow-up to {row['user_phone']} for case {row['case_id']}")
        except Exception as e:
            print(f"[scheduler] Failed for {row['user_phone']}: {e}")


if __name__ == "__main__":
    loop_mode = "--loop" in sys.argv
    if loop_mode:
        print("[scheduler] Running in loop mode — checking every 15 minutes.")
        while True:
            run_due_followups()
            time.sleep(15 * 60)
    else:
        run_due_followups()
