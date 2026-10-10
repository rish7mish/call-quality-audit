# The AI prompts in this project

Exported from the code on 2026-10-10 by `export_prompts.py` (rules v4 (2026-10-10), grader prompt v4).
The code is the source of truth; re-run `python export_prompts.py` after changing a prompt.

| File | What it is | Where it lives in code |
|---|---|---|
| [01_auditor_grader.md](01_auditor_grader.md) | The AI auditor (grades every call) | `rubric.py` -> `build_system_prompt()`; called from `grade_calls.py` -> `grade_turns()` |
| [02_root_cause_grouping.md](02_root_cause_grouping.md) | Root-cause grouping (turns individual failures into named problems) | `root_causes.py` -> `CLUSTER_SYSTEM` |
| [03_fix_writer.md](03_fix_writer.md) | Fix writer (proposes a change to the bot's instructions) | `suggest_fix.py` -> `FIX_SYSTEM` |
| [04_fix_test_bot_and_judge.md](04_fix_test_bot_and_judge.md) | Fix test: 'same moment, two answers' (bot stand-in + judge) | `test_fix.py` -> `BOT_WRAPPER` (bot stand-in) and `moment_test.py` -> `JUDGE_SYSTEM` (judge) |
| [05_roleplay_buyer.md](05_roleplay_buyer.md) | Role-play buyer (exploratory full-call replays only) | `test_fix.py` -> `BUYER_SYSTEM` |

Not included: the VANI bot prompt itself (`inputs/bot_prompt.docx`) and its fixed copy (`fixes/*/prompt_fixed.txt`). They belong to the problem owner.
