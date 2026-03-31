"""
Webhook server (Flask).
Handles all inbound Twilio webhooks:
  - POST /sms          — inbound SMS
  - POST /whatsapp     — inbound WhatsApp
  - POST /call/start   — Twilio calls this when lawyer picks up
  - POST /call/gather  — Twilio calls this after each speech input
  - POST /call/status  — Twilio call status callbacks

Run with: python webhook_server.py
For production: gunicorn webhook_server:app
"""

import os
import sys
from pathlib import Path

# Ensure execution/ is on the path regardless of where the process starts
sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask, request, Response
from dotenv import load_dotenv
from twilio.request_validator import RequestValidator
from conversation_manager import handle_incoming_message
from call_handler import (
    handle_call_start,
    handle_call_gather,
    handle_call_status,
)
from feedback_handler import handle_feedback_message

load_dotenv()

app = Flask(__name__)
VALIDATE_TWILIO = os.environ.get("VALIDATE_TWILIO_SIGNATURE", "true").lower() == "true"


def _get_validator():
    """Lazy-load so missing env var doesn't crash startup."""
    return RequestValidator(os.environ.get("TWILIO_AUTH_TOKEN", ""))


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


def _validate_twilio(req):
    """Reject requests not from Twilio (in production)."""
    if not VALIDATE_TWILIO:
        return True
    signature = req.headers.get("X-Twilio-Signature", "")
    url = req.url
    params = req.form.to_dict()
    return _get_validator().validate(url, params, signature)


# ── SMS ───────────────────────────────────────────────────────────────────────

@app.route("/sms", methods=["POST"])
def sms_webhook():
    if not _validate_twilio(request):
        return Response("Forbidden", status=403)

    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()

    if not from_number or not body:
        return Response("", status=200)

    try:
        reply = _route_message(from_number, body)
    except Exception as e:
        import traceback
        print(f"[sms] ERROR: {e}\n{traceback.format_exc()}")
        reply = "Sorry, something went wrong on my end. I'm looking into it!"

    # Respond via TwiML
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{_escape_xml(reply)}</Message></Response>"""
    return Response(twiml, mimetype="text/xml")


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    if not _validate_twilio(request):
        return Response("Forbidden", status=403)

    from_number = request.form.get("From", "")  # format: whatsapp:+1XXXXXXXXXX
    body = request.form.get("Body", "").strip()

    if not from_number or not body:
        return Response("", status=200)

    # Normalize: strip "whatsapp:" prefix for internal use
    user_phone = from_number.replace("whatsapp:", "")

    try:
        reply = _route_message(user_phone, body)
    except Exception as e:
        import traceback
        print(f"[whatsapp] ERROR: {e}\n{traceback.format_exc()}")
        reply = "Sorry, something went wrong on my end. I'm looking into it!"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{_escape_xml(reply)}</Message></Response>"""
    return Response(twiml, mimetype="text/xml")


# ── Voice calls ───────────────────────────────────────────────────────────────

@app.route("/call/start", methods=["POST", "GET"])
def call_start():
    case_id   = request.args.get("case_id", "")
    lawyer_id = request.args.get("lawyer_id", "")
    twiml = handle_call_start(case_id, lawyer_id)
    return Response(twiml, mimetype="text/xml")


@app.route("/call/gather", methods=["POST"])
def call_gather():
    case_id      = request.args.get("case_id", "")
    lawyer_id    = request.args.get("lawyer_id", "")
    speech_result = request.form.get("SpeechResult", "")
    twiml = handle_call_gather(case_id, lawyer_id, speech_result)
    return Response(twiml, mimetype="text/xml")


@app.route("/call/status", methods=["POST"])
def call_status():
    call_sid    = request.form.get("CallSid", "")
    call_status = request.form.get("CallStatus", "")
    handle_call_status(call_sid, call_status)
    return Response("", status=200)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _route_message(user_phone: str, body: str) -> str:
    """
    Message routing priority:
    1. Lawyer contact lookup (user replied 1/2/3 after report)
    2. Feedback flow (user is mid-feedback, or message sounds like feedback)
    3. Intake / ongoing case conversation
    """
    # Priority 1: lawyer contact selection
    if body in ("1", "2", "3"):
        contact_reply = _handle_lawyer_selection(user_phone, body)
        # If it returned a real contact, send it. Otherwise fall through.
        if "contact info" in contact_reply or "No problem" in contact_reply or "Here's" in contact_reply:
            return contact_reply

    # Priority 2: feedback flow
    feedback_reply = handle_feedback_message(user_phone, body)
    if feedback_reply is not None:
        return feedback_reply

    # Priority 3: intake / ongoing conversation
    return handle_incoming_message(user_phone, body)


def _handle_lawyer_selection(user_phone: str, choice: str) -> str:
    """User replied with 1/2/3 to get a specific lawyer's contact info."""
    import json
    from db import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT case_json FROM cases WHERE user_phone=? AND status='complete' ORDER BY created_at DESC LIMIT 1",
            (user_phone,)
        ).fetchone()

    if not row:
        return "I don't have a recent completed case for you. Send me your situation and I'll get started!"

    try:
        case_data = json.loads(row["case_json"])
        lookup = case_data.get("contact_lookup", {})
        lawyer = lookup.get(choice)
        if not lawyer:
            return "I don't have that option. Please reply 1, 2, or 3."

        name = lawyer.get("name", "the lawyer")
        pref = lawyer.get("contact_preference", "phone")
        detail = lawyer.get("contact_detail") or lawyer.get("phone", "")
        return f"Here's {name}'s contact info:\n{pref.capitalize()}: {detail}\n\nGood luck — you've got this!"
    except Exception:
        return "Something went wrong retrieving that contact. Please try again."


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print(f"Starting Lawbot webhook server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
