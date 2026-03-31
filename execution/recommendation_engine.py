"""
Recommendation engine.
After all lawyer calls are complete, uses Claude to compare responses
and generate a clear recommendation. Sends the report to the user.
"""

import os
import json
from dotenv import load_dotenv
import anthropic
from db import get_conn, update_case, get_lawyer_score
from notifier import send_message

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-opus-4-6"


def generate_recommendation(case_id: str):
    """Generate and send the final comparison report to the user."""
    print(f"[recommendation] Generating report for case {case_id}")

    # Load case
    with get_conn() as conn:
        case_row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()

    if not case_row:
        print(f"[recommendation] Case {case_id} not found")
        return

    case_data = json.loads(case_row["case_json"]) if case_row["case_json"] else {}
    user_phone = case_row["user_phone"]

    # Load all lawyer responses
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.name, l.firm, l.phone, l.rating,
                   cr.will_take_case, cr.fee_structure, cr.fee_range,
                   cr.case_assessment, cr.next_steps, cr.contact_preference, cr.contact_detail
            FROM lawyers l
            LEFT JOIN call_responses cr ON l.id = cr.lawyer_id
            WHERE l.case_id=?
        """, (case_id,)).fetchall()

    lawyers_data = [dict(r) for r in rows]

    if not lawyers_data:
        send_message(user_phone, (
            "I wasn't able to reach any lawyers for your case. "
            "This sometimes happens if all numbers went to voicemail. "
            "Reply 'retry' and I'll try a new set of lawyers."
        ))
        return

    # Filter to willing lawyers
    willing = [l for l in lawyers_data if l.get("will_take_case") in ("yes", "maybe")]
    unreachable = [l for l in lawyers_data if not l.get("will_take_case")]
    declined = [l for l in lawyers_data if l.get("will_take_case") == "no"]

    if not willing:
        msg = (
            f"Unfortunately, none of the {len(lawyers_data)} lawyers I contacted were able to take your case right now. "
            f"{len(declined)} declined and {len(unreachable)} didn't answer. "
            "Reply 'retry' and I'll search for more lawyers."
        )
        send_message(user_phone, msg)
        update_case(case_id, status="complete")
        return

    # Ask Claude to compare and recommend
    report = _generate_report_with_claude(case_data, willing, declined, unreachable)

    # Send to user
    send_message(user_phone, report)
    update_case(case_id, status="complete")

    # Store the willing lawyers' contact info for quick follow-up
    _store_contact_lookup(case_id, willing)

    # Schedule a follow-up feedback request in 7 days
    _schedule_feedback_followup(user_phone, case_id)

    print(f"[recommendation] Report sent for case {case_id}")


def _generate_report_with_claude(
    case_data: dict,
    willing: list,
    declined: list,
    unreachable: list,
) -> str:
    practice = case_data.get("practice_area", "legal").replace("_", " ")
    summary = case_data.get("summary", "")

    lawyers_text = ""
    for i, l in enumerate(willing, 1):
        # Pull internal review score for this lawyer
        internal = get_lawyer_score(l.get("google_place_id", ""))
        internal_str = "No internal reviews yet"
        if internal["review_count"] > 0:
            internal_str = (
                f"{internal['avg_rating']}/5 from {internal['review_count']} past user"
                f"{'s' if internal['review_count'] != 1 else ''} on this platform"
            )
            if internal["positive_outcomes"] > 0:
                internal_str += f" — {internal['positive_outcomes']} won/settled"
            if internal["recent_comments"]:
                top_comment = internal["recent_comments"][0]
                if top_comment.get("comment"):
                    internal_str += f'. Recent review: "{top_comment["comment"]}"'

        lawyers_text += f"""
Lawyer {i}: {l['name']} ({l['firm']})
- Will take case: {l.get('will_take_case', 'unknown')}
- Fee: {l.get('fee_structure', 'unknown')} — {l.get('fee_range', 'not specified')}
- Assessment: {l.get('case_assessment', 'none given')}
- Next step: {l.get('next_steps', 'none given')}
- Contact: {l.get('contact_preference', '')} — {l.get('contact_detail', l.get('phone', ''))}
- Google rating: {l.get('rating', 'N/A')}
- Internal review score: {internal_str}
"""

    prompt = f"""A user has a {practice} case: {summary}

I called {len(willing) + len(declined) + len(unreachable)} lawyers.
{len(willing)} are willing to help, {len(declined)} declined, {len(unreachable)} didn't answer.

Here are the willing lawyers:
{lawyers_text}

IMPORTANT: Each lawyer has an "Internal review score" — this is real feedback from past users of this platform.
If a lawyer has internal reviews, weight them heavily in your recommendation. A lawyer with even 2-3 good internal reviews beats a stranger with only a Google rating.

Write a short, clear WhatsApp report for the user following this exact format:

---
*Your Legal Agent Report* 📋
Case: [practice area] — [1 sentence]

*Lawyers Who Can Help:*

1️⃣ [Name]
• Fee: [info]
• Their take: "[brief quote/paraphrase]"
• Next step: [their recommendation]
• ⭐ [internal review score if exists, e.g. "4.8/5 from 3 past users on this platform"]

[repeat for each willing lawyer]

---
*My Recommendation: [Name]*
[2-3 sentences: why this one — lead with internal review data if available, then fee/assessment]

Reply 1, 2, or 3 and I'll send their direct contact info.
---

Keep it concise. Use WhatsApp formatting (*bold*, not markdown headers).
If only 1 lawyer, skip the numbering and just give the info + recommend them directly.
Only show the internal review line if there are actual reviews."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def _schedule_feedback_followup(user_phone: str, case_id: str):
    """
    Schedule a follow-up message 7 days from now.
    Uses a simple DB-backed scheduler. A background job checks this table.
    """
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_followups (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone  TEXT NOT NULL,
                case_id     TEXT NOT NULL,
                send_at     DATETIME NOT NULL,
                sent        INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            INSERT INTO scheduled_followups (user_phone, case_id, send_at)
            VALUES (?, ?, datetime('now', '+7 days'))
        """, (user_phone, case_id))
    print(f"[recommendation] Feedback follow-up scheduled for {user_phone} in 7 days")


def _store_contact_lookup(case_id: str, willing: list):
    """Store numbered lawyer choices so user can reply '1', '2', etc."""
    lookup = {str(i): l for i, l in enumerate(willing, 1)}
    with get_conn() as conn:
        conn.execute(
            "UPDATE cases SET case_json = json_patch(case_json, ?) WHERE id=?",
            (json.dumps({"contact_lookup": lookup}), case_id)
        )


if __name__ == "__main__":
    case_id = input("Case ID to generate recommendation for: ").strip()
    generate_recommendation(case_id)
