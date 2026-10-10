"""
STEP 6 - Prove the fix works: replay failed calls against the CURRENT and the FIXED prompt.

For each fix in fixes/<P01>/fix.json:
  1. take up to --calls failed calls that have this problem
  2. a SIMULATED BUYER (AI) plays the real buyer from that call - same need, same answers, same quirks
  3. the BOT (AI) answers turn by turn, once with the current prompt and once with the fixed prompt
  4. both simulated conversations are graded by the SAME checker as the sample calls
  5. failure rate on the problem's checks: current prompt vs fixed prompt
It also records the time from "issue found" to "fix tested".

Output: tests/<P01>/results.json, tests/summary.csv
Run:    python test_fix.py                 (all fixes)
        python test_fix.py --only P01 --calls 5 --turns 8
Limits (say these to the jury): text-only simulation (no real audio/ASR), an AI plays the buyer,
small samples. It shows direction and size of the effect, not a production A/B test.
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from grade_calls import grade_turns  # noqa: E402
from llm import ask_llm, provider  # noqa: E402
from prompt_tools import split_sections  # noqa: E402
from rubric import build_system_prompt  # noqa: E402

# The buyer/bot role-play uses a cheaper model by default; GRADING the replays uses the same model as the sample calls.
SIM_MODEL = os.environ.get("LLM_SIM_MODEL", "claude-haiku-5-5" if os.environ.get("LLM_PROVIDER") == "anthropic" else "") or None


SIM_LOG = []


def sim_ask(system, user, max_tokens):
    """Role-play call on the cheap model. Falls back to the main model if that model is unavailable,
    or if it returns an empty reply (e.g. its token budget was used up before it answered)."""
    global SIM_MODEL
    import llm as _llm
    try:
        text, sec = ask_llm(system, user, max_tokens=max_tokens, model=SIM_MODEL)
    except RuntimeError as e:
        if SIM_MODEL and ("model" in str(e).lower() or "HTTP 404" in str(e) or "HTTP 400" in str(e)):
            print(f"   (simulation model {SIM_MODEL} not available - using the main model instead)")
            SIM_MODEL = None
            return ask_llm(system, user, max_tokens=max_tokens)
        raise
    if not text.strip():
        SIM_LOG.append({"model": SIM_MODEL, "empty_reply": True, **_llm.LAST_META})
        text, sec = ask_llm(system, user, max_tokens=max_tokens)  # retry once on the main model
        if not text.strip():
            SIM_LOG.append({"model": "main", "empty_reply": True, **_llm.LAST_META})
    return text, sec


BUYER_SYSTEM = """You are role-playing the BUYER in a phone call with IndiaMART's AI assistant. Below is the transcript of
the ORIGINAL call this buyer had. Behave like that buyer: same requirement, same answers (quantity, unit, specs), same language
mix (Hindi/English/Hinglish), same level of patience and the same quirks (e.g. answering in crates, giving a range,
mentioning a different product). If the real buyer's words look garbled by speech recognition, give similarly unclear
answers at the same moments. Do NOT help the bot more than the real buyer did.
Reply with ONLY the buyer's next utterance (one short line). If the real buyer would hang up now (irritated, done, or the
bot is closing the call), reply with exactly: [HANGUP]

ORIGINAL CALL TRANSCRIPT:
"""

BOT_WRAPPER = """You are the AI voice bot described by the PROMPT below, speaking on a phone call. Tools, variables and
function calls in the prompt are not available in this simulation: just say what you would say. Reply with ONLY your next
spoken line (one turn, short, natural spoken Hinglish as the prompt requires). When the prompt says to end the call,
say your closing line and append [END].

PROMPT:
"""


def bot_prompt_excerpt(prompt_text, titles, max_chars=22000):
    """The bot gets the sections that were relevant to the fix (+ the quality-fix section if one was added)."""
    secs = split_sections(prompt_text)
    want = set(titles) | {"Additional Rules (quality fixes)"}
    parts, total = [], 0
    for s in secs:
        if s["title"] in want:
            body = s["text"][: max(0, max_chars - total)]
            if not body:
                break
            parts.append(f"## {s['title']}\n{body}")
            total += len(body)
    return "\n\n".join(parts)


def first_bot_line(transcript):
    for line in transcript.splitlines():
        if "] Bot:" in line:
            return line.split("] Bot:", 1)[1].strip()
    return "Hello, main IndiaMART se bol rahi hoon. Aapko kis product ki requirement hai?"


def simulate(real_transcript, bot_prompt, max_turns, mock=False):
    opening = first_bot_line(real_transcript)
    turns = [{"start": 0.0, "end": 0.0, "spk": "BOT", "text": opening}]
    convo = f"Bot: {opening}"
    for i in range(max_turns):
        if mock:
            buyer = "[HANGUP]" if i == max_turns - 1 else f"(mock buyer reply {i})"
        else:
            buyer, _ = sim_ask(BUYER_SYSTEM + real_transcript[:6000],
                               "CONVERSATION SO FAR:\n" + convo + "\n\nYour next line as the buyer:", 1500)
            lines = [x for x in buyer.strip().splitlines() if x.strip()]
            buyer = lines[0].strip() if lines else "[HANGUP]"
        if "[HANGUP]" in buyer.upper():
            break
        turns.append({"start": float(len(turns) * 5), "end": float(len(turns) * 5), "spk": "BUYER", "text": buyer})
        convo += f"\nBuyer: {buyer}"
        if mock:
            bot = f"(mock bot reply {i})"
        else:
            bot, _ = sim_ask(BOT_WRAPPER + bot_prompt, "CONVERSATION SO FAR:\n" + convo + "\n\nYour next line as the bot:", 1500)
            bot = " ".join(bot.strip().splitlines()) or "..."
        ended = "[END]" in bot
        bot = bot.replace("[END]", "").strip()
        turns.append({"start": float(len(turns) * 5), "end": float(len(turns) * 5), "spk": "BOT", "text": bot})
        convo += f"\nBot: {bot}"
        if ended:
            break
    return turns


def failed(result, checks):
    return any(result["checks"][c]["grade"] in ("Fatal", "Non-Fatal") for c in checks if c in result["checks"])


def run_one(key, real_transcript, prompts, checks, max_turns, grader_prompt, mock):
    out = {"key": key}
    for variant, bp in prompts.items():
        turns = simulate(real_transcript, bp, max_turns, mock)
        g = grade_turns(f"{key}_{variant}", turns, grader_prompt, has_audio=False)
        out[variant] = {"failed": failed(g, checks), "overall": g["overall"],
                        "checks": {c: g["checks"][c] for c in checks if c in g["checks"]},
                        "transcript": g["transcript"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated problem ids")
    ap.add_argument("--calls", type=int, default=5, help="failed calls to replay per fix")
    ap.add_argument("--turns", type=int, default=8, help="max buyer turns per simulated call")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--set", default="audited", choices=["audited", "provided"])
    args = ap.parse_args()
    if not provider():
        sys.exit('LLM_PROVIDER is not set. Example:  $env:LLM_PROVIDER = "anthropic"')
    mock = provider() == "mock"
    graded_dir = os.path.join(HERE, "graded" if args.set == "audited" else "graded_provided")
    fix_files = sorted(glob.glob(os.path.join(HERE, "fixes", "P*", "fix.json")))
    if args.only:
        want = {x.strip() for x in args.only.split(",")}
        fix_files = [f for f in fix_files if os.path.basename(os.path.dirname(f)) in want]
    if not fix_files:
        sys.exit("No fixes found. Run suggest_fix.py first.")
    with open(os.path.join(HERE, "fixes", "prompt_original.txt"), encoding="utf-8") as f:
        original = f.read()
    grader_prompt = build_system_prompt()
    summary = []

    for ff in fix_files:
        with open(ff, encoding="utf-8") as f:
            fix = json.load(f)
        pid = fix["problem_id"]
        with open(os.path.join(os.path.dirname(ff), "prompt_fixed.txt"), encoding="utf-8") as f:
            fixed = f.read()
        titles = fix.get("sections_shown") or []
        prompts = {"current": bot_prompt_excerpt(original, titles), "fixed": bot_prompt_excerpt(fixed, titles)}
        untestable = {"dead_air", "pronunciation", "mcat", "astbuy"}  # silence/voice/category can't be seen in a text replay
        checks = [c for c in (fix.get("test_checks") or fix["problem"]["checks"]) if c not in untestable]
        if not checks:
            print(f"{pid}: skipped - its checks (silence/voice/category) can't be measured in a text replay.")
            continue
        keys = fix["problem"]["keys"][: args.calls]
        reals = {}
        for k in keys:
            p = os.path.join(graded_dir, f"{k}.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    reals[k] = json.load(f).get("transcript", "")
        print(f"{pid} {fix['problem_name']}: replaying {len(reals)} calls x 2 prompts (checks: {', '.join(checks)}) ...")
        t0 = time.time()
        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(run_one, k, t, prompts, checks, args.turns, grader_prompt, mock) for k, t in reals.items()]
            for fu in futs:
                try:
                    results.append(fu.result())
                except Exception as e:
                    print(f"   one replay failed: {str(e)[:150]}")
        if not results:
            continue
        before = sum(r["current"]["failed"] for r in results) / len(results)
        after = sum(r["fixed"]["failed"] for r in results) / len(results)
        tested_at = time.strftime("%Y-%m-%d %H:%M:%S")
        turns_info = {r["key"]: {v: r[v]["transcript"].count("\n") + 1 for v in ("current", "fixed")} for r in results}
        print(f"   conversation lengths (lines): {turns_info}")
        if SIM_LOG:
            print(f"   note: {len(SIM_LOG)} empty replies from the role-play model were retried")
        rec = {"problem_id": pid, "problem_name": fix["problem_name"], "checks": checks, "calls_replayed": len(results),
               "conversation_lines": turns_info, "sim_warnings": SIM_LOG[:20],
               "failure_rate_current": round(100 * before, 1), "failure_rate_fixed": round(100 * after, 1),
               "real_calls_failure_rate": 100.0,
               "issue_found_at": fix.get("issue_found_at", ""), "fix_suggested_at": fix.get("fix_suggested_at", ""),
               "fix_tested_at": tested_at, "test_seconds": round(time.time() - t0, 1),
               "method": "text simulation: AI buyer replays real failed calls; same checker grades both prompts",
               "results": results}
        out = os.path.join(HERE, "tests", pid)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        summary.append({k: v for k, v in rec.items() if k != "results"})
        print(f"   failure rate: current prompt {rec['failure_rate_current']}%  ->  fixed prompt {rec['failure_rate_fixed']}%"
              f"   ({rec['test_seconds']}s)")

    if summary:
        path = os.path.join(HERE, "tests", "summary.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
            w.writeheader()
            w.writerows([{**s, "checks": " ".join(s["checks"])} for s in summary])
        print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
