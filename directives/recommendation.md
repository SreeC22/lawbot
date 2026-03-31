# Directive: Recommendation Report

## Goal
After collecting responses from all lawyer calls, generate a clear, simple comparison and a single confident recommendation for the user. Deliver via WhatsApp/SMS.

## Input
- Original case summary
- All lawyer response JSONs
- User's phone number

## Evaluation Criteria (weight each lawyer on these)
1. **Will take the case** — hard filter. If no, exclude.
2. **Fee structure fit** — contingency is best for users with no upfront budget; flat fee good for simple matters; hourly = most expensive
3. **Case assessment quality** — did they give a substantive view, or generic non-answer?
4. **Responsiveness** — answered the call, gave clear answers = good sign
5. **Experience signals** — did they mention relevant cases, specialization, track record?
6. **Next step clarity** — did they give a concrete path forward?

## Report Format (send via WhatsApp/SMS)

Keep it short enough for a phone screen. Use this structure:

---
**Your Legal Agent Report**
Case: [practice area] — [1 sentence summary]

**Lawyer Responses:**

1️⃣ [Name] — [Firm]
• Will take your case: Yes/No/Maybe
• Fee: [fee info]
• Their take: "[quote or paraphrase]"
• Next step: [their recommendation]

2️⃣ [Name] — [Firm]
[same format]

3️⃣ [Name] — [Firm]
[same format]

---
**My Recommendation: [Name]**
[2-3 sentences explaining why — fee, assessment quality, responsiveness]

Reply with the lawyer's number (1, 2, or 3) and I'll send you their direct contact info.

---

## Edge Cases
- **Only 1 lawyer responded**: Give the one result + note that more outreach can be done
- **No lawyers responded**: Notify user, offer to try different lawyers or wider radius
- **All declined**: Explain why (e.g., case type, jurisdiction) and suggest alternatives
- **Tie between lawyers**: Break tie on fee structure (lower cost wins), then responsiveness
- **User wants more info**: Offer to send full call notes for any lawyer

## Tone
- Direct and confident — don't hedge excessively
- Explain the "why" behind the recommendation in plain English
- Treat the user as intelligent — no condescension
- Remind them: this is information, not legal advice. They make the final call.
