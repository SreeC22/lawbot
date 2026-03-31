"""
Feedback handler.
Two flows:

1. PROACTIVE: After a case is marked complete, schedule a follow-up
   message to the user 7 days later asking how the lawyer worked out.

2. REACTIVE: User texts back unprompted (e.g. "the lawyer was great").
   Detect this and start the feedback collection flow.

Collected data: rating (1-5), outcome, optional comment.
Stored in lawyer_reviews keyed by google_place_id — accumulates across all users.
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from db import (
    get_conn, save_lawyer_review, get_lawyer_score,
    get_active_case, add_message, get_messages
)
from notifier import send_message

load_dotenv()

MODEL = "gpt-4o"

def _get_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

# In-memory state for users currently in feedback flow
# { user_phone: { "state": "awaiting_lawyer_choice"|"awaiting_rating"|"awaiting_outcome"|"awaiting_comment", ...} }
_feedback_state: dict[str, dict] = {}

FEEDBACK_PROMPT_DELAY_DAYS = 7


def send_followup_prompt(user_phone: str, case_id: str):
    """
    Called 7 days after a case completes.
    Asks the user how things went with the lawyer they chose.
    """
    lawyers = _get_recommended_lawyers(case_id)
    if not lawyers:
        return

    if len(lawyers) == 1:
        lawyer_line = f"you worked with *{lawyers[0]['name']}*"
        _feedback_state[user_phone] = {
            "stage": "awaiting_rating",
            "case_id": case_id,
            "lawyers": lawyers,
            "chosen_lawyer": lawyers[0],
        }
    else:
        names = "\n".join(f"{i+1}. {l['name']}" for i, l in enumerate(lawyers))
        lawyer_line = f"you had a few lawyer options:\n{names}\n\nWhich one did you end up going with? (Reply with the number, or say 'none')"
        _feedback_state[user_phone] = {
            "stage": "awaiting_lawyer_choice",
            "case_id": case_id,
            "lawyers": lawyers,
        }

    msg = (
        f"Hey! It's Lex. About a week ago I helped you find a lawyer — {lawyer_line}.\n\n"
        "How did it go? Would love to hear so I can give better recommendations to others in the future."
        if len(lawyers) == 1
        else
        f"Hey! It's Lex. A week ago I helped you find a lawyer. "
        f"Quick follow-up — {lawyer_line}"
    )
    send_message(user_phone, msg)


def handle_feedback_message(user_phone: str, message: str) -> str | None:
    """
    Handle a message from a user who is in a feedback flow.
    Returns the reply string, or None if this message isn't feedback.
    """
    state = _feedback_state.get(user_phone)

    # If no active feedback state, check if this looks like unprompted feedback
    if not state:
        if _looks_like_feedback(message):
            return _start_unprompted_feedback(user_phone, message)
        return None

    stage = state["stage"]

    if stage == "awaiting_lawyer_choice":
        return _handle_lawyer_choice(user_phone, message, state)

    elif stage == "awaiting_rating":
        return _handle_rating(user_phone, message, state)

    elif stage == "awaiting_outcome":
        return _handle_outcome(user_phone, message, state)

    elif stage == "awaiting_comment":
        return _handle_comment(user_phone, message, state)

    return None


def _looks_like_feedback(message: str) -> bool:
    """Quick heuristic: does this message sound like feedback about a lawyer?"""
    keywords = [
        "lawyer", "attorney", "great", "terrible", "awful", "amazing",
        "helped", "didn't help", "won", "lost", "settled", "dropped",
        "fired", "hired", "review", "rating", "feedback", "update"
    ]
    lower = message.lower()
    return any(kw in lower for kw in keywords)


def _start_unprompted_feedback(user_phone: str, message: str) -> str:
    """User texted about their lawyer experience without being prompted."""
    # Find their most recent completed case
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM cases WHERE user_phone=? AND status='complete' ORDER BY created_at DESC LIMIT 1",
            (user_phone,)
        ).fetchone()

    if not row:
        return None  # No completed case, treat as new intake

    case_id = row["id"]
    lawyers = _get_recommended_lawyers(case_id)

    if not lawyers:
        return None

    _feedback_state[user_phone] = {
        "stage": "awaiting_lawyer_choice" if len(lawyers) > 1 else "awaiting_rating",
        "case_id": case_id,
        "lawyers": lawyers,
        "chosen_lawyer": lawyers[0] if len(lawyers) == 1 else None,
        "initial_message": message,
    }

    if len(lawyers) == 1:
        return (
            f"Thanks for the update! Sounds like you're sharing feedback about *{lawyers[0]['name']}*. "
            "On a scale of 1–5, how would you rate them? (1 = terrible, 5 = excellent)"
        )
    else:
        names = "\n".join(f"{i+1}. {l['name']}" for i, l in enumerate(lawyers))
        return (
            f"Thanks for sharing! Which lawyer are you giving feedback on?\n{names}\n"
            "(Reply with the number)"
        )


def _handle_lawyer_choice(user_phone: str, message: str, state: dict) -> str:
    lawyers = state["lawyers"]
    msg = message.strip().lower()

    if msg == "none" or msg == "0":
        del _feedback_state[user_phone]
        return "No worries! If you ever need help finding a lawyer again, just text me anytime."

    try:
        idx = int(msg) - 1
        if 0 <= idx < len(lawyers):
            state["chosen_lawyer"] = lawyers[idx]
            state["stage"] = "awaiting_rating"
            _feedback_state[user_phone] = state
            return (
                f"Got it — *{lawyers[idx]['name']}*. "
                "On a scale of 1–5, how would you rate them overall? (1 = terrible, 5 = excellent)"
            )
    except ValueError:
        pass

    return f"Please reply with a number between 1 and {len(lawyers)}, or 'none'."


def _handle_rating(user_phone: str, message: str, state: dict) -> str:
    try:
        rating = int(message.strip())
        if not (1 <= rating <= 5):
            raise ValueError
    except ValueError:
        return "Please rate on a scale of 1 to 5 (e.g. reply '4')."

    state["rating"] = rating
    state["stage"] = "awaiting_outcome"
    _feedback_state[user_phone] = state

    return (
        "Thanks! How did the case turn out?\n\n"
        "Reply with:\n"
        "1 - Won / favorable outcome\n"
        "2 - Settled\n"
        "3 - Lost\n"
        "4 - Dropped / didn't pursue\n"
        "5 - Still ongoing\n"
        "6 - Just consulted, didn't hire"
    )


OUTCOME_MAP = {
    "1": "won", "2": "settled", "3": "lost",
    "4": "dropped", "5": "still_ongoing", "6": "just_consulted",
}

def _handle_outcome(user_phone: str, message: str, state: dict) -> str:
    outcome = OUTCOME_MAP.get(message.strip())
    if not outcome:
        return "Please reply with a number 1–6."

    state["outcome"] = outcome
    state["stage"] = "awaiting_comment"
    _feedback_state[user_phone] = state

    return (
        "Last question — anything you'd want other people to know about this lawyer? "
        "Or just reply 'skip' if you'd rather not."
    )


def _handle_comment(user_phone: str, message: str, state: dict) -> str:
    comment = None if message.strip().lower() == "skip" else message.strip()

    lawyer = state["chosen_lawyer"]
    case_id = state["case_id"]
    rating = state["rating"]
    outcome = state["outcome"]

    # Look up practice area from case
    with get_conn() as conn:
        case_row = conn.execute("SELECT case_json FROM cases WHERE id=?", (case_id,)).fetchone()
    practice_area = ""
    if case_row and case_row["case_json"]:
        practice_area = json.loads(case_row["case_json"]).get("practice_area", "")

    save_lawyer_review(
        google_place_id=lawyer.get("google_place_id", ""),
        lawyer_name=lawyer["name"],
        case_id=case_id,
        user_phone=user_phone,
        rating=rating,
        outcome=outcome,
        comment=comment,
        practice_area=practice_area,
    )

    del _feedback_state[user_phone]

    stars = "⭐" * rating
    return (
        f"Got it — {stars} for {lawyer['name']}. Thank you! "
        "This helps me give better recommendations to others in the same situation. "
        "If you ever need legal help again, I'm here."
    )


def _get_recommended_lawyers(case_id: str) -> list[dict]:
    """Return the lawyers that were recommended for this case (those who answered calls)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.id, l.name, l.google_place_id, cr.will_take_case
            FROM lawyers l
            JOIN call_responses cr ON l.id = cr.lawyer_id
            WHERE l.case_id = ? AND cr.will_take_case IN ('yes', 'maybe')
        """, (case_id,)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    # Simulate feedback flow in terminal
    phone = input("Test phone: ").strip()
    case_id = input("Case ID: ").strip()
    send_followup_prompt(phone, case_id)
    while True:
        msg = input("You: ").strip()
        reply = handle_feedback_message(phone, msg)
        if reply:
            print(f"Lex: {reply}")
        else:
            print("(no feedback state — would route to intake)")
