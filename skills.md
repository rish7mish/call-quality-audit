---
name: vani-call-quality-audit
description: Audit IndiaMART VANI voice-bot calls against the auditors' 17-point checklist (Fatal / Non-Fatal / Pass with quoted evidence), group failures into ranked root causes, write a concrete fix to the bot's prompt and test it on the real moments where the bot went wrong. Use for voice-bot call QA, "why do our calls fail", or proving a prompt change before it ships.
---

# VANI Call Quality: Audit → Root cause → Fix → Test

**Voice AI Hackathon 2.0, PS01: Quality Audit & Fix Loop**

This skill turns a pile of voice-bot calls into four answers a business team needs:
1. **How are our calls doing?** Every call gets graded on 17 checks, and every bad grade comes with a quoted line from the call as proof.
2. **Which calls need a human?** A risk queue: wrong requirement captured, frustrated buyer, looping, unclear audio, buyer asking for a person.
3. **Why do calls fail?** Failures are grouped into root causes and ranked by impact.
4. **What do we change, and does it work?** A specific edit to the bot's instructions, tested on the moments in the sample calls where the bot went wrong.

Everything is shown in a 9-page guided dashboard written for non-technical viewers.

---

## When to use this skill
- You have voice-bot call recordings or transcripts and want them graded like human auditors would.
- You want to know which problems to fix first, with evidence.
- You changed the bot's prompt and want proof it helps before going live.

## What you need
| Input | Used for | In this project |
|---|---|---|
| Call recordings (or transcripts) | Everything | Sample calls shared with the problem statement |
| Speech-to-text with timestamps and speakers | Turning audio into a conversation | Sarvam `saaras:v4`, codemix, diarization |
| The auditors' rulebook | The 17 checks | Call Quality Matrix image |
| Past human audits (optional, strongly recommended) | Calibrating and honestly scoring the AI | Sample audit sheet |
| The bot's system prompt | Writing and testing fixes | VANI prompt (.docx, 159k characters) |
| An AI API key | Grading, grouping, fixing, judging | Anthropic: Claude Sonnet 5.5, plus Haiku 5.5 for role-play |

---

## The workflow

| # | Step | Script | Output | Cost |
|---|---|---|---|---|
| 1 | Turn recordings into text | `transcribe_sarvam.py` | `transcripts/json`, `transcripts/text` | Sarvam credits |
| 2 | Grade every call (17 checks + risk flags) | `grade_calls.py` | `graded/<call>.json`, `all_grades.csv` | ~$0.04 and ~8 s per call |
| 3 | Compare with human auditors | `evaluate.py` | `results/agreement_<split>.md` | free |
| 4 | Group failures into root causes, rank them | `root_causes.py` | `problems/problems.json` | ~$0.03 |
| 5 | Write a fix to the bot's prompt | `suggest_fix.py` | `fixes/<P>/fix.json`, `diff.txt` | ~$0.10 |
| 6 | Test the fix at the failure moments | `moment_test.py` | `tests/<P>/moment_results.json` | ~$0.30–0.50 |
| 7 | Show it all | `dashboard.py` (Streamlit) | 9-page dashboard | free |

On Windows, every step has a double-click `RUN_*.bat` file that asks for the API key (never stored) and prints tokens used and an estimated cost.

```bash
pip install -r requirements.txt
export LLM_PROVIDER=anthropic LLM_API_KEY=...        # or openai / gemini / sarvam / mock (free dry run)
python grade_calls.py --split tune --limit 10
python evaluate.py --split tune
python root_causes.py
python suggest_fix.py --top 1
python moment_test.py --only P03 --cases 4 --tries 3
streamlit run dashboard.py
```

All AI prompts are exported for review in [`prompts/`](prompts/README.md). Run `python export_prompts.py` to refresh them.

---

## How each step works, and why it was built that way

### Step 2: Grading (the AI auditor)
- **The rules are the auditors' own.** The 17 checks come from their matrix. Where the matrix was vague, we read the auditors' written notes to see where they draw the line. Every rule records where it came from (copied, confirmed on past data, clarified from notes, measured by code, set aside, or required by PS01). See `rubric.py` → `RULE_ORIGIN` and dashboard page 8.
- **The overall verdict is computed by code, not by the AI:** the call's verdict is its worst check. We confirmed this matches the auditors' overall verdict 97% of the time in the sample audit sheet.
- **Measure, don't ask:** dead air is measured from timestamps (a gap of more than 7 s after the buyer speaks, ignoring the first 10 s). The buyer's word count is passed in as a hard signal for "did the buyer ever really engage?".
- **No proof, no fault:** every Fatal or Non-Fatal must quote the transcript line with its timestamp.
- **Don't guess what isn't in the call:** checks that need dashboard data (seller transfer, parts of category mapping) are marked "not assessable" instead of guessed.
- **Calibrate to the humans:** auditors only write up clear, material problems (about 70% of calls pass). The prompt says so explicitly, and "when in doubt, Pass".
- **Built for real outputs:** compact JSON (Pass and NA as plain strings), 6,000 output-token budget, automatic retry with a shorter answer, and the raw reply saved if parsing fails.

### Step 3: Honest scoring against humans
- Calls are split **tune** / **holdout**. Rules were adjusted only on tune calls, frozen at v4, and then the holdout was graded **once**.
- We report agreement, how often a "Serious" flag is right (precision), and how many real Serious calls it catches (recall).
- **Baseline:** on 12 calls the auditors audited twice, the two audits agreed only 75% of the time. A perfect score is not possible, because humans disagree too.

### Step 4: Root causes and priority
- Each failure carries a cause type (speech recognition, prompt/flow, knowledge, data…) and a one-line reusable root-cause sentence. The AI groups the sentences into 5–15 named problems.
- **Priority = % of calls with the problem × severity** (Fatal = 3, Non-Fatal = 1). This is transparent and explainable on one slide. If the AI is unavailable, the simple fallback groups by check and cause type.

### Step 5: Writing the fix
- The 159k-character bot prompt is split into 57 sections, and only the relevant ones are shown. The AI must propose the **smallest** change (add / replace / remove) using exact text, so the edit can be applied by code and shown as a before/after diff.
- Only problems a prompt can fix are attempted. Silence, voice and category data are not prompt problems.

### Step 6: Proving the fix: "same moment, two answers"
1. Take sample calls where the problem happened, and cut each one just before the bot's wrong reply. The quoted evidence timestamps locate it.
2. Ask the bot for its next line 3 times with today's instructions and 3 times with the fixed instructions.
3. A judge answers one narrow question per reply: *did the bot make this exact mistake again?*
4. **Validity check:** the judge also checks the bot's *actual* reply in the sample call. A moment counts only if that reply really was a mistake.

**Why not full role-play replays?** We tried them first (`test_fix.py`, where an AI plays the buyer). Results swung from 33% to 100% between runs on the same prompt, so they cannot prove anything. Cutting at the real moment removes that noise.

---

## Results (honest)

| Rules version | What changed | Agreement with auditors |
|---|---|---|
| v1 | Matrix + overall rule + auditor notes | 36% (first 11 tune calls) |
| v2 | "Only clear, material problems"; dead air only after the buyer speaks | 45% |
| v3 | Seller requests are normal; tighter spec rules | 48% (Serious recall fell to 36%) |
| **v4 (frozen)** | Outcome = Fatal when buyer never confirmed and gave no detail; looping tightened | **65% tune** |

**Holdout (52 calls never used for tuning):** same verdict as the auditors on **50%**; when the AI says "Serious" it is right **69%** of the time; it catches **50%** of the auditors' Serious calls. Cohen's kappa is 0.25 (fair agreement). For context, the auditor-vs-auditor agreement is 75%. About 1 in 10 auditor verdicts depends on data that is not in the call.

**Fix test (P03 "Quantity not captured or defaulted wrongly"):**
- In the sample calls, the bot made the mistake at **4 of 4** moments (judge-confirmed).
- Claude, given today's instructions at those same moments, made it **0 of 12** times. With the fixed instructions it also made it 0 of 12.
- **Finding: the rule already exists, but the live bot doesn't follow it.** Today's prompt already tells the bot not to assume a quantity the buyer never gave.
- The problem is not missing instructions. The likely causes are a very long prompt (159k characters), the production model, or speech-recognition errors. This is a more useful finding than "we added a rule", and it changes what should be fixed.
- **Next step:** run the same moment test against the live bot's own model with the full prompt.

**Speed and cost:** about 8 seconds and $0.04 per call to grade. Issue found → fix written → fix tested takes minutes of compute. The whole project used about $8 of AI credit.

---

## Guardrails
- **Data stays local.** Sample recordings, transcripts, the audit sheet, grades and the bot prompt are excluded by `.gitignore`. The repo holds code, rules, our prompts and made-up demo calls (`samples/`).
- **API keys are typed in at run time**, never saved to files. Every run logs tokens and estimated cost to `usage_log.csv`.
- **Don't over-claim.** If today's and the fixed instructions both score 0 mistakes, the dashboard says "rule exists, not followed", not "fix worked".
- **Rules are versioned** (`RULES_VERSION`, `RULES_CHANGELOG`). After any rule change, re-grade tune calls first; touch the holdout only once.

## Limitations
- 83 sample calls were graded (31 tune + 52 holdout). The samples are small, so the percentages are directional.
- Text only: the AI never hears the audio, so pronunciation and tone are judged from the transcript. Speech-recognition errors in the transcript can look like bot errors.
- The fix test uses Claude as a stand-in for the production bot, so it shows whether the *instructions* are sufficient, not how the live model behaves.
- Some checks need IndiaMART dashboard data (category mapping, seller list) and are marked not assessable.

---

## Lessons learned (so you can reuse this)
1. **Start from the humans' rulebook and their notes**, not from what "good" sounds like. Our first rules flagged far more than auditors do (36% agreement).
2. **Keep a holdout and touch it once.** Tune agreement (65%) overstated real performance (50%).
3. **Know the human ceiling.** At 75%, auditor-vs-auditor agreement is the realistic target.
4. **Let code do what code can:** overall verdict, silences, word counts, priority score.
5. **Test fixes at the exact failure moment**, not with free-form role-play.
6. **A null result is a result.** "The instruction exists but isn't followed" points to model, prompt length or speech recognition, not to more prompt text.

## Files
| Path | What it is |
|---|---|
| `rubric.py` | The 17 rules, their origins, change log, and the grader prompt builder |
| `grade_calls.py`, `evaluate.py` | Grading and agreement with humans |
| `root_causes.py` | Root-cause grouping and priority |
| `suggest_fix.py`, `prompt_tools.py` | Fix writing, prompt section split, edit, diff |
| `moment_test.py`, `test_fix.py` | Fix testing (main and exploratory) |
| `dashboard.py` | 9-page guided dashboard |
| `llm.py` | One function for Anthropic / OpenAI / Gemini / Sarvam / mock, with cost tracking |
| `transcribe_sarvam.py` | Batch speech-to-text |
| `prompts/` | Every AI prompt, readable (`export_prompts.py` regenerates) |
| `samples/` | Made-up demo calls to paste into dashboard page 9 |
| `RUN_*.bat` | One-click runs for non-technical teammates |

## Tools used
Sarvam speech-to-text (`saaras:v4`), Claude Sonnet 5.5 (grading, grouping, fixing, judging), Claude Haiku 5.5 (role-play), Python, pandas, Streamlit, Altair, python-docx. The code was built with Claude as a pair-programming assistant.
