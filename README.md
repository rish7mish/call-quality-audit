# VANI Call Quality: Audit → Issue → Fix → Test
**Voice AI Hackathon 2.0, Problem 1: Quality Audit & Fix Loop**

Every voice-bot call is checked automatically against the auditors' own 17-point checklist. Failures are
grouped into root causes and ranked. For a top problem, the system writes a change to the bot's instructions
and tests it at the exact moments where the bot went wrong. Everything is shown in one guided dashboard for
business viewers.

How it works, why it was built this way, and honest results: **[skills.md](skills.md)**.
Every AI prompt we wrote: **[prompts/](prompts/README.md)**.

## Quick start (Windows)
| Double-click | What it does | AI cost |
|---|---|---|
| `RUN_DASHBOARD.bat` | Opens the dashboard at http://localhost:8501 (keep the black window open) | free |
| `RUN_FIX_DEMO.bat` | Writes a prompt fix for one problem (default P03) and tests it (same-moment test) | ~$0.50 |
| `RUN_TEST_FIX.bat` | Re-tests an existing fix with the same-moment test (no new fix written) | ~$0.30-0.50 |
| `RUN_GRADE_MORE.bat` | Grades N more sample calls | ~$0.04 per call |
| `RUN_RETUNE.bat` | Re-grades the already-graded calls after a rules change | ~$0.04 per call |
| `RUN_HOLDOUT.bat` | Final honest score on the holdout calls (run only after a rules change) | ~$2.40 |
| `RUN_ME_transcribe.bat` | Turns recordings into text with Sarvam (needs a Sarvam key) | Sarvam credits |

Every script asks for the API key at run time (it is never saved) and prints the tokens used plus a cost
estimate. The running total is kept in `usage_log.csv` and shown on dashboard page 9.

Other systems: `pip install -r requirements.txt`, then `streamlit run dashboard.py`.

**Try it without any data:** open the dashboard, go to page 9 ("Try it live"), and paste one of the made-up
calls from [`samples/sample_transcripts.txt`](samples/sample_transcripts.txt). A fresh copy of this repo has
no calls graded yet, so pages 1–8 stay empty until you run the steps on your own sample calls.

## Folder layout
| Path | What it is |
|---|---|
| `*.bat` | One-click run files (above) |
| `rubric.py` | **The audit rules**: 17 checks, Serious / Minor / OK definitions, where each rule came from, change log |
| `grade_calls.py` | The AI auditor: grades each call with quoted proof; overall = worst check |
| `evaluate.py` | Agreement with the human auditors |
| `root_causes.py` | Groups failures into root causes, ranks by impact (% of calls × severity) |
| `suggest_fix.py`, `prompt_tools.py` | Writes a concrete change to the bot's instructions |
| `moment_test.py` | **Did the fix work?** Cuts failed calls just before the wrong reply, asks the bot for its next line with current vs fixed instructions, and a judge checks for the same mistake |
| `test_fix.py` | Exploratory full-conversation replays (an AI plays the buyer) |
| `dashboard.py` | The 9-page guided dashboard |
| `llm.py`, `transcribe_sarvam.py` | Connectors (Claude / OpenAI / Gemini / Sarvam; Sarvam speech-to-text) |
| `export_prompts.py` | Writes every AI prompt into `prompts/` as readable files |
| `skills.md` | **The skill file**: what this does, how each step works and why, honest results, limits, lessons |
| `prompts/` | Every AI prompt we wrote, readable |
| `samples/` | Made-up demo calls to paste into the dashboard |
| `docs/` | Step-by-step guide for transcribing recordings with Sarvam |

These folders are created locally when you run the steps and are **not** part of the repo:
`inputs/` (bot prompt, checklist image, sample audit sheet), `transcripts/`, `graded/`, `problems/`, `results/`,
`fixes/`, `tests/`, plus `human_labels.csv` (auditor verdicts for the sample calls, tune / holdout split).

## Results on the sample calls (rules v4, frozen)
- 83 sample calls graded (31 tune + 52 holdout), about 8 seconds and $0.04 per call.
- **Holdout (calls never used to set up the rules): same verdict as the auditors on 50%;
  when the AI says "serious" it is right 69% of the time.** Tune calls: 65%.
- For context: on calls the auditors audited twice, the two audits agreed 75% of the time.
- About 1 in 10 auditor verdicts depends on data not in the call (lead dashboard, category mapping, seller list).

## Notes
- If Anthropic says your key "is not scoped to a workspace", put your workspace ID (starts with `wrkspc_`) in
  `anthropic_workspace_id.txt` (not committed) or set `ANTHROPIC_WORKSPACE_ID`.
- Never paste API keys into files or chat; the run files ask for them each time.

## Data rule
No call data is stored in this repo. Sample recordings, transcripts, the audit sheet, the bot prompt and all
run outputs stay on your machine; `.gitignore` excludes them.
