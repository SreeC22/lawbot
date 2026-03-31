"""
Call handler (TwiML webhook).
Drives the AI phone conversation with lawyers turn-by-turn.
Mounted on the Flask webhook server at /call/start and /call/gather.
Called by Twilio during the live phone call.
"""

import os
import json
from dotenv import load_dotenv
from twilio.twiml.voice_response import VoiceResponse, Gather
import anthropic
from db import get_conn

load_dotenv()

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-opus-4-6"

# Conversation state stored in-memory per call SID (short-lived, call duration only)
# For production, replace with Redis
_call_state: dict[str, dict] = {}

CALL_SYSTEM_PROMPT = """You are an AI assistant making a phone call on behalf of a potential legal client.
You are professional, warm, and concise. This is a real phone call so keep responses SHORT (1-3 sentences max).

Your goal is to:
1. Introduce yourself and the client's situation
2. Ask if the lawyer handles this type of case
3. Ask about fees
4. Ask for their initial assessment
5. Ask for recommended next steps
6. Thank them and end

After each lawyer response, decide: ask the next question OR wrap up if you have enough info.

When you have all the information you need, end your response with: <END_CALL>

When extracting the lawyer's answers into structured data, end with:
<RESPONSE_DATA>
{
  "will_take_case": "yes|no|maybe",
  "fee_structure": "contingency|hourly|flat_fee|unknown",
  "fee_range": "",
  "case_assessment": "",
  "next_steps": "",
  "contact_preference": "phone|email|website",
  "contact_detail": ""
}
</RESPONSE_DATA>"""


def handle_call_start(case_id: str, lawyer_id: str) -> str:
    """
    Called when Twilio connects the call.
    Returns TwiML for the opening statement + first gather.
    """
    # Load context
    case_data, lawyer = _load_context(case_id, lawyer_id)
    if not case_data or not lawyer:
        return _twiml_hangup("Sorry, I have a system error. Goodbye.")

    call_key = f"{case_id}:{lawyer_id}"
    _call_state[call_key] = {
        "case_id": case_id,
        "lawyer_id": lawyer_id,
        "case_data": case_data,
        "lawyer": lawyer,
        "history": [],
        "turn": 0,
    }

    opening = _generate_opening(case_data, lawyer)
    _call_state[call_key]["history"].append({"role": "assistant", "content": opening})

    return _twiml_gather(opening, case_id, lawyer_id)


def handle_call_gather(case_id: str, lawyer_id: str, speech_result: str) -> str:
    """
    Called after each speech input from the lawyer.
    Returns TwiML for the next AI turn.
    """
    call_key = f"{case_id}:{lawyer_id}"
    state = _call_state.get(call_key)

    if not state:
        return _twiml_hangup("I'm sorry, I lost our session. Thank you for your time. Goodbye.")

    if not speech_result:
        # No speech detected — prompt again
        return _twiml_gather("I'm sorry, I didn't catch that. Could you repeat?", case_id, lawyer_id)

    # Add lawyer's response to history
    state["history"].append({"role": "user", "content": speech_result})
    state["turn"] += 1

    # Generate AI response
    ai_response = _generate_response(state)
    state["history"].append({"role": "assistant", "content": ai_response})

    # Check for end-of-call signal
    if "<END_CALL>" in ai_response:
        clean_text = ai_response.replace("<END_CALL>", "").strip()
        # Extract and save structured data if present
        _save_response_data(case_id, lawyer_id, ai_response, state["history"])
        del _call_state[call_key]
        return _twiml_hangup(clean_text)

    # Safety: end call after 8 turns max
    if state["turn"] >= 8:
        _save_response_data(case_id, lawyer_id, ai_response, state["history"])
        del _call_state[call_key]
        return _twiml_hangup(
            "Thank you so much for your time. We'll be in touch if the client decides to move forward. Have a great day!"
        )

    return _twiml_gather(ai_response, case_id, lawyer_id)


def handle_call_no_answer(case_id: str, lawyer_id: str):
    """Mark lawyer as no_answer in DB."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE lawyers SET call_status='no_answer' WHERE id=?", (lawyer_id,)
        )
    # Check if all calls are done
    _maybe_finalize(case_id)


def handle_call_status(call_sid: str, call_status: str):
    """Handle Twilio status callback."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT lawyer_id, case_id FROM call_responses WHERE twilio_call_sid=?",
            (call_sid,)
        ).fetchone()

    if not row:
        return

    lawyer_id, case_id = row["lawyer_id"], row["case_id"]

    if call_status in ("no-answer", "failed", "busy"):
        handle_call_no_answer(case_id, lawyer_id)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_context(case_id: str, lawyer_id: str):
    with get_conn() as conn:
        case_row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        lawyer_row = conn.execute("SELECT * FROM lawyers WHERE id=?", (lawyer_id,)).fetchone()

    if not case_row or not lawyer_row:
        return None, None

    case_data = json.loads(case_row["case_json"]) if case_row["case_json"] else {}
    return case_data, dict(lawyer_row)


def _generate_opening(case_data: dict, lawyer: dict) -> str:
    practice = case_data.get("practice_area", "legal").replace("_", " ")
    summary = case_data.get("summary", "")
    # Infer user's first name from case data or fall back to "my client"
    client_name = "my client"

    return (
        f"Hi, this is an AI assistant calling on behalf of {client_name}. "
        f"I'm reaching out because {client_name} has a {practice} matter and is looking for representation. "
        f"Here's a brief summary: {summary} "
        f"Does this sound like something you'd be able to help with?"
    )


def _generate_response(state: dict) -> str:
    case_data = state["case_data"]
    history = state["history"]

    messages = history.copy()
    # Add context about what info we still need
    if state["turn"] == 1:
        messages.append({
            "role": "user",
            "content": f"[SYSTEM: Also need to collect fee structure, case assessment, and next steps. Case details: {json.dumps(case_data)}]"
        })

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=CALL_SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text


def _save_response_data(case_id: str, lawyer_id: str, raw_text: str, history: list):
    """Parse and save structured response data to DB."""
    data = {}
    if "<RESPONSE_DATA>" in raw_text:
        try:
            json_str = raw_text.split("<RESPONSE_DATA>")[1].split("</RESPONSE_DATA>")[0].strip()
            data = json.loads(json_str)
        except Exception as e:
            print(f"[call_handler] Failed to parse response data: {e}")

    transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)

    with get_conn() as conn:
        # Upsert into call_responses
        existing = conn.execute(
            "SELECT id FROM call_responses WHERE lawyer_id=? AND case_id=?",
            (lawyer_id, case_id)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE call_responses SET
                    will_take_case=?, fee_structure=?, fee_range=?,
                    case_assessment=?, next_steps=?, contact_preference=?,
                    contact_detail=?, full_transcript=?
                WHERE lawyer_id=? AND case_id=?
            """, (
                data.get("will_take_case"), data.get("fee_structure"), data.get("fee_range"),
                data.get("case_assessment"), data.get("next_steps"), data.get("contact_preference"),
                data.get("contact_detail"), transcript,
                lawyer_id, case_id
            ))
        else:
            conn.execute("""
                INSERT INTO call_responses
                    (lawyer_id, case_id, will_take_case, fee_structure, fee_range,
                     case_assessment, next_steps, contact_preference, contact_detail, full_transcript)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                lawyer_id, case_id,
                data.get("will_take_case"), data.get("fee_structure"), data.get("fee_range"),
                data.get("case_assessment"), data.get("next_steps"), data.get("contact_preference"),
                data.get("contact_detail"), transcript
            ))

        conn.execute("UPDATE lawyers SET call_status='answered' WHERE id=?", (lawyer_id,))

    _maybe_finalize(case_id)


def _maybe_finalize(case_id: str):
    """If all lawyers have been called, generate recommendation."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as n FROM lawyers WHERE case_id=?", (case_id,)
        ).fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) as n FROM lawyers WHERE case_id=? AND call_status IN ('pending','calling')",
            (case_id,)
        ).fetchone()["n"]

    if pending == 0 and total > 0:
        from recommendation_engine import generate_recommendation
        generate_recommendation(case_id)


def _twiml_gather(say_text: str, case_id: str, lawyer_id: str) -> str:
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"/call/gather?case_id={case_id}&lawyer_id={lawyer_id}",
        method="POST",
        speech_timeout="auto",
        language="en-US",
    )
    gather.say(say_text, voice="Polly.Joanna")
    response.append(gather)
    # If no input after gather, hang up politely
    response.say("I didn't hear a response. Thank you for your time. Goodbye.", voice="Polly.Joanna")
    response.hangup()
    return str(response)


def _twiml_hangup(say_text: str) -> str:
    response = VoiceResponse()
    response.say(say_text, voice="Polly.Joanna")
    response.hangup()
    return str(response)
