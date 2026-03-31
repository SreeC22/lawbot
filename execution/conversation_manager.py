"""
Conversation manager.
Handles multi-turn intake conversation with the user via Claude.
Detects when intake is complete and triggers case building.
"""

import os
import json
import uuid
from dotenv import load_dotenv
from openai import OpenAI
from db import get_conn, get_active_case, get_messages, add_message, update_case

load_dotenv()

MODEL = "gpt-4o"

def _get_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

SYSTEM_PROMPT = """You are a warm, professional AI legal intake agent named Lex.
You help people find the right lawyer by understanding their legal situation through conversation.

Your job in this phase is INTAKE ONLY — gather facts, never give legal advice.

Rules:
- Ask at most 1-2 questions per message (this is WhatsApp/SMS, keep it short)
- Be empathetic but efficient
- Use plain English, no jargon
- Once you have enough to build a case summary, output a JSON block

You need to collect:
1. What happened (the core situation)
2. Who is involved (parties)
3. What the harm is (financial, physical, emotional, job, housing, etc.)
4. What the user wants (sue, get money back, get advice, custody, etc.)
5. When it happened (date/timeframe)
6. Their city and state (for finding local lawyers)
7. Any prior actions taken (police report, HR complaint, prior lawyer, etc.)

When you have enough information (all 7 points covered), end your message with a JSON block like this:
<case_ready>
{
  "practice_area": "employment|personal_injury|family|landlord_tenant|contract|criminal|immigration|other",
  "summary": "2-3 sentence plain English summary",
  "incident_date": "YYYY-MM-DD or approximate month/year",
  "location": {"city": "", "state": "", "zip": ""},
  "parties": {"plaintiff": "", "defendant": ""},
  "harm": "",
  "desired_outcome": "",
  "urgency": "low|medium|high|emergency",
  "prior_actions": "",
  "key_facts": ["fact1", "fact2", "fact3"]
}
</case_ready>

Only output this block when you are confident you have all the information needed.
Keep all other messages conversational and short."""


def handle_incoming_message(user_phone: str, user_message: str) -> str:
    """
    Process an incoming message from the user.
    Returns the assistant's reply.
    """
    # Find or create a case for this user
    case = get_active_case(user_phone)

    if not case:
        case_id = str(uuid.uuid4())
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO cases (id, user_phone, status) VALUES (?,?,?)",
                (case_id, user_phone, "intake")
            )
        case = {"id": case_id, "user_phone": user_phone, "status": "intake"}

    case_id = case["id"]

    # Store the user's message
    add_message(case_id, "user", user_message)

    # Build message history for OpenAI (system message first)
    history = [{"role": "system", "content": SYSTEM_PROMPT}] + get_messages(case_id)

    response = _get_client().chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        messages=history
    )

    reply = response.choices[0].message.content

    # Store assistant reply
    add_message(case_id, "assistant", reply)

    # Check if intake is complete
    if "<case_ready>" in reply:
        _process_case_ready(case_id, reply)
        # Strip the JSON block from the user-facing reply
        clean_reply = reply.split("<case_ready>")[0].strip()
        return clean_reply

    return reply


def _process_case_ready(case_id: str, raw_reply: str):
    """Extract the case JSON and update case status to 'researching'."""
    try:
        json_str = raw_reply.split("<case_ready>")[1].split("</case_ready>")[0].strip()
        case_data = json.loads(json_str)
        update_case(case_id, status="researching", case_json=json.dumps(case_data))
        print(f"[case_manager] Case {case_id} intake complete. Status → researching")
        # Trigger lawyer search (import here to avoid circular deps)
        from lawyer_finder import find_lawyers_for_case
        find_lawyers_for_case(case_id)
    except Exception as e:
        print(f"[case_manager] Failed to parse case JSON: {e}")


if __name__ == "__main__":
    # Quick CLI test
    phone = input("Test phone number: ")
    while True:
        msg = input("You: ")
        reply = handle_incoming_message(phone, msg)
        print(f"Lex: {reply}\n")
