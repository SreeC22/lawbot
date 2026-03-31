# Directive: Feedback Collection

## Goal
After a user's case is resolved, collect a rating and outcome for the lawyer they worked with. Use this data to improve future recommendations — lawyers with strong internal reviews get surfaced first.

## Why this matters
Google ratings are generic. Our internal reviews are specific to legal outcomes — did the lawyer win the case? Were they worth the money? This is our proprietary signal and becomes more valuable with every case.

## Two collection flows

### Flow 1: Proactive follow-up (preferred)
7 days after a case is marked `complete`, the system automatically texts the user:
> "Hey! It's Lex. About a week ago I helped you find a lawyer... How did it go?"

This is handled by `followup_scheduler.py` — run as a cron job or background process.

### Flow 2: Reactive (unprompted)
User texts something like "the lawyer was great" or "update: we won the case."
The webhook server detects feedback-like language and routes to `feedback_handler.py`.

## Conversation flow

### Step 1: Which lawyer?
If multiple lawyers were recommended, ask which one they used.
If only one, skip straight to rating.

### Step 2: Rating (1–5)
"On a scale of 1–5, how would you rate them overall?"
- 1 = terrible, would not recommend
- 5 = excellent, would strongly recommend

### Step 3: Outcome
"How did the case turn out?"
Options: Won / Settled / Lost / Dropped / Still ongoing / Just consulted

### Step 4: Comment (optional)
"Anything you'd want other people to know about this lawyer?"
User can skip.

## Data stored (per review)
- `google_place_id` — links this review to the lawyer across all cases
- `rating` — 1 to 5
- `outcome` — categorical
- `comment` — free text
- `practice_area` — so we can show "4.8/5 for employment cases"
- `user_phone` — to prevent duplicate reviews from same user

## How reviews affect recommendations
In `recommendation_engine.py`, each lawyer's internal score is fetched and included in the prompt to Claude:
- Avg rating across all past users on this platform
- Number of reviews
- Positive outcome count (won + settled)
- Most recent comment

Claude is instructed to weight internal reviews heavily over Google ratings — a lawyer with 3 strong internal reviews beats one with 100 generic Google reviews.

## Tone guidelines
- Keep it short — 4 steps max
- Don't pressure for comments — always offer "skip"
- Frame it as helping others, not as a survey
- Thank them genuinely at the end

## Edge cases
- **User never worked with a lawyer**: They'll say "none" at step 1. End gracefully.
- **User gives feedback months later**: Still collect it, same flow.
- **User rates 1–2 stars**: Note it, but don't ask them to explain unless they offer. Log it and move on.
- **Duplicate review (same user, same lawyer)**: Log but flag as duplicate — exclude from averages.
- **Lawyer has no Google Place ID**: Store with empty place_id, match by name + city instead.

## Running the scheduler
```bash
# One-time run (use as cron):
python execution/followup_scheduler.py

# Continuous loop (every 15 minutes):
python execution/followup_scheduler.py --loop

# Cron job example (every hour):
0 * * * * cd /path/to/lawbot && python execution/followup_scheduler.py
```
