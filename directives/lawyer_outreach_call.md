# Directive: Lawyer Outreach Call (AI Phone Call)

## Goal
Place an AI-powered outbound phone call to a lawyer's office. Introduce the case, confirm the lawyer handles this type of case, and collect structured information: availability, rate, assessment, and recommended next steps.

## Input
- Structured case summary (from intake_interview directive)
- Lawyer's name, phone number, firm name, practice areas

## Call Script Flow

### Step 1: Introduction (on answer)
"Hi, this is an AI assistant calling on behalf of [User first name], a potential client. I'm reaching out because [User first name] has a [practice area] matter and we're looking for representation. Is this [Lawyer name / firm name]?"

If wrong number or no answer → log and move on.

### Step 2: Availability check
"Do you have a moment to hear a brief case summary? It'll take about 2 minutes."

If no → "No problem. What's the best time to call back?" → log callback time → end call.
If yes → continue.

### Step 3: Case summary (read condensed version)
"Here's the situation: [2-3 sentence summary from case JSON]. The incident occurred around [date] in [city, state]. The client is seeking [desired outcome]."

### Step 4: Structured questions (ask one at a time, record answers)
1. "Does this sound like a case you'd be able to take on?"
2. "What's your typical fee structure for this type of case — hourly, contingency, or flat fee? And what's the approximate range?"
3. "Based on what I've described, what's your initial read on the strength of this case?"
4. "What would be the recommended next step if [User first name] decides to move forward with you?"
5. "What's the best way for the client to reach you — phone, email, or your website?"

### Step 5: Close
"Thank you so much for your time. [User first name] will be receiving a summary of all responses and will be in touch if they'd like to proceed. Have a great day."

## Output (lawyer response JSON)
```json
{
  "lawyer_id": "",
  "call_status": "answered | no_answer | wrong_number | callback_requested | declined",
  "will_take_case": true | false | "maybe",
  "fee_structure": "contingency | hourly | flat_fee | unknown",
  "fee_range": "$X - $Y or % contingency",
  "case_assessment": "their words on case strength",
  "next_steps": "what they recommend",
  "contact_preference": "phone | email | website",
  "contact_detail": "",
  "callback_time": "if requested",
  "notes": "anything else notable from the call",
  "call_duration_seconds": 0,
  "recording_url": ""
}
```

## Handling Common Scenarios
- **Receptionist answers**: Ask to speak with the lawyer or leave a message, explain it's about a new client matter
- **Voicemail**: Leave a brief message — name, that it's about a potential new [practice area] client, your callback number — then log as no_answer
- **Lawyer declines immediately**: Ask if they can refer to a colleague, log referral if given
- **Lawyer asks for more details**: Read the full key_facts from the case summary
- **Lawyer asks who we are**: "I'm an AI assistant helping [User first name] find the right legal representation."

## Timing
- Calls should be placed during business hours: Mon–Fri, 9am–5pm local time (based on lawyer's location)
- Space calls at least 2 minutes apart
- Maximum 3 call attempts per lawyer before marking as unreachable

## Quality Standards
- Never misrepresent the user's situation
- Never promise outcomes
- Keep calls under 5 minutes
- Be polite and professional at all times
- If lawyer seems hostile or hangs up, log and move on — never re-call same lawyer same day
