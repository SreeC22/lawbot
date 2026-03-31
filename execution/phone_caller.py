"""
Phone caller.
Places outbound AI phone calls to lawyers via Twilio Voice.
Uses a TwiML webhook (call_handler.py) to drive the conversation turn-by-turn.
"""

import os
import json
import time
from dotenv import load_dotenv
from twilio.rest import Client
from db import get_conn, get_lawyers_for_case, update_case

load_dotenv()

TWILIO_ACCOUNT_SID   = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN    = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE_NUMBER  = os.environ["TWILIO_PHONE_NUMBER"]   # your Twilio number
WEBHOOK_BASE_URL     = os.environ["WEBHOOK_BASE_URL"]       # e.g. https://yourapp.railway.app

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

SECONDS_BETWEEN_CALLS = 120   # 2 minutes between calls
MAX_ATTEMPTS_PER_LAWYER = 3


def call_lawyers_for_case(case_id: str):
    """Place calls to all pending lawyers for a case."""
    lawyers = get_lawyers_for_case(case_id)
    pending = [l for l in lawyers if l["call_status"] == "pending" and l["phone"]]

    if not pending:
        print(f"[phone_caller] No pending lawyers to call for case {case_id}")
        _check_and_finalize(case_id)
        return

    print(f"[phone_caller] Placing {len(pending)} calls for case {case_id}")

    for lawyer in pending:
        _call_lawyer(case_id, lawyer)
        time.sleep(SECONDS_BETWEEN_CALLS)

    print(f"[phone_caller] All calls placed for case {case_id}")


def _call_lawyer(case_id: str, lawyer: dict):
    """Initiate a single outbound call to a lawyer."""
    lawyer_id = lawyer["id"]
    phone = lawyer["phone"]

    # Normalize phone number format
    phone_e164 = _to_e164(phone)
    if not phone_e164:
        print(f"[phone_caller] Invalid phone for lawyer {lawyer_id}: {phone}")
        _set_lawyer_status(lawyer_id, "unreachable")
        return

    # The webhook URL carries context so the call handler knows what to say
    webhook_url = (
        f"{WEBHOOK_BASE_URL}/call/start"
        f"?case_id={case_id}&lawyer_id={lawyer_id}"
    )

    print(f"[phone_caller] Calling {lawyer['name']} at {phone_e164}")

    try:
        call = twilio_client.calls.create(
            to=phone_e164,
            from_=TWILIO_PHONE_NUMBER,
            url=webhook_url,
            status_callback=f"{WEBHOOK_BASE_URL}/call/status",
            status_callback_event=["completed", "no-answer", "failed", "busy"],
            timeout=30,           # ring for 30 seconds
            record=True,
        )
        _set_lawyer_status(lawyer_id, "calling", twilio_call_sid=call.sid)
        print(f"[phone_caller] Call SID {call.sid} for lawyer {lawyer['name']}")
    except Exception as e:
        print(f"[phone_caller] Failed to call lawyer {lawyer_id}: {e}")
        _set_lawyer_status(lawyer_id, "unreachable")


def _set_lawyer_status(lawyer_id: str, status: str, twilio_call_sid: str = None):
    with get_conn() as conn:
        if twilio_call_sid:
            conn.execute(
                "UPDATE lawyers SET call_status=? WHERE id=?",
                (status, lawyer_id)
            )
            # Store the SID in call_responses for later lookup
            conn.execute(
                """INSERT OR IGNORE INTO call_responses (lawyer_id, case_id, twilio_call_sid)
                   SELECT ?, case_id, ? FROM lawyers WHERE id=?""",
                (lawyer_id, twilio_call_sid, lawyer_id)
            )
        else:
            conn.execute(
                "UPDATE lawyers SET call_status=? WHERE id=?",
                (status, lawyer_id)
            )


def _to_e164(phone: str) -> str:
    """Convert a US phone number to E.164 format (+1XXXXXXXXXX)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return ""


def _check_and_finalize(case_id: str):
    """If all calls are done, trigger recommendation."""
    from recommendation_engine import generate_recommendation
    generate_recommendation(case_id)


if __name__ == "__main__":
    case_id = input("Case ID to call lawyers for: ").strip()
    call_lawyers_for_case(case_id)
