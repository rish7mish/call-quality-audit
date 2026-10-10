"""
STEP 5 - Suggest a concrete prompt fix for each top problem.

For each top problem (from problems/problems.json) the AI gets:
  - the problem, its example failures with evidence, and 2 example transcripts
  - the outline of the bot prompt + the prompt sections most relevant to the problem
and must return specific edits (add / replace / remove exact text) - not generic advice.
The edits are applied to a copy of the prompt and a diff is saved.

Output per problem:  fixes/<P01>/fix.json, fixes/<P01>/diff.txt, fixes/<P01>/prompt_fixed.txt
Run:  python suggest_fix.py --top 3            (top 3 prompt-fixable problems)
      python suggest_fix.py --only P02,P05
Needs: pip install python-docx  (to read the .docx prompt)
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import ask_llm, parse_json, provider  # noqa: E402
from prompt_tools import apply_edits, load_prompt_text, make_diff, outline, relevant_sections, split_sections  # noqa: E402
from rubric import CHECKS  # noqa: E402

CHECK_IDS = [c["id"] for c in CHECKS]
UNTESTABLE = {"dead_air", "pronunciation", "mcat", "astbuy"}  # can't be measured in a text-only replay

FIX_SYSTEM = """You are a senior conversation designer fixing the system prompt of an AI voice bot (VANI) that calls buyers
for IndiaMART in Hindi/English/Hinglish. You are given ONE recurring quality problem found by auditing calls,
with evidence, plus the relevant parts of the bot's current prompt.

Propose the SMALLEST specific change to the prompt that would prevent this problem without breaking other behaviour.
Rules:
- Be concrete: write the exact instruction text the bot should follow, in the same style as the prompt (English, imperative).
- Prefer adding/editing a rule inside the most relevant existing section (use its exact title).
- For 'replace' or 'remove', old_text must be copied EXACTLY from the prompt excerpt (a full sentence or line).
- If the root cause is speech recognition, the prompt can still mitigate it (e.g. read back numbers/units and
  confirm; ask the buyer to repeat when the answer does not fit the question). Say so in diagnosis.
- If the problem cannot be fixed in the prompt at all (e.g. category mapping data), return no edits and explain.
Reply with ONLY JSON:
{"diagnosis": "<what in the current prompt causes or fails to prevent this, quote the rule if one exists>",
 "edits": [{"action": "add|replace|remove", "section": "<exact section title>", "old_text": "<exact text or empty>",
            "new_text": "<new instruction text>"}],
 "expected_effect": "<which failures this should remove, and how we will see it>",
 "risks": "<what could get worse>",
 "test_checks": ["<check ids to measure in the replay test, from: """ + ", ".join(CHECK_IDS) + """>"]}"""


def load_problems(set_name):
    p = os.path.join(HERE, "problems" if set_name == "audited" else "problems_provided", "problems.json")
    if not os.path.exists(p):
        sys.exit("problems.json not found. Run root_causes.py first.")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def example_transcripts(keys, graded_dir, n=2, max_chars=3500):
    out = []
    for k in keys[:n]:
        p = os.path.join(graded_dir, f"{k}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                t = json.load(f).get("transcript", "")
            out.append(f"--- Example call {k} ---\n{t[:max_chars]}")
    return "\n\n".join(out)


def mock_fix(problem, titles):
    sec = titles[1] if len(titles) > 1 else titles[0]
    return {"diagnosis": f"(mock) No explicit rule prevents: {problem['name']}",
            "edits": [{"action": "add", "section": sec, "old_text": "",
                       "new_text": f"- QUALITY RULE ({problem['id']}): (mock fix text for '{problem['name']}')."}],
            "expected_effect": "(mock)", "risks": "(mock)", "test_checks": problem["checks"][:2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="audited", choices=["audited", "provided"])
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated problem ids, e.g. P01,P03")
    ap.add_argument("--prompt", default=None, help="path to the bot prompt (.docx or .txt)")
    args = ap.parse_args()

    data = load_problems(args.set)
    problems = data["problems"]
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        chosen = [p for p in problems if p["id"] in want]
    else:
        # only problems a prompt change can fix AND a text replay can measure (no silence/voice/ASR-only problems)
        chosen = [p for p in problems
                  if p.get("fixable_by_prompt") and p["cause_type"] not in ("data_mapping", "asr_stt", "tts_voice")
                  and set(p["checks"]) - UNTESTABLE and not p["name"].startswith("Other")][: args.top]
        if not chosen:
            print("No prompt-fixable, text-testable problems found; falling back to the top problems.")
            chosen = [p for p in problems if set(p["checks"]) - UNTESTABLE][: args.top]
    graded_dir = os.path.join(HERE, "graded" if args.set == "audited" else "graded_provided")

    prompt_text = load_prompt_text(args.prompt)
    sections = split_sections(prompt_text)
    fixes_dir = os.path.join(HERE, "fixes")
    os.makedirs(fixes_dir, exist_ok=True)
    with open(os.path.join(fixes_dir, "prompt_original.txt"), "w", encoding="utf-8") as f:
        f.write(prompt_text)
    print(f"Prompt loaded: {len(prompt_text):,} chars, {len(sections)} sections. Fixing {len(chosen)} problems...")

    for p in chosen:
        t0 = time.time()
        query = " ".join([p["name"], p["description"]] + [e["root_cause"] + " " + e["evidence"] for e in p["examples"]])
        excerpt, titles = relevant_sections(sections, query, max_chars=45000)
        user = (f"PROBLEM {p['id']}: {p['name']}\n{p['description']}\n"
                f"Cause type: {p['cause_type']}. Affects {p['frequency_pct']}% of audited calls "
                f"({p['calls_affected']} calls, {p['fatal_calls']} fatal). Checks failing: {', '.join(p['checks'])}\n\n"
                "EXAMPLE FAILURES:\n" + "\n".join(
                    f"- {e['key']} | {e['check']} | {e['grade']} | {e['root_cause']} | evidence: {e['evidence']}"
                    for e in p["examples"]) +
                "\n\n" + example_transcripts(p["keys"], graded_dir) +
                "\n\nPROMPT OUTLINE (all sections):\n" + outline(sections) +
                "\n\nRELEVANT PROMPT SECTIONS (verbatim):\n" + excerpt)
        try:
            if provider() in ("", "mock"):
                fix = mock_fix(p, titles)
            else:
                text, _ = ask_llm(FIX_SYSTEM, user, max_tokens=3000)
                fix = parse_json(text)
        except Exception as e:
            print(f"  {p['id']}: FAILED - {str(e)[:200]}")
            continue
        fixed_text, report = apply_edits(prompt_text, fix.get("edits") or [])
        diff = make_diff(prompt_text, fixed_text)
        out = os.path.join(fixes_dir, p["id"])
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "prompt_fixed.txt"), "w", encoding="utf-8") as f:
            f.write(fixed_text)
        with open(os.path.join(out, "diff.txt"), "w", encoding="utf-8") as f:
            f.write(diff)
        fix.update({"problem_id": p["id"], "problem_name": p["name"], "problem": p,
                    "sections_shown": titles, "apply_report": report,
                    "test_checks": [c for c in (fix.get("test_checks") or p["checks"]) if c in CHECK_IDS and c not in UNTESTABLE]
                    or [c for c in p["checks"] if c not in UNTESTABLE],
                    "issue_found_at": p.get("first_seen") or data["meta"]["created_at"],
                    "fix_suggested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "suggest_seconds": round(time.time() - t0, 1)})
        with open(os.path.join(out, "fix.json"), "w", encoding="utf-8") as f:
            json.dump(fix, f, ensure_ascii=False, indent=2)
        applied = sum(1 for r in report if r["applied"])
        print(f"  {p['id']} {p['name']}: {applied}/{len(report)} edits applied  -> fixes/{p['id']}/diff.txt")
    print("\nNext: python test_fix.py   (replays the failed calls against the old and fixed prompt)")


if __name__ == "__main__":
    main()
