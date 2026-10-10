"""
STEP 2 - The AI checker.

Reads each transcript in transcripts/json/, measures silences in code, asks the AI to grade
every checklist item with evidence, then computes the overall grade with the human rule
(overall = worst single check).

Output:
    graded/<call>.json     full result for one call (grades, evidence, root causes, risk flags)
    graded/all_grades.csv  one row per call, for the dashboard and evaluate.py

Run (PowerShell, inside the project folder):
    $env:LLM_PROVIDER = "anthropic"     # or openai / gemini / sarvam / mock
    $env:LLM_API_KEY  = "your-key"
    python grade_calls.py --split tune --limit 5     # small test first
    python grade_calls.py --split tune               # the 71 tune calls
    python grade_calls.py --split all                # everything with a transcript
Re-running skips calls already graded (use --redo to grade again after changing the rubric).
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import ask_llm, parse_json, provider, model_name  # noqa: E402
from rubric import CHECKS, CHECK_IDS, GRADES, RISK_FLAGS, build_system_prompt, overall_grade  # noqa: E402

TX_JSON = os.path.join(HERE, "transcripts", "json")
OUT = os.path.join(HERE, "graded")
LABELS = os.path.join(HERE, "human_labels.csv")
PROMPT_VERSION = "v4"
DEAD_AIR_SEC = 7.0  # matrix says 5s; auditors did not flag ~6s gaps in practice (tuned on tune calls)


def mmss(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def load_turns(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = (data.get("diarized_transcript") or {}).get("entries") or []
    turns = [{"start": float(e.get("start_time_seconds") or 0), "end": float(e.get("end_time_seconds") or 0),
              "spk": f"S{e.get('speaker_id', '?')}", "text": (e.get("transcript") or "").strip()} for e in entries]
    if not turns and data.get("transcript"):
        turns = [{"start": 0.0, "end": 0.0, "spk": "S?", "text": data["transcript"]}]
    return turns


BOT_CUES = ["indiamart", "india mart", "इंडियामार्ट", "इंडिया मार्ट", "requirement", "रिक्वायरमेंट", "product चाहिए",
            "seller", "सेलर", "कितने", "कितनी", "prefer", "चाहिए होंगे", "चाहिए होगी", "बताइए", "dhanyawad", "धन्यवाद"]


def guess_bot(turns):
    """Pick the speaker who sounds like the bot: introduces IndiaMART, asks about requirement/qty/specs, asks questions."""
    score = {}
    for i, t in enumerate(turns):
        low = t["text"].lower()
        s = sum(3 if ("india" in c or "इंडिया" in c) else 1 for c in BOT_CUES if c in low)
        s += 0.3 * low.count("?") + (0.5 if i == 0 else 0)
        score[t["spk"]] = score.get(t["spk"], 0) + s
    if score:
        return max(score, key=score.get)
    return "S0"


def silences(turns, bot):
    """Gaps longer than DEAD_AIR_SEC between consecutive turns, with who spoke before/after."""
    out = []
    for a, b in zip(turns, turns[1:]):
        gap = b["start"] - a["end"]
        if gap > DEAD_AIR_SEC and a["spk"] != bot and a["end"] >= 10:  # bot's turn to speak, after call set-up
            out.append({"from": mmss(a["end"]), "to": mmss(b["start"]), "seconds": round(gap, 1),
                        "before": "Bot" if a["spk"] == bot else "Buyer",
                        "after": "Bot" if b["spk"] == bot else "Buyer"})
    return out


def render(turns, bot):  # noqa: D401
    return "\n".join(f"[{mmss(t['start'])}] {'Bot' if t['spk'] == bot else 'Buyer'}: {t['text']}" for t in turns)


def clean(result):
    """Make sure every check is present with a valid grade; force NA where we can't judge."""
    checks = result.get("checks") or {}
    fixed = {}
    for c in CHECKS:
        r = checks.get(c["id"]) or {}
        if isinstance(r, str):  # compact form: "looping": "Pass"
            r = {"grade": r}
        g = str(r.get("grade", "NA")).strip()
        g = {"pass": "Pass", "non-fatal": "Non-Fatal", "nonfatal": "Non-Fatal", "non fatal": "Non-Fatal",
             "fatal": "Fatal", "na": "NA", "n/a": "NA"}.get(g.lower(), g)
        if g not in GRADES or not c["from_call"]:
            g = "NA"
        fixed[c["id"]] = {"grade": g, "evidence": r.get("evidence", "") or "", "reason": r.get("reason", "") or "",
                          "cause_type": (r.get("cause_type", "") or "") if g in ("Fatal", "Non-Fatal") else "",
                          "root_cause": (r.get("root_cause", "") or "") if g in ("Fatal", "Non-Fatal") else ""}
    flags = result.get("risk_flags") or {}
    result["checks"] = fixed
    result["risk_flags"] = {k: bool(flags.get(k, False)) for k in RISK_FLAGS}
    return result


def parse_pasted(text):
    """Turn a pasted transcript into turns. Accepts lines like
    '[00:12] Bot: ...', '00:12 Buyer: ...', 'Bot: ...', 'S0: ...'. Lines without a speaker continue the previous turn."""
    import re
    turns = []
    pat = re.compile(r"^\s*\[?(?:(\d{1,2}):(\d{2}))?\]?\s*(bot|buyer|agent|customer|user|s\d)\s*[:\-]\s*(.*)$", re.I)
    for line in text.splitlines():
        if not line.strip():
            continue
        m = pat.match(line)
        if m:
            mm, ss, who, said = m.groups()
            t = int(mm) * 60 + int(ss) if mm else (turns[-1]["start"] + 3 if turns else 0)
            who = who.lower()
            spk = "BOT" if who in ("bot", "agent") else ("BUYER" if who in ("buyer", "customer", "user") else who.upper())
            turns.append({"start": float(t), "end": float(t), "spk": spk, "text": said.strip()})
        elif turns:
            turns[-1]["text"] += " " + line.strip()
        else:
            turns.append({"start": 0.0, "end": 0.0, "spk": "BUYER", "text": line.strip()})
    return turns


def grade_turns(key, turns, system_prompt, out_dir=None, has_audio=True):
    """Grade one conversation given as turns. has_audio=False (pasted text): silences can't be measured,
    so dead air and pronunciation are reported as NA."""
    bot = "BOT" if any(t["spk"] == "BOT" for t in turns) else guess_bot(turns)
    sil = silences(turns, bot) if has_audio else []
    duration = turns[-1]["end"] if turns else 0
    audio_note = (f"MEASURED SILENCES over {DEAD_AIR_SEC:.0f}s after a buyer turn: " + (json.dumps(sil, ensure_ascii=False) if sil else "none")
                  if has_audio else "NO AUDIO (pasted transcript): grade dead_air and pronunciation as NA.")
    buyer_words = sum(len(t["text"].split()) for t in turns if t["spk"] != bot)
    buyer_turns = sum(1 for t in turns if t["spk"] != bot)
    user = (f"CALL {key}  (duration {mmss(duration)}). BUYER WORD COUNT: {buyer_words} words in {buyer_turns} turns. "
            f"Speaker labels Bot/Buyer were assigned automatically; "
            f"if they are clearly swapped, judge using the real roles.\n\n" + audio_note +
            "\n\nTRANSCRIPT:\n" + render(turns, bot))
    t0 = time.time()
    text, llm_sec = ask_llm(system_prompt, user, max_tokens=6000)
    try:
        parsed = parse_json(text)
    except Exception:
        # usually the answer was cut off or had a stray quote - save it and retry once, asking for brevity
        raw_dir = os.path.join(out_dir or OUT, "_raw")
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, f"{key}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        text, more = ask_llm(system_prompt, user + "\n\nIMPORTANT: your previous answer was invalid or too long. "
                             "Return compact valid JSON only: Pass/NA checks as plain strings, evidence under 80 characters.",
                             max_tokens=8000)
        llm_sec += more
        parsed = parse_json(text)
    result = clean(parsed)
    if not has_audio:
        for cid in ("dead_air", "pronunciation"):
            result["checks"][cid].update({"grade": "NA", "evidence": "", "reason": "no audio", "cause_type": "", "root_cause": ""})
    grades = {k: v["grade"] for k, v in result["checks"].items()}
    result.update({"key": key, "overall": overall_grade(grades), "bot_speaker": bot, "duration_sec": round(duration, 1),
                   "silences": sil, "turns": len(turns), "llm_seconds": llm_sec,
                   "audit_seconds": round(time.time() - t0, 1), "provider": provider(), "model": model_name(),
                   "prompt_version": PROMPT_VERSION, "graded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "transcript": render(turns, bot)})
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"{key}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result


def grade_one(key, system_prompt):
    turns = load_turns(os.path.join(TX_JSON, f"{key}.json"))
    return grade_turns(key, turns, system_prompt, out_dir=OUT)


def write_csv():
    rows = []  # noqa
    for p in sorted(glob.glob(os.path.join(OUT, "*.json"))):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        row = {"key": r["key"], "overall": r["overall"], "summary": r.get("summary", ""),
               "duration_sec": r.get("duration_sec"), "audit_seconds": r.get("audit_seconds"),
               "model": r.get("model"), "prompt_version": r.get("prompt_version")}
        for cid in CHECK_IDS:
            c = r["checks"][cid]
            row[f"ai_{cid}"] = c["grade"]
            row[f"ev_{cid}"] = c["evidence"]
            row[f"cause_{cid}"] = c["cause_type"]
            row[f"rc_{cid}"] = c["root_cause"]
        for k, v in r["risk_flags"].items():
            row[f"risk_{k}"] = int(v)
        row["risk_reason"] = r.get("risk_reason", "")
        rows.append(row)
    if rows:
        with open(os.path.join(OUT, "all_grades.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="tune", choices=["tune", "holdout", "all"],
                    help="which calls: tune (to improve the rubric), holdout (final score - run once at the end), all")
    ap.add_argument("--limit", type=int, default=0, help="only grade this many (for a test)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true", help="grade again even if already graded")
    ap.add_argument("--regrade", action="store_true",
                    help="re-grade ONLY the calls already graded in this split (e.g. after changing the rules)")
    ap.add_argument("--set", default="audited", choices=["audited", "provided"],
                    help="audited = the human-audited calls (transcripts/ -> graded/); provided = the unaudited sample calls "
                         "(transcripts_provided/ -> graded_provided/, no human labels, --split is ignored)")
    ap.add_argument("--keys", default="", help="comma-separated call keys to grade (overrides --split)")
    args = ap.parse_args()

    global TX_JSON, OUT
    if args.set == "provided":
        TX_JSON = os.path.join(HERE, "transcripts_provided", "json")
        OUT = os.path.join(HERE, "graded_provided")
        args.split = "all"
    if not provider():
        sys.exit('LLM_PROVIDER is not set. Example:  $env:LLM_PROVIDER = "anthropic"')
    os.makedirs(OUT, exist_ok=True)
    have = {os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(TX_JSON, "*.json"))}
    if args.keys:
        keys = [k.strip() for k in args.keys.split(",") if k.strip() in have]
    else:
        with open(LABELS, encoding="utf-8") as f:
            split_of = {r["key"]: r["split"] for r in csv.DictReader(f)}
        keys = sorted(k for k in have if args.split == "all" or split_of.get(k) == args.split)
    if args.regrade:
        keys = [k for k in keys if os.path.exists(os.path.join(OUT, f"{k}.json"))]
    elif not args.redo:
        keys = [k for k in keys if not os.path.exists(os.path.join(OUT, f"{k}.json"))]
    if args.limit:
        keys = keys[: args.limit]
    print(f"Grading {len(keys)} calls with {provider()} / {model_name()} ...")
    if not keys:
        print("Nothing to do (already graded? use --redo).")
        write_csv()
        return

    system_prompt = build_system_prompt()
    t0, done, failed = time.time(), 0, []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(grade_one, k, system_prompt): k for k in keys}
        for fut in as_completed(futs):
            k = futs[fut]
            try:
                r = fut.result()
                done += 1
                print(f"  [{done + len(failed)}/{len(keys)}] {k}: {r['overall']}  ({r['audit_seconds']}s)")
            except Exception as e:
                failed.append(k)
                print(f"  [{done + len(failed)}/{len(keys)}] {k}: FAILED - {str(e)[:200]}")
    n = write_csv()
    print(f"\nDone in {int(time.time() - t0)}s: {done} graded, {len(failed)} failed. "
          f"{os.path.basename(OUT)}/all_grades.csv now has {n} calls.")
    if failed:
        print("Re-run the same command to retry the failed ones.")


if __name__ == "__main__":
    main()
