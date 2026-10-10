"""
STEP 4 - Group the failures into root causes and rank them.

Reads graded/*.json (or graded_provided/*.json with --set provided). Every Fatal/Non-Fatal check
is one "failure" carrying the AI's cause_type and one-line root_cause. The AI groups similar
root_cause sentences into a short list of named problems. If no AI is available (mock), failures
are grouped by check + cause type instead.

Ranking (transparent, explain this on the slide):
    frequency  = share of audited calls that have this problem
    severity   = average weight of its failures (Fatal = 3, Non-Fatal = 1)
    priority   = frequency (%) x severity         e.g. 12% of calls x 2.5 = 30

Output: problems/problems.json and problems/problems.csv
Run:    python root_causes.py            (audited calls)
        python root_causes.py --set provided
"""
import argparse
import csv
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from llm import ask_llm, parse_json, provider  # noqa: E402
from rubric import CAUSE_TYPES, CHECKS  # noqa: E402

CHECK_NAME = {c["id"]: c["name"] for c in CHECKS}
WEIGHT = {"Fatal": 3, "Non-Fatal": 1}

CLUSTER_SYSTEM = """You group call-quality failures of an AI voice bot into ROOT CAUSES.
You get a numbered list of failures. Each has: the checklist item that failed, a cause type, and a one-line root cause.
Group failures that share the same underlying reason (something one fix to the bot, its speech recognition, its knowledge
or its call flow would solve) into 5-15 groups. Failures of different checklist items CAN share a root cause
(e.g. 'bot does not read back numbers' can cause both quantity and spec errors).
Every failure number must appear in exactly one group. Use a final group 'Other / one-off' only for true leftovers.
Reply with ONLY JSON:
{"groups": [{"name": "<short problem name, max 8 words>",
             "description": "<one sentence: what goes wrong and why>",
             "cause_type": "<one of: """ + ", ".join(CAUSE_TYPES) + """>",
             "fixable_by_prompt": true/false,
             "members": [<failure numbers>]}]}"""


def load(graded_dir):
    calls, failures = [], []
    for p in sorted(glob.glob(os.path.join(graded_dir, "*.json"))):
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        calls.append(r)
        for cid, c in r["checks"].items():
            if c["grade"] in WEIGHT:
                failures.append({"key": r["key"], "check": cid, "grade": c["grade"],
                                 "cause_type": c.get("cause_type") or "", "root_cause": c.get("root_cause") or c.get("reason", ""),
                                 "evidence": c.get("evidence", ""), "graded_at": r.get("graded_at", "")})
    return calls, failures


def cluster_with_ai(failures):
    lines = [f"{i}. [{CHECK_NAME.get(f['check'], f['check'])} | {f['grade']} | {f['cause_type']}] {f['root_cause']}"
             for i, f in enumerate(failures)]
    text, _ = ask_llm(CLUSTER_SYSTEM, "FAILURES:\n" + "\n".join(lines), max_tokens=6000)
    groups = parse_json(text)["groups"]
    seen = set()
    for g in groups:
        g["members"] = [int(m) for m in g.get("members", []) if str(m).isdigit() and int(m) < len(failures) and int(m) not in seen]
        seen.update(g["members"])
    left = [i for i in range(len(failures)) if i not in seen]
    if left:
        groups.append({"name": "Other / one-off", "description": "Failures the grouping did not place.",
                       "cause_type": "", "fixable_by_prompt": False, "members": left})
    return [g for g in groups if g["members"]]


def cluster_simple(failures):
    groups = {}
    for i, f in enumerate(failures):
        k = (f["check"], f["cause_type"] or "unknown")
        groups.setdefault(k, []).append(i)
    plain = {"prompt": "bot instructions", "asr_stt": "speech recognition", "knowledge": "product knowledge",
             "flow_logic": "call flow", "tts_voice": "bot voice", "data_mapping": "category data", "unknown": "other"}
    return [{"name": f"{CHECK_NAME.get(c, c)} – {plain.get(t, t)}",
             "description": f"Calls failing '{CHECK_NAME.get(c, c)}', most likely caused by {plain.get(t, t)}.",
             "cause_type": t, "fixable_by_prompt": t in ("prompt", "flow_logic", "knowledge"), "members": m}
            for (c, t), m in groups.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="audited", choices=["audited", "provided"])
    ap.add_argument("--simple", action="store_true", help="group by check + cause type without the AI")
    args = ap.parse_args()
    graded_dir = os.path.join(HERE, "graded" if args.set == "audited" else "graded_provided")
    out_dir = os.path.join(HERE, "problems" if args.set == "audited" else "problems_provided")
    calls, failures = load(graded_dir)
    if not calls:
        sys.exit(f"No graded calls in {graded_dir}. Run grade_calls.py first.")
    print(f"{len(calls)} graded calls, {len(failures)} failed checks. Grouping...")

    if args.simple or provider() in ("", "mock"):
        groups, method = cluster_simple(failures), "check + cause type"
    else:
        try:
            groups, method = cluster_with_ai(failures), "AI grouping"
        except Exception as e:
            print(f"AI grouping failed ({str(e)[:150]}); falling back to simple grouping.")
            groups, method = cluster_simple(failures), "check + cause type"

    n_calls = len(calls)
    problems = []
    for g in groups:
        mem = [failures[i] for i in g["members"]]
        keys = sorted({m["key"] for m in mem})
        fatal_keys = sorted({m["key"] for m in mem if m["grade"] == "Fatal"})
        freq = len(keys) / n_calls
        sev = sum(WEIGHT[m["grade"]] for m in mem) / len(mem)
        examples = sorted(mem, key=lambda m: -WEIGHT[m["grade"]])[:6]
        problems.append({
            "name": g["name"], "description": g.get("description", ""), "cause_type": g.get("cause_type", ""),
            "fixable_by_prompt": bool(g.get("fixable_by_prompt", False)),
            "checks": sorted({m["check"] for m in mem}),
            "calls_affected": len(keys), "fatal_calls": len(fatal_keys), "failures": len(mem),
            "frequency_pct": round(100 * freq, 1), "severity": round(sev, 2),
            "priority": round(100 * freq * sev, 1),
            "keys": keys,
            "examples": [{"key": e["key"], "check": e["check"], "grade": e["grade"], "evidence": e["evidence"],
                          "root_cause": e["root_cause"]} for e in examples],
            "first_seen": min((m["graded_at"] for m in mem if m["graded_at"]), default=""),
        })
    problems.sort(key=lambda p: -p["priority"])
    for i, p in enumerate(problems, 1):
        p["rank"] = i
        p["id"] = f"P{i:02d}"

    os.makedirs(out_dir, exist_ok=True)
    meta = {"set": args.set, "calls": n_calls, "failures": len(failures), "method": method,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "formula": "priority = frequency% x severity (Fatal=3, Non-Fatal=1)"}
    with open(os.path.join(out_dir, "problems.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "problems": problems}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "problems.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "name", "cause_type", "calls_affected", "fatal_calls", "frequency_pct", "severity",
                    "priority", "fixable_by_prompt", "description", "example_calls"])
        for p in problems:
            w.writerow([p["rank"], p["id"], p["name"], p["cause_type"], p["calls_affected"], p["fatal_calls"],
                        p["frequency_pct"], p["severity"], p["priority"], p["fixable_by_prompt"], p["description"],
                        " ".join(p["keys"][:5])])
    print(f"\n{len(problems)} problems ({method}). Top 5:")
    for p in problems[:5]:
        print(f"  {p['id']}  priority {p['priority']:>5}  |  {p['frequency_pct']}% of calls, severity {p['severity']}  |  {p['name']}")
    print(f"\nSaved {out_dir}/problems.json")


if __name__ == "__main__":
    main()
