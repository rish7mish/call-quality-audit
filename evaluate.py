"""
STEP 3 - How often does the AI agree with the human auditors?

Compares graded/all_grades.csv with human_labels.csv and writes:
    results/agreement_<split>.md          the numbers for the slide / README
    results/disagreements_<split>.csv     every call where AI and humans differ, side by side,
                                          for a teammate to review ("who was right?")

Run:
    python evaluate.py --split tune       # while improving the rubric
    python evaluate.py --split holdout    # the FINAL number to report (grade holdout only once!)
Needs: pip install pandas
"""
import argparse
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rubric import CHECKS  # noqa: E402

ORDER = ["Pass", "Non-Fatal", "Fatal"]


def kappa(a, b):
    """Cohen's kappa: agreement corrected for chance (1 = perfect, 0 = chance level)."""
    n = len(a)
    if n == 0:
        return float("nan")
    po = (a == b).mean()
    pe = sum((a == c).mean() * (b == c).mean() for c in set(a) | set(b))
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def as_pass(s):
    return s.replace({"NA": "Pass"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="tune", choices=["tune", "holdout", "all"])
    args = ap.parse_args()

    h = pd.read_csv(os.path.join(HERE, "human_labels.csv"), keep_default_na=False)
    ai = pd.read_csv(os.path.join(HERE, "graded", "all_grades.csv"), keep_default_na=False, encoding="utf-8-sig")
    df = h.merge(ai, on="key", how="inner")
    if args.split != "all":
        df = df[df.split == args.split]
    if df.empty:
        sys.exit(f"No graded calls in split '{args.split}' yet. Run grade_calls.py first.")
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)

    hum, mach = df.human_overall, df.overall
    n = len(df)
    acc = (hum == mach).mean()
    k = kappa(hum, mach)
    fatal_h, fatal_a = hum == "Fatal", mach == "Fatal"
    recall = (fatal_h & fatal_a).sum() / max(fatal_h.sum(), 1)
    precision = (fatal_h & fatal_a).sum() / max(fatal_a.sum(), 1)
    bin_acc = ((hum == "Pass") == (mach == "Pass")).mean()
    cm = pd.crosstab(hum.rename("Human"), mach.rename("AI")).reindex(index=ORDER, columns=ORDER, fill_value=0)

    lines = [f"# Agreement with human auditors - split: {args.split}", "",
             f"Calls compared: **{n}**  (human mix: " + ", ".join(f"{g} {int((hum == g).sum())}" for g in ORDER) + ")", "",
             "| Measure | Value | Plain meaning |", "|---|---|---|",
             f"| Exact agreement (Pass / Non-Fatal / Fatal) | **{acc:.0%}** | AI gave the same overall grade as the human |",
             f"| Cohen's kappa | {k:.2f} | agreement beyond chance (0.6+ good, 0.8+ very good) |",
             f"| Problem vs no-problem agreement | {bin_acc:.0%} | both said Pass, or both said some problem |",
             f"| Fatal calls caught (recall) | {recall:.0%} | of the calls humans marked Fatal, how many the AI also marked Fatal |",
             f"| Fatal precision | {precision:.0%} | of the calls the AI marked Fatal, how many humans also did |",
             f"| Avg time to audit one call | {pd.to_numeric(df.audit_seconds, errors='coerce').mean():.0f} s | vs. a human listening to the full call |",
             "", "## Confusion matrix (rows = human, columns = AI)", "", "```\n" + cm.to_string() + "\n```",
             "", "## Per check (only calls where the human graded that check)", "",
             "| Check | Calls | Agreement | Human problems | AI problems | Note |", "|---|---|---|---|---|---|"]
    for c in CHECKS:
        hc, ac = f"h_{c['id']}", f"ai_{c['id']}"
        sub = df[df[hc] != "NA"]
        if sub.empty:
            continue
        a_h, a_m = sub[hc], as_pass(sub[ac])
        note = "" if c["from_call"] else "not assessable from the call (needs dashboard data)"
        lines.append(f"| {c['name']} | {len(sub)} | {(a_h == a_m).mean():.0%} | {int((a_h != 'Pass').sum())} | "
                     f"{int((a_m != 'Pass').sum())} | {note} |")
    report = os.path.join(HERE, "results", f"agreement_{args.split}.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # disagreements, side by side, for human review
    rows = []
    for _, r in df[hum != mach].iterrows():
        diffs = []
        for c in CHECKS:
            cid = c["id"]
            hg, ag = r["h_" + cid], r["ai_" + cid]
            if (hg if hg != "NA" else "Pass") != (ag if ag != "NA" else "Pass"):
                h_note, a_note = r.get("hr_" + cid, ""), r.get("ev_" + cid, "")
                diffs.append(f"{cid}: human={hg} [{h_note}] | AI={ag} [{a_note}]")
        rows.append({"key": r.key, "human_overall": r.human_overall, "ai_overall": r.overall, "ai_summary": r.summary,
                     "differences": "\n".join(diffs), "who_is_right (fill in)": "", "comment (fill in)": ""})
    pd.DataFrame(rows).to_csv(os.path.join(HERE, "results", f"disagreements_{args.split}.csv"),
                              index=False, encoding="utf-8-sig")

    print("\n".join(lines[:12]))
    print(f"\nFull report: {report}")
    print(f"Disagreements to review: results/disagreements_{args.split}.csv ({len(rows)} calls)")


if __name__ == "__main__":
    main()
