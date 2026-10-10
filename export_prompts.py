"""
Writes every AI prompt this project uses into the prompts/ folder as readable Markdown files.
The prompts live in the code (that is what actually runs); this script makes a copy people can read and review.
Re-run it after changing any prompt or rule.  No AI calls, no cost.

Run:  python export_prompts.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("LLM_PROVIDER", "mock")  # importing the modules must never call an AI

from grade_calls import DEAD_AIR_SEC, PROMPT_VERSION  # noqa: E402
from moment_test import JUDGE_SYSTEM  # noqa: E402
from root_causes import CLUSTER_SYSTEM  # noqa: E402
from rubric import CHECKS, RULES_VERSION, build_system_prompt  # noqa: E402
from suggest_fix import FIX_SYSTEM  # noqa: E402
from test_fix import BOT_WRAPPER, BUYER_SYSTEM  # noqa: E402

OUT = os.path.join(HERE, "prompts")
STAMP = time.strftime("%Y-%m-%d")

def block(text):
    return "````text\n" + text.strip() + "\n````\n"


GRADER_INPUT = f"""CALL <call id>  (duration mm:ss). BUYER WORD COUNT: <n> words in <n> turns. Speaker labels Bot/Buyer were
assigned automatically; if they are clearly swapped, judge using the real roles.

MEASURED SILENCES over {DEAD_AIR_SEC:.0f}s after a buyer turn: [{{"after": "00:42", "seconds": 9.1}}, ...]   (or "none")

TRANSCRIPT:
[00:00] Bot: ...
[00:04] Buyer: ...
"""

FILES = [
    ("01_auditor_grader.md", "The AI auditor (grades every call)",
     "`rubric.py` -> `build_system_prompt()`; called from `grade_calls.py` -> `grade_turns()`",
     "Claude Sonnet 5.5 (`claude-sonnet-5-5`), max 6,000 output tokens, one call per conversation",
     "Transcript with timestamps + silences measured by code + buyer word count (see 'What the AI receives with each call' below)",
     "JSON: grade per check (Pass / Non-Fatal / Fatal / NA) with quoted evidence, reason, cause type, root-cause sentence, "
     "risk flags. The overall verdict is NOT asked from the AI: code takes the worst check.",
     build_system_prompt(), GRADER_INPUT),
    ("02_root_cause_grouping.md", "Root-cause grouping (turns individual failures into named problems)",
     "`root_causes.py` -> `CLUSTER_SYSTEM`",
     "Claude Sonnet 5.5, one call for all failures",
     "Numbered list of every Fatal / Non-Fatal check: check name, cause type, one-line root cause",
     "JSON groups. Ranking is done by code, not the AI: priority = % of calls with the problem x severity (Fatal 3, Non-Fatal 1)",
     CLUSTER_SYSTEM, None),
    ("03_fix_writer.md", "Fix writer (proposes a change to the bot's instructions)",
     "`suggest_fix.py` -> `FIX_SYSTEM`",
     "Claude Sonnet 5.5, one call per problem",
     "One problem with example failures + 2 example transcripts + outline of the bot prompt + its most relevant sections",
     "JSON: diagnosis, exact add / replace / remove edits, expected effect, risks, checks to test. Code applies the "
     "edits to a copy of the bot prompt and saves a diff.",
     FIX_SYSTEM, None),
    ("04_fix_test_bot_and_judge.md", "Fix test: 'same moment, two answers' (bot stand-in + judge)",
     "`test_fix.py` -> `BOT_WRAPPER` (bot stand-in) and `moment_test.py` -> `JUDGE_SYSTEM` (judge)",
     "Bot stand-in: Claude Haiku 5.5 (falls back to Sonnet). Judge: Claude Sonnet 5.5",
     "Bot stand-in: the bot's prompt sections (current or fixed) + the original call cut just before the wrong reply. "
     "Judge: the mistake to look for + the conversation so far + one bot reply",
     "Bot stand-in: its next spoken line. Judge: JSON {mistake: true/false, why}",
     "### Bot stand-in (BOT_WRAPPER, followed by the bot's own prompt sections)\n\n" + block(BOT_WRAPPER) +
     "\n### Judge (JUDGE_SYSTEM)\n\n" + block(JUDGE_SYSTEM), None),
    ("05_roleplay_buyer.md", "Role-play buyer (exploratory full-call replays only)",
     "`test_fix.py` -> `BUYER_SYSTEM`",
     "Claude Haiku 5.5 (falls back to Sonnet)",
     "The original call transcript + the simulated conversation so far",
     "The buyer's next line, or [HANGUP]. Replays turned out too noisy to prove a fix, so the main test is 04.",
     BUYER_SYSTEM, None),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    index = ["# The AI prompts in this project\n",
             f"Exported from the code on {STAMP} by `export_prompts.py` (rules {RULES_VERSION}, grader prompt {PROMPT_VERSION}).",
             "The code is the source of truth; re-run `python export_prompts.py` after changing a prompt.\n",
             "| File | What it is | Where it lives in code |", "|---|---|---|"]
    for fname, title, where, model, inp, out, prompt, user_example in FILES:
        md = [f"# {title}\n", f"- **Code:** {where}", f"- **Model:** {model}", f"- **Input:** {inp}",
              f"- **Output:** {out}", f"- **Exported:** {STAMP}\n", "## The prompt (system instructions)\n"]
        md.append(prompt.strip() + "\n" if prompt.lstrip().startswith("###") else block(prompt))
        if user_example:
            md += ["## What the AI receives with each call\n", block(user_example)]
        if fname.startswith("01"):
            md += ["## The 17 checks at a glance\n", "| id | Check | Visible in the call? |", "|---|---|---|"]
            md += [f"| `{c['id']}` | {c['name']} | {'yes' if c['from_call'] else 'no - graded NA (needs dashboard data)'} |"
                   for c in CHECKS]
            md.append("\nWhere each rule came from and how it changed (v1 -> v4): `rubric.py` (`RULE_ORIGIN`, "
                      "`RULES_CHANGELOG`) and dashboard page 8.")
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        index.append(f"| [{fname}]({fname}) | {title} | {where} |")
    index += ["", "Not included: the VANI bot prompt itself (`inputs/bot_prompt.docx`) and its fixed copy "
              "(`fixes/*/prompt_fixed.txt`). They belong to the problem owner."]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    print(f"Wrote {len(FILES)} prompt files + README.md to {OUT}")


if __name__ == "__main__":
    main()
