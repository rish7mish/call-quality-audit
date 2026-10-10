"""
STEP 6 - Did the fix work?  "Same moment, two answers" test.

For each sample call where the problem happened:
  1. cut the conversation just BEFORE the bot's wrong reply (found from the auditor-AI's quoted evidence)
  2. ask the bot for its next line - with TODAY's instructions and with the FIXED instructions, several tries each
  3. a judge answers one narrow question per reply: did the bot make THIS mistake again?
It also judges the bot's actual reply in the call, to confirm the moment really shows the mistake
(moments where it doesn't are reported but not counted).

Output: tests/<P03>/moment_results.json
Run:    python moment_test.py --only P03 --cases 4 --tries 3
"""
import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import ask_llm, parse_json, provider  # noqa: E402
from test_fix import BOT_WRAPPER, bot_prompt_excerpt, sim_ask  # noqa: E402

JUDGE_SYSTEM = """You check ONE reply of an AI voice bot (IndiaMART buyer calls, Hindi/English/Hinglish) for ONE specific mistake.
You get: the mistake to look for, the conversation so far, and the bot's next line.
Answer only about that mistake - ignore every other quality issue.
If the bot's line does not get far enough to show the behaviour either way, answer false.
Reply with ONLY JSON: {"mistake": true or false, "why": "<one short sentence>"}"""

TS = re.compile(r"\[(\d{1,2}):(\d{2})\]\s*(Bot|Buyer)?")


def to_sec(m, s):
    return int(m) * 60 + int(s)


def parse_lines(transcript):
    out = []
    for line in transcript.splitlines():
        m = re.match(r"\[(\d{1,2}):(\d{2})\]\s*(Bot|Buyer):\s*(.*)", line)
        if m:
            out.append({"t": to_sec(m.group(1), m.group(2)), "who": m.group(3), "text": m.group(4), "line": line})
    return out


def cut_point(lines, evidence):
    """Index of the bot line that showed the mistake, using timestamps quoted in the evidence."""
    stamps = [(to_sec(m.group(1), m.group(2)), m.group(3)) for m in TS.finditer(evidence or "")]
    if not stamps:
        return None
    bot_stamps = [t for t, who in stamps if who == "Bot"]
    target = max(bot_stamps) if bot_stamps else max(t for t, _ in stamps)
    for i, ln in enumerate(lines):
        if ln["who"] == "Bot" and ln["t"] >= target - 1 and i > 0:
            return i
    return None


def judge(mistake, prefix, reply):
    user = (f"MISTAKE TO LOOK FOR: {mistake}\n\nCONVERSATION SO FAR:\n{prefix}\n\nTHE BOT'S NEXT LINE:\nBot: {reply}")
    text, _ = ask_llm(JUDGE_SYSTEM, user, max_tokens=1500)
    try:
        r = parse_json(text)
        return bool(r.get("mistake")), str(r.get("why", ""))[:300]
    except Exception:
        return False, "judge reply could not be read"


def mock_reply(variant, i):
    return f"(mock {variant} reply {i})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated problem ids (default: all fixes)")
    ap.add_argument("--cases", type=int, default=4, help="failure moments per fix (from the sample calls)")
    ap.add_argument("--tries", type=int, default=3, help="replies per version per moment")
    args = ap.parse_args()
    if not provider():
        sys.exit('LLM_PROVIDER is not set. Example:  $env:LLM_PROVIDER = "anthropic"')
    mock = provider() == "mock"

    fix_files = sorted(glob.glob(os.path.join(HERE, "fixes", "P*", "fix.json")))
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        fix_files = [f for f in fix_files if os.path.basename(os.path.dirname(f)) in want]
    if not fix_files:
        sys.exit("No fixes found. Run suggest_fix.py first.")
    with open(os.path.join(HERE, "fixes", "prompt_original.txt"), encoding="utf-8") as f:
        original = f.read()

    for ff in fix_files:
        with open(ff, encoding="utf-8") as f:
            fix = json.load(f)
        pid = fix["problem_id"]
        with open(os.path.join(os.path.dirname(ff), "prompt_fixed.txt"), encoding="utf-8") as f:
            fixed = f.read()
        titles = fix.get("sections_shown") or []
        prompts = {"current": bot_prompt_excerpt(original, titles), "fixed": bot_prompt_excerpt(fixed, titles)}
        problem = fix["problem"]
        mistake_base = f"{problem['name']}: {problem['description']}"

        # one moment per call, from the problem's example failures
        seen, cases = set(), []
        for ex in problem.get("examples", []):
            if ex["key"] in seen:
                continue
            gp = os.path.join(HERE, "graded", f"{ex['key']}.json")
            if not os.path.exists(gp):
                continue
            with open(gp, encoding="utf-8") as f:
                transcript = json.load(f).get("transcript", "")
            lines = parse_lines(transcript)
            i = cut_point(lines, ex.get("evidence", ""))
            if i is None:
                continue
            seen.add(ex["key"])
            cases.append({"key": ex["key"], "check": ex["check"], "evidence": ex.get("evidence", ""),
                          "root_cause": ex.get("root_cause", ""),
                          "prefix": "\n".join(ln["line"] for ln in lines[max(0, i - 12):i]),
                          "real_reply": lines[i]["text"]})
            if len(cases) >= args.cases:
                break
        if not cases:
            print(f"{pid}: no usable failure moments found (evidence had no timestamps).")
            continue
        print(f"{pid} {fix['problem_name']}: {len(cases)} failure moments x 2 versions x {args.tries} tries ...")
        t0 = time.time()
        for c in cases:
            mistake = f"{mistake_base} Specifically in this call: {c['root_cause']}"
            c["real_mistake"], c["real_why"] = (True, "mock") if mock else judge(mistake, c["prefix"], c["real_reply"])
            c["replies"] = {}
            for variant, bp in prompts.items():
                out = []
                for k in range(args.tries):
                    if mock:
                        reply, made, why = mock_reply(variant, k), (variant == "current" and k < 2), "mock"
                    else:
                        reply, _ = sim_ask(BOT_WRAPPER + bp, "CONVERSATION SO FAR:\n" + c["prefix"] +
                                           "\n\nYour next line as the bot:", 1500)
                        reply = " ".join(reply.strip().splitlines()).replace("[END]", "").strip() or "(no reply)"
                        made, why = judge(mistake, c["prefix"], reply)
                    out.append({"reply": reply, "mistake": made, "why": why})
                c["replies"][variant] = out
            cur = sum(r["mistake"] for r in c["replies"]["current"])
            fx = sum(r["mistake"] for r in c["replies"]["fixed"])
            flag = "" if c["real_mistake"] else "  (actual reply not judged a mistake - not counted)"
            print(f"   {c['key']}: today's instructions {cur}/{args.tries} mistakes, fixed {fx}/{args.tries}{flag}")

        valid = [c for c in cases if c["real_mistake"]]
        tot = len(valid) * args.tries
        cur_m = sum(r["mistake"] for c in valid for r in c["replies"]["current"])
        fix_m = sum(r["mistake"] for c in valid for r in c["replies"]["fixed"])
        rec = {"problem_id": pid, "problem_name": fix["problem_name"], "method": "same moment, two answers",
               "moments": len(cases), "valid_moments": len(valid), "tries": args.tries, "total_tries": tot,
               "current_mistakes": cur_m, "fixed_mistakes": fix_m,
               "issue_found_at": fix.get("issue_found_at", ""), "fix_suggested_at": fix.get("fix_suggested_at", ""),
               "fix_tested_at": time.strftime("%Y-%m-%d %H:%M:%S"), "test_seconds": round(time.time() - t0, 1),
               "cases": cases}
        out_dir = os.path.join(HERE, "tests", pid)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "moment_results.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        print(f"\n   RESULT ({len(valid)} valid moments, {tot} tries per version): "
              f"today's instructions made the mistake {cur_m}/{tot} times, fixed instructions {fix_m}/{tot} times.")
        print(f"   Saved tests/{pid}/moment_results.json")


if __name__ == "__main__":
    main()
