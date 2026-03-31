# Setup Guide

## Prerequisites
- Python 3.11+
- A Twilio account (for WhatsApp + SMS + voice calls)
- A Google Cloud account (for Places API)
- A public URL for webhooks (Railway, Render, or ngrok for local testing)

## Step 1: Install dependencies
```bash
cd execution
pip install -r ../requirements.txt
```

## Step 2: Fill in .env
```
ANTHROPIC_API_KEY       → get from console.anthropic.com
TWILIO_ACCOUNT_SID      → get from console.twilio.com
TWILIO_AUTH_TOKEN       → get from console.twilio.com
TWILIO_PHONE_NUMBER     → buy a number in Twilio console
TWILIO_WHATSAPP_NUMBER  → enable WhatsApp sandbox in Twilio console
GOOGLE_PLACES_API_KEY   → enable Places API in Google Cloud Console
WEBHOOK_BASE_URL        → your public server URL (see Step 4)
```

## Step 3: Initialize the database
```bash
cd execution
python db.py
# Creates .tmp/lawbot.db
```

## Step 4: Get a public URL
**Local dev (ngrok):**
```bash
ngrok http 5000
# Copy the https URL → paste into WEBHOOK_BASE_URL in .env
```

**Production (Railway):**
- Push repo to GitHub
- New project in Railway → Deploy from GitHub
- Set all env vars in Railway dashboard
- Railway gives you a public URL automatically

## Step 5: Configure Twilio webhooks
In Twilio console:

**For SMS:**
- Phone Numbers → your number → Messaging → "A message comes in"
- Set to: `https://YOUR_URL/sms` (HTTP POST)

**For WhatsApp:**
- Messaging → Try it out → Send a WhatsApp message
- Sandbox settings → "When a message comes in"
- Set to: `https://YOUR_URL/whatsapp` (HTTP POST)

## Step 6: Start the server
```bash
cd execution
python webhook_server.py
# or for production:
gunicorn webhook_server:app --bind 0.0.0.0:5000
```

## Step 7: Test it
1. Text your Twilio WhatsApp number: "I need a lawyer"
2. The agent will ask follow-up questions
3. Once intake is complete, it will search for lawyers and start calling them
4. You'll receive a report via WhatsApp with the comparison + recommendation

## How the flow works
```
User texts → webhook_server.py → conversation_manager.py (Claude intake)
  → case complete → lawyer_finder.py (Google Places)
  → phone_caller.py (Twilio outbound calls)
  → call_handler.py (AI conversation with lawyer)
  → recommendation_engine.py (Claude comparison)
  → notifier.py (WhatsApp/SMS report back to user)
```

## Testing without real calls
Set `VALIDATE_TWILIO_SIGNATURE=false` in .env and use curl to simulate:
```bash
curl -X POST http://localhost:5000/sms \
  -d "From=%2B15551234567&Body=I+was+wrongfully+fired+from+my+job"
```
