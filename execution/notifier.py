"""
Notifier.
Sends messages back to the user via WhatsApp or SMS using Twilio.
Automatically routes to WhatsApp if the number is registered, otherwise SMS.
"""

import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID  = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN   = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]   # SMS fallback
TWILIO_WHATSAPP_NUMBER = os.environ.get(
    "TWILIO_WHATSAPP_NUMBER",
    f"whatsapp:{TWILIO_PHONE_NUMBER}"
)

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_message(to_phone: str, body: str, prefer_whatsapp: bool = True):
    """
    Send a message to the user.
    Tries WhatsApp first if prefer_whatsapp=True, falls back to SMS on error.
    Long messages are automatically chunked to stay under 1600 chars (SMS) / 4096 chars (WhatsApp).
    """
    chunks = _chunk_message(body, max_len=4000 if prefer_whatsapp else 1500)

    for chunk in chunks:
        if prefer_whatsapp:
            try:
                _send_whatsapp(to_phone, chunk)
            except Exception as e:
                print(f"[notifier] WhatsApp failed, falling back to SMS: {e}")
                _send_sms(to_phone, chunk)
        else:
            _send_sms(to_phone, chunk)


def _send_whatsapp(to_phone: str, body: str):
    to = f"whatsapp:{_normalize(to_phone)}"
    msg = twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        body=body
    )
    print(f"[notifier] WhatsApp sent to {to_phone} | SID: {msg.sid}")


def _send_sms(to_phone: str, body: str):
    msg = twilio_client.messages.create(
        from_=TWILIO_PHONE_NUMBER,
        to=_normalize(to_phone),
        body=body
    )
    print(f"[notifier] SMS sent to {to_phone} | SID: {msg.sid}")


def _normalize(phone: str) -> str:
    """Ensure phone is in E.164 format."""
    if phone.startswith("whatsapp:"):
        phone = phone[9:]
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return phone  # return as-is if already formatted


def _chunk_message(text: str, max_len: int) -> list[str]:
    """Split a long message into chunks without cutting words."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


if __name__ == "__main__":
    phone = input("Phone number to test: ").strip()
    send_message(phone, "Hello from Lex, your AI legal agent! This is a test message.")
