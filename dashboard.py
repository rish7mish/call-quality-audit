"""
VANI Call Quality - a guided dashboard for business viewers.

Pages follow the story of the problem statement:
  1 Summary -> 2 How are our calls doing? -> 3 Which calls need a human? -> 4 Why do calls fail?
  -> 5 How do we fix it? -> 6 Did the fix work? -> 7 Can we trust the AI? -> 8 What rules does it follow?
  -> 9 Try it live + settings

Start it:  double-click RUN_DASHBOARD.bat   (or: python -m streamlit run dashboard.py)
It opens in your browser at http://localhost:8501 and runs only on this laptop.
"""
import glob
import json
import os
import sys
import tempfile
import time

import altair as alt
import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rubric import (CHECKS, OVERALL_ORIGIN, RISK_FLAGS, RULE_GROUPS, RULES_CHANGELOG, RULES_VERSION, SOURCES,  # noqa: E402
                    build_system_prompt, rules_table)

# ---------------------------------------------------------------- plain-language vocabulary
CHECK_NAME = {c["id"]: c["name"] for c in CHECKS}
ASSESSABLE = {c["id"] for c in CHECKS if c["from_call"]}
GRADE = {"Fatal": "🔴 Serious (Fatal)", "Non-Fatal": "🟠 Minor (Non-Fatal)", "Pass": "✅ OK (Pass)", "NA": "– Not applicable"}
GRADE_SHORT = {"Fatal": "Serious", "Non-Fatal": "Minor", "Pass": "OK"}
GRADE_COLORS = {"OK": "#0ca30c", "Minor": "#ec835a", "Serious": "#d03b3b"}  # status colours, always shown with words
CAUSE = {"prompt": "Bot instructions", "asr_stt": "Speech recognition (mishearing)", "knowledge": "Product knowledge",
         "flow_logic": "Call flow", "tts_voice": "Bot voice", "data_mapping": "Category data", "": "Other"}
FLAG = {"wrong_requirement": "Wrong requirement captured", "frustration": "Buyer sounded frustrated",
        "loop": "Bot going in circles", "low_confidence": "Unclear audio at a key moment",
        "human_request": "Buyer asked for a person / specific seller"}
ACCENT, MUTED = "#2a78d6", "#8a8985"

PAGES = ["1 · Summary", "2 · How are our calls doing?", "3 · Which calls need a human?", "4 · Why do calls fail?",
         "5 · How do we fix it?", "6 · Did the fix work?", "7 · Can we trust the AI?", "8 · What rules does it follow?",
         "9 · Try it live + settings"]

st.set_page_config(page_title="VANI Call Quality", page_icon="📞", layout="wide")
st.markdown("""<style>
.block-container {padding-top: 1.4rem; max-width: 1250px;}
div[data-testid="stMetricValue"] {font-size: 1.9rem;}
.answers {font-size: 1.05rem; color: #52514e; margin: -0.4rem 0 0.2rem 0;}
.hint {font-size: 0.9rem; color: #6b6a66; margin-bottom: 0.8rem;}
.card {border: 1px solid rgba(127,127,127,0.25); border-radius: 10px; padding: 14px 16px; margin: 8px 0;}
.card h4 {margin: 0 0 4px 0;}
.quote {background: rgba(127,127,127,0.08); border-left: 3px solid #2a78d6; border-radius: 4px; padding: 6px 10px;
        margin: 4px 0; font-size: 0.92rem;}
.big {font-size: 1.15rem;}
.small {color: #6b6a66; font-size: 0.85rem;}
.step {text-align: center; padding: 10px 6px;}
.step .icon {font-size: 2rem;}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- data
@st.cache_data(show_spinner=False)
def load_graded(folder, _stamp):
    rows = []
    for p in sorted(glob.glob(os.path.join(HERE, folder, "*.json"))):
        with open(p, encoding="utf-8") as f:
            rows.append(json.load(f))
    return rows


@st.cache_data(show_spinner=False)
def load_json(path, _stamp):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def load_labels(_stamp):
    p = os.path.join(HERE, "human_labels.csv")
    return pd.read_csv(p, keep_default_na=False) if os.path.exists(p) else None


@st.cache_data(show_spinner=False)
def human_vs_human():
    """Calls graded twice in the sample audit sheet: how often did the two audits agree?"""
    p = os.path.join(HERE, "inputs", "audit_source_of_truth.csv")
    p = p if os.path.exists(p) else None
    if not p:
        return None
    try:
        au = pd.read_csv(p, low_memory=False)
        au.columns = [c.replace("\n", " ").strip() for c in au.columns]
        au["key"] = au["Call Recording"].astype(str).str.extract(r"/([A-Za-z0-9]+)\.mp3")[0]
        au = au[au["Overall Quality"].isin(["Pass", "Non-Fatal", "Fatal"]) & au.key.notna()]
        d = au[au.duplicated("key", keep=False)]
        pairs = [g["Overall Quality"].head(2).tolist() for _, g in d.groupby("key")]
        pairs = [p_ for p_ in pairs if len(p_) == 2]
        if not pairs:
            return None
        return len(pairs), sum(a == b for a, b in pairs)
    except Exception:
        return None


def stamp(folder):
    files = glob.glob(os.path.join(HERE, folder, "**", "*.json"), recursive=True)
    return (len(files), max((os.path.getmtime(f) for f in files), default=0))


def kappa(a, b):
    po = (a == b).mean()
    pe = sum((a == c).mean() * (b == c).mean() for c in set(a) | set(b))
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


if "page" not in st.session_state:
    st.session_state.page = PAGES[0]
if "dataset" not in st.session_state:
    st.session_state.dataset = "audited"
audited = st.session_state.dataset == "audited"
GDIR = "graded" if audited else "graded_provided"
PDIR = "problems" if audited else "problems_provided"
calls = load_graded(GDIR, stamp(GDIR))
by_key = {c["key"]: c for c in calls}
labels = load_labels(stamp("graded")) if audited else None
problems_doc = load_json(os.path.join(HERE, PDIR, "problems.json"), stamp(PDIR))
problems = problems_doc["problems"] if problems_doc else []
fixes = [load_json(f, stamp("fixes")) for f in sorted(glob.glob(os.path.join(HERE, "fixes", "P*", "fix.json")))]
tests = [load_json(f, stamp("tests")) for f in sorted(glob.glob(os.path.join(HERE, "tests", "P*", "results.json")))]
moments = [load_json(f, stamp("tests")) for f in sorted(glob.glob(os.path.join(HERE, "tests", "P*", "moment_results.json")))]
moments = [m for m in moments if m and m.get("total_tries")]
n = len(calls)


def agreement(split):
    """Human vs AI overall grade on the audited sample. split: holdout / tune / all."""
    if labels is None or not calls:
        return None
    ai = pd.DataFrame([{"key": c["key"], "ai": c["overall"], **{f"ai_{k}": v["grade"] for k, v in c["checks"].items()}}
                       for c in calls])
    m = labels.merge(ai, on="key")
    if split != "all":
        m = m[m.split == split]
    if m.empty:
        return None
    hf, af = m.human_overall == "Fatal", m.ai == "Fatal"
    return {"m": m, "n": len(m), "same": int((m.human_overall == m.ai).sum()),
            "acc": (m.human_overall == m.ai).mean(), "kappa": kappa(m.human_overall, m.ai),
            "fatal_caught": (hf & af).sum() / max(hf.sum(), 1), "fatal_right": (hf & af).sum() / max(af.sum(), 1),
            "n_hf": int(hf.sum()), "n_af": int(af.sum()), "n_both": int((hf & af).sum())}


# ---------------------------------------------------------------- sidebar = story navigation
def go(page):
    st.session_state.page = page


with st.sidebar:
    st.markdown("## 📞 VANI Call Quality")
    st.caption("Every bot call checked automatically → problems found → fix suggested → fix proven.")
    st.radio("Go to", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    st.caption(f"Showing: **{'audited sample calls' if audited else 'unaudited sample calls'}** · {n} calls checked")
    st.caption("Settings are on page 9.")


def header(title, answers, hint=""):
    st.title(title)
    st.markdown(f"<div class='answers'>This page answers: <b>{answers}</b></div>", unsafe_allow_html=True)
    if hint:
        st.markdown(f"<div class='hint'>👀 {hint}</div>", unsafe_allow_html=True)


def next_button(current):
    i = PAGES.index(current)
    st.divider()
    if i + 1 < len(PAGES):
        st.button(f"Next: {PAGES[i + 1].split(' · ', 1)[1]} →", on_click=go, args=(PAGES[i + 1],), type="primary")


def empty(msg):
    st.info(msg)


def call_story(c, key_suffix=""):
    """One call told as a short story."""
    st.markdown(f"#### Call {c['key']} — {GRADE[c['overall']]}")
    if c.get("summary"):
        st.markdown(f"<div class='big'>📝 {c['summary']}</div>", unsafe_allow_html=True)
    flags = [FLAG.get(f, f) for f, v in c["risk_flags"].items() if v]
    if flags:
        st.warning("**Needs a human look:** " + " · ".join(flags))
    problems_here = [(cid, r) for cid, r in c["checks"].items() if r["grade"] in ("Fatal", "Non-Fatal")]
    problems_here.sort(key=lambda x: x[1]["grade"] != "Fatal")
    human = None
    if labels is not None:
        hr = labels[labels.key == c["key"]]
        human = hr.iloc[0].to_dict() if len(hr) else None
    if human is not None:
        hg = human["human_overall"]
        same = "✔ same verdict" if hg == c["overall"] else "✖ different verdict"
        st.markdown(f"**Human auditor's verdict:** {GRADE.get(hg, hg)} &nbsp; <span class='small'>({same})</span>",
                    unsafe_allow_html=True)
    if not problems_here:
        st.success("No problems found on any of the 17 checks.")
    for cid, r in problems_here:
        hnote = ""
        if human is not None:
            hg = human.get("h_" + cid, "NA")
            hrem = human.get("hr_" + cid, "")
            hnote = f"<br><span class='small'>Human auditor on this check: {GRADE.get(hg, hg)}" + \
                    (f" — “{hrem}”" if hrem else "") + "</span>"
        st.markdown(f"<div class='card'><h4>{GRADE[r['grade']]} · {CHECK_NAME.get(cid, cid)}</h4>"
                    f"{r.get('reason', '')}"
                    + (f"<div class='quote'>🗣️ {r['evidence']}</div>" if r.get("evidence") else "")
                    + (f"<span class='small'>Likely cause: {CAUSE.get(r.get('cause_type', ''), r.get('cause_type', ''))}</span>"
                       if r.get("cause_type") else "") + hnote + "</div>", unsafe_allow_html=True)
    with st.expander("Read the full conversation"):
        st.text(c.get("transcript", "(transcript not stored for this call)"))
    with st.expander("All 17 checks for this call"):
        rows = [{"Check": CHECK_NAME.get(cid, cid), "Result": GRADE.get(r["grade"], r["grade"]),
                 "Proof from the call": r.get("evidence", "")} for cid, r in c["checks"].items()]
        if human is not None:
            for row, cid in zip(rows, c["checks"]):
                row["Human auditor"] = GRADE.get(human.get(f"h_{cid}", "NA"), "")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if c.get("silences"):
        st.caption("Silences over 7 s after the buyer spoke: " +
                   ", ".join(f"{s['from']}–{s['to']} ({s['seconds']} s)" for s in c["silences"]))


page = st.session_state.page

# ================================================================= 1 SUMMARY
if page == PAGES[0]:
    header("Voice bot call quality — summary", "What did checking every call automatically find?",
           "Four headline numbers, then how the system works. Use the menu on the left or the Next button to walk through.")
    if not n:
        empty("No calls have been checked yet. Run the grading step first (RUN_TEST_SMALL.bat).")
    else:
        serious = sum(c["overall"] == "Fatal" for c in calls)
        minor = sum(c["overall"] == "Non-Fatal" for c in calls)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Calls checked automatically", f"{n}", help="Every call in the set is checked - today only a small sample is listened to by hand.")
        k1.caption("100% of calls · about 8 seconds each")
        k2.metric("Calls with a serious problem", f"{serious / n:.0%}")
        k2.caption(f"{serious} serious · {minor} minor · {n - serious - minor} OK")
        if problems:
            top = problems[0]
            k3.metric("#1 reason calls fail", f"{top['frequency_pct']:.0f}% of calls")
            k3.caption(top["name"])
        else:
            k3.metric("#1 reason calls fail", "–")
            k3.caption("Run the 'find problems' step")
        if moments and moments[-1]["valid_moments"] and moments[-1]["current_mistakes"] <= 0.25 * moments[-1]["total_tries"]:
            mt = moments[-1]
            k4.metric("Fix test finding", "Rule exists, not followed",
                      help="At the failure moments in the sample calls, a test bot with today's instructions already avoided the mistake - see page 6.")
            k4.caption(f"{mt['problem_name']}: the live bot breaks a rule it already has → shorten instructions / check the model")
        elif moments:
            mt = moments[-1]
            k4.metric("Fix tested: same mistake repeated", f"{mt['current_mistakes']}/{mt['total_tries']} → {mt['fixed_mistakes']}/{mt['total_tries']}",
                      help="At the failure moments in the sample calls, how often the bot repeated the mistake with today's instructions vs the fix.")
            k4.caption(f"{mt['problem_name']} ({mt['valid_moments']} sample moments)")
        elif tests:
            t = tests[-1]
            k4.metric("Fix tested", f"{t['failure_rate_current']:.0f}% → {t['failure_rate_fixed']:.0f}%")
            k4.caption(f"{t['problem_name']} (on {t['calls_replayed']} replayed calls)")
        else:
            k4.metric("Fix tested", "–")
            k4.caption("Run the fix step")
        ag = agreement("holdout") or agreement("all")
        if ag:
            label = "calls it had never seen before" if agreement("holdout") else "the audited sample calls"
            st.info(f"**Can we trust it?** On {ag['n']} {label}, the AI gave the same verdict as the human auditors on "
                    f"**{ag['same']} of {ag['n']} calls ({ag['acc']:.0%})**. When it marks a call **serious**, the auditors "
                    f"agree **{ag['fatal_right']:.0%}** of the time. Details on page 7.")
        st.subheader("How it works")
        steps = [("🎧", "1. Listen", "Each call is turned into text with who said what, and when."),
                 ("✅", "2. Check", "An AI auditor checks every call on the auditors' own 17-point checklist and quotes the proof."),
                 ("🔎", "3. Find patterns", "Failures are grouped into root causes and ranked by how often and how badly they hurt."),
                 ("🛠️", "4. Fix & prove", "For the top problems it writes a change to the bot's instructions and replays failed calls to prove it works.")]
        cols = st.columns(4)
        for col, (icon, t_, d) in zip(cols, steps):
            col.markdown(f"<div class='card step'><div class='icon'>{icon}</div><b>{t_}</b><br>"
                         f"<span class='small'>{d}</span></div>", unsafe_allow_html=True)
    next_button(page)

# ================================================================= 2 CALLS
elif page == PAGES[1]:
    header("How are our calls doing?", "How many calls go wrong, and on which checks?",
           "Left: the overall result. Right: which of the 17 checks fail most. Below: open any call to read what happened.")
    if not n:
        empty("No calls checked yet.")
    else:
        c1, c2 = st.columns([1, 2])
        dist = pd.DataFrame({"Result": ["OK", "Minor", "Serious"],
                             "Calls": [sum(c["overall"] == g for c in calls) for g in ["Pass", "Non-Fatal", "Fatal"]]})
        ch = alt.Chart(dist).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("Result:N", sort=["OK", "Minor", "Serious"], title=None, axis=alt.Axis(labelFontSize=13, labelOverlap=False)),
            x=alt.X("Calls:Q", title="Number of calls"),
            color=alt.Color("Result:N", scale=alt.Scale(domain=list(GRADE_COLORS), range=list(GRADE_COLORS.values())), legend=None),
            tooltip=["Result", "Calls"]).properties(height=170)
        with c1:
            st.markdown("**Overall result per call**")
            st.altair_chart(ch + ch.mark_text(align="left", dx=4, color="#6b6a66").encode(text="Calls:Q", color=alt.value("#6b6a66")),
                            use_container_width=True)
            st.caption("A call's result = its worst check (the auditors' own rule).")
        fails = [{"Check": CHECK_NAME.get(cid, cid), "Severity": GRADE_SHORT[r["grade"]]}
                 for c in calls for cid, r in c["checks"].items() if r["grade"] in ("Fatal", "Non-Fatal")]
        with c2:
            st.markdown("**Which checks fail most**")
            if fails:
                fd = pd.DataFrame(fails).value_counts().reset_index(name="Calls")
                order = fd.groupby("Check").Calls.sum().sort_values(ascending=False).index.tolist()
                st.altair_chart(alt.Chart(fd).mark_bar().encode(
                    y=alt.Y("Check:N", sort=order, title=None, axis=alt.Axis(labelLimit=260)),
                    x=alt.X("Calls:Q", stack="zero", title="Calls failing this check"),
                    color=alt.Color("Severity:N", scale=alt.Scale(domain=["Minor", "Serious"],
                                                                  range=[GRADE_COLORS["Minor"], GRADE_COLORS["Serious"]]),
                                    legend=alt.Legend(orient="top", title=None)),
                    tooltip=["Check", "Severity", "Calls"]), use_container_width=True)
            else:
                st.success("No failing checks.")
        st.subheader("Read the calls")
        f1, f2 = st.columns(2)
        show = f1.multiselect("Show calls that are", ["Serious", "Minor", "OK"], default=["Serious"])
        chk = f2.selectbox("…and failed this check", ["(any check)"] + [CHECK_NAME[c] for c in CHECK_NAME])
        inv = {"Serious": "Fatal", "Minor": "Non-Fatal", "OK": "Pass"}
        view = [c for c in calls if c["overall"] in {inv[s] for s in show} and
                (chk == "(any check)" or any(CHECK_NAME.get(k) == chk and v["grade"] in ("Fatal", "Non-Fatal")
                                             for k, v in c["checks"].items()))]
        st.dataframe(pd.DataFrame([{"Call": c["key"], "Result": GRADE[c["overall"]], "What happened": c.get("summary", ""),
                                    "Problems found": ", ".join(CHECK_NAME[k] for k, v in c["checks"].items()
                                                                if v["grade"] in ("Fatal", "Non-Fatal"))} for c in view]),
                     hide_index=True, use_container_width=True, height=260)
        if view:
            pick = st.selectbox(f"Open a call ({len(view)} shown)", [c["key"] for c in view],
                                format_func=lambda k: f"{k} — {GRADE_SHORT.get(by_key[k]['overall'], '')} — {by_key[k].get('summary', '')[:80]}")
            call_story(by_key[pick])
    next_button(page)

# ================================================================= 3 NEEDS A HUMAN
elif page == PAGES[2]:
    header("Which calls need a human?", "Which calls should an auditor listen to first?",
           "These calls were flagged for a person to review, with the reason. Most-flagged calls are at the top.")
    risky = sorted([c for c in calls if any(c["risk_flags"].values())],
                   key=lambda c: (-(c["overall"] == "Fatal"), -sum(c["risk_flags"].values())))
    if not risky:
        empty("No calls flagged for review.")
    else:
        counts = pd.DataFrame([{"Reason": FLAG[k], "Calls": sum(c["risk_flags"][k] for c in calls)} for k in FLAG])
        st.altair_chart(alt.Chart(counts).mark_bar(cornerRadiusEnd=4, color=ACCENT).encode(
            y=alt.Y("Reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=300)), x=alt.X("Calls:Q", title="Calls flagged"),
            tooltip=["Reason", "Calls"]).properties(height=170), use_container_width=True)
        st.markdown(f"**{len(risky)} of {n} calls** need a human look.")
        st.dataframe(pd.DataFrame([{"Call": c["key"], "Result": GRADE[c["overall"]],
                                    "Why it needs a human": " · ".join(FLAG[k] for k, v in c["risk_flags"].items() if v),
                                    "Details": c.get("risk_reason", "")} for c in risky]),
                     hide_index=True, use_container_width=True, height=300)
        pick = st.selectbox("Open a flagged call", [c["key"] for c in risky],
                            format_func=lambda k: f"{k} — {' · '.join(FLAG[f] for f, v in by_key[k]['risk_flags'].items() if v)}")
        call_story(by_key[pick])
    next_button(page)

# ================================================================= 4 WHY CALLS FAIL
elif page == PAGES[3]:
    header("Why do calls fail?", "What are the main reasons behind the failures, and which matter most?",
           "Each card is one root cause found across many calls. #1 hurts the most.")
    if not problems:
        empty("Root causes not computed yet (run root_causes.py).")
    else:
        st.caption(f"Found from {problems_doc['meta']['failures']} failed checks in {problems_doc['meta']['calls']} calls. "
                   "**Impact score** = % of calls affected × how serious (serious counts 3, minor counts 1).")
        top = pd.DataFrame([{"Problem": f"#{p['rank']} {p['name']}", "Impact score": p["priority"],
                             "% of calls": p["frequency_pct"]} for p in problems[:8]])
        ch = alt.Chart(top).mark_bar(cornerRadiusEnd=4, color=ACCENT).encode(
            y=alt.Y("Problem:N", sort=top.Problem.tolist(), title=None, axis=alt.Axis(labelLimit=380)),
            x=alt.X("Impact score:Q"), tooltip=["Problem", "% of calls", "Impact score"])
        st.altair_chart(ch + ch.mark_text(align="left", dx=4, color="#6b6a66").encode(text="Impact score:Q", color=alt.value("#6b6a66")),
                        use_container_width=True)
        for p in problems[:8]:
            fixable = "✔ can be fixed by changing the bot's instructions" if p.get("fixable_by_prompt") else \
                "needs a fix outside the bot's instructions (speech recognition, data, or call flow)"
            st.markdown(f"<div class='card'><h4>#{p['rank']} · {p['name']}</h4>{p['description']}<br>"
                        f"<b>Affects {p['frequency_pct']:.0f}% of calls</b> ({p['calls_affected']} calls, {p['fatal_calls']} serious) · "
                        f"Type: {CAUSE.get(p['cause_type'], p['cause_type'])}<br><span class='small'>{fixable}</span></div>",
                        unsafe_allow_html=True)
            with st.expander(f"Examples from the sample calls — #{p['rank']}"):
                for e in p["examples"][:4]:
                    st.markdown(f"<div class='quote'><b>{e['key']}</b> · {GRADE[e['grade']]} · {CHECK_NAME.get(e['check'], e['check'])}"
                                f"<br>🗣️ {e['evidence']}</div>", unsafe_allow_html=True)
    next_button(page)

# ================================================================= 5 FIX
elif page == PAGES[4]:
    header("How do we fix it?", "What exactly should change in the bot's instructions?",
           "For a top problem, the system reads the bot's current instructions and writes a specific change - not generic advice.")
    real_fixes = [f for f in fixes if f]
    if not real_fixes:
        empty("No fix suggested yet (run RUN_FIX_DEMO.bat).")
    for fx in real_fixes:
        st.subheader(f"Problem: {fx['problem_name']}")
        st.markdown(f"**What's going wrong today:** {fx.get('diagnosis', '')}")
        for i, e in enumerate(fx.get("edits") or [], 1):
            sec = e.get("section", "")
            if (e.get("action") or "add") == "replace" and e.get("old_text"):
                st.markdown(f"**Change {i}** — rewrite a rule in the section *{sec}*:")
                a, b = st.columns(2)
                a.markdown("**Before**")
                a.markdown(f"<div class='quote' style='border-color:#8a8985'>{e['old_text']}</div>", unsafe_allow_html=True)
                b.markdown("**After**")
                b.markdown(f"<div class='quote'>{e.get('new_text', '')}</div>", unsafe_allow_html=True)
            elif (e.get("action") or "") == "remove":
                st.markdown(f"**Change {i}** — remove from *{sec}*:")
                st.markdown(f"<div class='quote' style='border-color:#d03b3b'>{e.get('old_text', '')}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"**Change {i}** — add this rule to the section *{sec}*:")
                st.markdown(f"<div class='quote'>➕ {e.get('new_text', '')}</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.markdown(f"**What we expect:** {fx.get('expected_effect', '')}")
        c2.markdown(f"**What could go wrong:** {fx.get('risks', '')}")
        dpath = os.path.join(HERE, "fixes", fx["problem_id"], "diff.txt")
        with st.expander("Technical details: exact change to the instructions file (diff)"):
            st.caption("Lines starting with + are added, - are removed.")
            if os.path.exists(dpath):
                with open(dpath, encoding="utf-8") as f:
                    st.code(f.read()[:20000], language="diff")
        st.divider()
    next_button(page)

# ================================================================= 6 DID IT WORK
elif page == PAGES[5]:
    header("Did the fix work?", "If we change the bot's instructions, does it stop making the mistake?",
           "We go back to the exact moments in the sample calls where the bot made the mistake, and ask it what it would say next - "
           "with today's instructions and with the fix.")
    real_tests = [t for t in tests if t]
    if not moments and not real_tests:
        empty("No fix tested yet (run RUN_FIX_DEMO.bat or RUN_TEST_FIX.bat).")

    def minutes(rec):
        try:
            return (time.mktime(time.strptime(rec["fix_tested_at"], "%Y-%m-%d %H:%M:%S")) -
                    time.mktime(time.strptime(rec["issue_found_at"], "%Y-%m-%d %H:%M:%S"))) / 60
        except Exception:
            return None

    for mt in moments:
        st.subheader(mt["problem_name"])
        tot = mt["total_tries"]
        a, b, c = st.columns(3)
        a.metric("Today's instructions", f"{mt['current_mistakes']} of {tot} tries")
        a.caption("repeated the same mistake")
        b.metric("With the fix", f"{mt['fixed_mistakes']} of {tot} tries")
        d = mt["current_mistakes"] - mt["fixed_mistakes"]
        b.caption(f"✅ {d} fewer mistakes" if d > 0 else ("➖ no change" if d == 0 else "⚠️ more mistakes - the fix needs work"))
        fx_rec = next((f for f in fixes if f and f.get("problem_id") == mt["problem_id"]), {}) or {}
        compute = (float(fx_rec.get("suggest_seconds") or 0) + float(mt.get("test_seconds") or 0)) / 60
        c.metric("Time to write + test the fix", f"{compute:.0f} min" if compute >= 1 else "< 1 min",
                 help="Computer time from 'problem found' to 'fix tested' (writing the fix + running the test). "
                      "Today this loop takes days or weeks of manual work.")
        c.caption(f"{mt['valid_moments']} failure moments × {mt['tries']} tries each")
        if mt["valid_moments"] and mt["current_mistakes"] <= 0.25 * tot:
            st.info("**Key finding.** At these moments the bot in the sample calls did make the mistake (confirmed above), but our "
                    "test bot - given the same moment and **today's** instructions - avoided it in "
                    f"{tot - mt['current_mistakes']} of {tot} tries. Today's instructions **already contain the rule** "
                    "(not to assume a quantity the buyer never gave). "
                    "So the live bot is not missing a rule - it is **not following one it already has**. The likely causes are its very long "
                    "instructions (≈159,000 characters), the model it runs on, or real-time speech recognition. "
                    "**Next step:** shorten / restructure the quantity section, and re-run this same test against the live bot's own model "
                    "with its full instructions.")
        chart = pd.DataFrame({"Version": ["Today's instructions", "With the fix"],
                              "Mistakes": [mt["current_mistakes"], mt["fixed_mistakes"]]})
        st.altair_chart(alt.Chart(chart).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("Version:N", sort=None, title=None, axis=alt.Axis(labelFontSize=13, labelLimit=300, labelOverlap=False)),
            x=alt.X("Mistakes:Q", scale=alt.Scale(domain=[0, max(tot, 1)]), title=f"Times the mistake was repeated (out of {tot})"),
            color=alt.Color("Version:N", scale=alt.Scale(domain=["Today's instructions", "With the fix"], range=[MUTED, ACCENT]),
                            legend=None), tooltip=["Version", "Mistakes"]).properties(height=130), use_container_width=True)
        st.markdown("**The failure moments** — pick one to see what the bot said with and without the fix")
        cases = mt["cases"]
        pick = st.selectbox("Moment", range(len(cases)), key=f"mom_{mt['problem_id']}",
                            format_func=lambda i: f"Call {cases[i]['key']} — {cases[i]['root_cause'][:90]}"
                            + ("" if cases[i]["real_mistake"] else "  (not counted)"))
        cse = cases[pick]
        st.markdown("<div class='small'>The conversation up to that moment:</div>", unsafe_allow_html=True)
        st.text("\n".join(cse["prefix"].splitlines()[-5:]))
        st.markdown(f"<div class='quote' style='border-color:#d03b3b'>🎙️ <b>What the bot said in the sample call:</b> "
                    f"{cse['real_reply']}<br><span class='small'>{'🔴 the mistake' if cse['real_mistake'] else 'not judged a mistake - this moment is not counted'}"
                    f" — {cse.get('real_why', '')}</span></div>", unsafe_allow_html=True)
        l, r_ = st.columns(2)
        for col, v, lab in [(l, "current", "With today's instructions"), (r_, "fixed", "With the fix")]:
            col.markdown(f"**{lab}**")
            for rep in cse["replies"][v]:
                col.markdown(f"<div class='quote' style='border-color:{'#d03b3b' if rep['mistake'] else '#0ca30c'}'>"
                             f"{'🔴 same mistake' if rep['mistake'] else '✅ handled correctly'}<br>{rep['reply']}"
                             f"<br><span class='small'>{rep['why']}</span></div>", unsafe_allow_html=True)
        with st.expander("How we tested, and the limits"):
            st.markdown("- We take sample calls where the auditor-AI found this problem and cut each one **just before the bot's "
                        "wrong reply** (found from the quoted proof).\n"
                        f"- The bot is asked for its next line **{mt['tries']} times with today's instructions and {mt['tries']} times "
                        "with the fix**, from exactly the same point in the conversation.\n"
                        "- A judge AI answers one narrow question per reply: *did the bot make this same mistake again?* "
                        "It also checks the bot's actual reply in the sample call, so moments that don't really show the mistake "
                        "are not counted.\n"
                        "- Limits: text only (no voice or speech recognition), a handful of moments, and the bot sees the parts "
                        "of its instructions related to the fix. It shows whether the change works at the moment it matters; "
                        "a live A/B test would confirm it at scale.")
        st.divider()

    if real_tests:
        with st.expander("Exploratory: full replayed conversations (an AI plays the whole buyer side)"):
            st.caption("Whole conversations wander in different directions every time, so these are examples, not the score.")
            for t in real_tests:
                sel = st.selectbox("Replayed call", [r["key"] for r in t["results"]], key=f"cmp_{t['problem_id']}")
                rec = next(r for r in t["results"] if r["key"] == sel)
                l, r_ = st.columns(2)
                for col, v, lab in [(l, "current", "Today's instructions"), (r_, "fixed", "With the fix")]:
                    col.markdown(f"**{lab}**")
                    col.text(rec[v]["transcript"])
    next_button(page)

# ================================================================= 7 TRUST
elif page == PAGES[6]:
    header("Can we trust the AI's judgement?", "How often does the AI auditor agree with the human auditors?",
           "We compare the AI's verdict with the human verdict on the same calls. The honest test is on calls the AI never saw while we set up its rules.")
    if not audited:
        empty("This comparison needs human-audited calls - switch to the audited sample on page 9.")
    else:
        choice = st.radio("Which calls", ["Calls the AI had never seen (honest score)", "Calls used to set up the rules",
                                          "All audited calls"], horizontal=True)
        split = {"Calls the AI had never seen (honest score)": "holdout", "Calls used to set up the rules": "tune",
                 "All audited calls": "all"}[choice]
        ag = agreement(split)
        if not ag:
            empty("No graded calls in this group yet.")
        else:
            a, b, c = st.columns(3)
            a.metric("Same verdict as the human", f"{ag['acc']:.0%}")
            a.caption(f"{ag['same']} of {ag['n']} calls got exactly the same result (OK / Minor / Serious)")
            b.metric("When the AI says 'serious', it's right", f"{ag['fatal_right']:.0%}")
            b.caption(f"{ag['n_both']} of the {ag['n_af']} calls it marked serious, the auditors also marked serious")
            c.metric("Serious calls it catches", f"{ag['fatal_caught']:.0%}")
            c.caption(f"{ag['n_both']} of the {ag['n_hf']} calls the auditors marked serious")
            hh = human_vs_human()
            if hh:
                st.caption(f"For context: {hh[0]} calls in the sample audit sheet were audited twice, and the two human audits gave the "
                           f"same verdict on {hh[1]} of them ({hh[1] / hh[0]:.0%}). Even humans don't always agree.")
            st.markdown("**Human said vs AI said** — the diagonal is agreement")
            m = ag["m"]
            order = ["Pass", "Non-Fatal", "Fatal"]
            cm = pd.crosstab(m.human_overall, m.ai).reindex(index=order, columns=order, fill_value=0)
            cm.index = [f"Human: {GRADE_SHORT[g]}" for g in order]
            cm.columns = [f"AI: {GRADE_SHORT[g]}" for g in order]
            st.dataframe(cm, use_container_width=True)
            st.markdown("**Where the AI and humans agree, check by check**")
            rows = []
            for chk in CHECKS:
                hcol, acol = "h_" + chk["id"], "ai_" + chk["id"]
                sub = m[m[hcol] != "NA"]
                if len(sub):
                    aig = sub[acol].replace({"NA": "Pass"})
                    agree = (sub[hcol] == aig).mean()
                    rows.append({"Check": chk["name"], "Calls compared": len(sub),
                                 "Agreement": f"{agree:.0%}",
                                 "Problems found by humans": int((sub[hcol] != "Pass").sum()),
                                 "Problems found by AI": int((aig != "Pass").sum()),
                                 "Note": "" if chk["id"] in ASSESSABLE else "needs dashboard data, not in the call"})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            with st.expander("Technical details (for data people)"):
                st.markdown(f"- **Cohen's kappa = {ag['kappa']:.2f}** — agreement after removing what would match by pure chance "
                            "(0 = chance, 0.4 = moderate, 0.6+ = good, 0.8+ = very good).\n"
                            f"- **Fatal precision = {ag['fatal_right']:.0%}** (of calls the AI marks serious, share humans also marked serious).\n"
                            f"- **Fatal recall = {ag['fatal_caught']:.0%}** (of calls humans marked serious, share the AI also caught).\n"
                            "- **Tune vs holdout**: rules were adjusted only on the tune calls; holdout calls were graded once at the end, "
                            "so their score is not flattered by the tuning.\n"
                            "- Known limits: about 1 in 10 human verdicts relies on data the call doesn't contain (lead dashboard, "
                            "category mapping, seller availability).")
    next_button(page)

# ================================================================= 8 RULES
elif page == PAGES[7]:
    header("What rules does it follow?", "What exactly does the AI check, and where did those rules come from?",
           "These are the auditors' own rules, written down so an AI can apply them. Click any check to see what counts as serious.")
    GROUP_BADGE = {"A": "🟦", "B": "🟩", "C": "🟨", "D": "🟪", "E": "⬜", "F": "🟧"}
    st.subheader("How a call is checked")
    steps = [("1 · Prepare", "⚙️ computer", "Label each line Bot or Buyer, count the buyer's words, and measure silences over 7 s after the buyer spoke."),
             ("2 · Instruct", "⚙️ computer", "Give the AI its role (senior call auditor) and all 17 rules, and ask for proof for every problem."),
             ("3 · Check", "🤖 AI", "The AI reads the call and marks each check OK / Minor / Serious / not applicable, quoting the exact line."),
             ("4 · Validate", "⚙️ computer", "Invalid answers become 'not applicable'; checks that need data outside the call can't be guessed."),
             ("5 · Decide", "⚙️ computer", "A call's result = its worst check (the auditors' own rule).")]
    for col, (t_, who, txt) in zip(st.columns(5), steps):
        col.markdown(f"**{t_}**<br><span class='small'>{who}</span>", unsafe_allow_html=True)
        col.caption(txt)
    st.subheader("Where the rules came from")
    gcols = st.columns(3)
    for i, (g, (name, expl)) in enumerate(RULE_GROUPS.items()):
        gcols[i % 3].markdown(f"{GROUP_BADGE[g]} **{name}**<br><span class='small'>{expl}</span>", unsafe_allow_html=True)
    st.info(f"**How a call's result is decided** {GROUP_BADGE[OVERALL_ORIGIN[0]]} — {OVERALL_ORIGIN[1]}")
    st.subheader(f"The 17 checks · rules {RULES_VERSION}")
    rt = pd.DataFrame(rules_table())
    st.dataframe(pd.DataFrame({"Check": rt.check,
                               "Where it came from": rt.group_codes.map(lambda gs: "  ".join(f"{GROUP_BADGE[g]} {RULE_GROUPS[g][0]}" for g in gs)),
                               "Can be judged from the call": rt.judged_from_call}),
                 hide_index=True, use_container_width=True, height=36 * (len(rt) + 1) + 4)
    for _, r in rt.iterrows():
        with st.expander(f"{' '.join(GROUP_BADGE[g] for g in r.group_codes)}  {r.check}"):
            if r.what_it_checks:
                st.markdown(f"**What it checks:** {r.what_it_checks}")
            st.markdown(f"**Why this rule:** {r.reasoning}")
            for lab, val in [("🔴 Serious when", r.fatal_when), ("🟠 Minor when", r.non_fatal_when),
                             ("✅ OK when", r.pass_when), ("– Not applicable when", r.na_when)]:
                if val:
                    st.markdown(f"**{lab}:** {val}")
    st.download_button("⬇️ Download the rules (opens in Excel)", rt.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"vani_audit_rules_{RULES_VERSION.split()[0]}.csv", mime="text/csv")
    st.subheader("How the rules were improved")
    st.caption("Rules were adjusted only on the 'set-up' calls; the never-seen calls stayed untouched so the trust score is honest.")
    st.dataframe(pd.DataFrame([{"Version": v, "Why": why, "What changed": what} for v, why, what in RULES_CHANGELOG]),
                 hide_index=True, use_container_width=True, column_config={"What changed": st.column_config.TextColumn(width="large")})
    st.subheader("Sources")
    s1, s2 = st.columns([2, 3])
    with s1:
        for name, what in SOURCES:
            st.markdown(f"- **{name}** — {what}")
    with s2:
        img = os.path.join(HERE, "inputs", "auditor_matrix.png")
        img = img if os.path.exists(img) else ""
        if img:
            st.image(img, caption="The auditors' current checklist (the starting point)")
    with st.expander("Technical details: the exact instructions the AI receives"):
        st.code(build_system_prompt(), language="text")
    next_button(page)

# ================================================================= 9 LIVE + SETTINGS
elif page == PAGES[8]:
    header("Try it live", "What does the AI auditor say about a call right now?",
           "Paste a conversation (or upload a recording) and press the button. Settings for the demo are further down.")
    mode = st.radio("Input", ["Paste a conversation", "Upload a recording (needs Sarvam key)"], horizontal=True)
    turns, has_audio, key = None, True, f"live_{time.strftime('%H%M%S')}"
    if mode.startswith("Paste"):
        txt = st.text_area("One line per turn, like  [00:12] Bot: …  /  Buyer: …", height=200,
                           value="[00:00] Bot: Hello, main IndiaMART se bol rahi hoon. Aapko steel pipe ki requirement hai na?\n"
                                 "[00:05] Buyer: Haan ji, 50 piece chahiye\n"
                                 "[00:09] Bot: Theek hai, 500 piece note kar liya. Aapko kaunsa size chahiye?\n"
                                 "[00:14] Buyer: 2 inch\n"
                                 "[00:18] Bot: Aapko kitne piece chahiye?\n"
                                 "[00:21] Buyer: Bataya na 50 piece!")
        if st.button("✅ Check this call", type="primary") and txt.strip():
            from grade_calls import parse_pasted
            turns, has_audio = parse_pasted(txt), False
    else:
        up = st.file_uploader("Call recording (.mp3 / .wav)", type=["mp3", "wav"])
        if st.button("🎧 Transcribe & check", type="primary", disabled=up is None) and up is not None:
            if not os.environ.get("SARVAM_API_KEY"):
                st.error("Add the Sarvam key in the settings below first.")
            else:
                with st.spinner("Turning the recording into text…"):
                    try:
                        from sarvamai import SarvamAI
                        from grade_calls import load_turns
                        tmp = tempfile.mkdtemp()
                        fpath = os.path.join(tmp, up.name)
                        with open(fpath, "wb") as f:
                            f.write(up.getbuffer())
                        job = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"]).speech_to_text_job.create_job(
                            model="saaras:v4", mode="codemix", language_code="hi-IN", with_diarization=True,
                            with_timestamps=True, num_speakers=2)
                        job.upload_files(file_paths=[fpath], timeout=180)
                        job.start()
                        job.wait_until_complete(poll_interval=3, timeout=600)
                        job.download_outputs(output_dir=tmp)
                        turns, key = load_turns(os.path.join(tmp, up.name + ".json")), os.path.splitext(up.name)[0]
                    except Exception as e:
                        st.error(f"Could not transcribe: {str(e)[:300]}")
    if turns:
        if not os.environ.get("LLM_PROVIDER"):
            st.error("Choose the AI and paste its key in the settings below first.")
        else:
            with st.spinner("The AI auditor is checking the call…"):
                try:
                    from grade_calls import grade_turns
                    t0 = time.time()
                    res = grade_turns(key, turns, build_system_prompt(), out_dir=os.path.join(HERE, "checked_calls"),
                                      has_audio=has_audio)
                    st.success(f"Checked in {time.time() - t0:.0f} seconds")
                    call_story(res)
                except Exception as e:
                    st.error(f"Could not check the call: {str(e)[:300]}")

    st.divider()
    st.header("⚙️ Settings")
    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**Which calls to show in the dashboard**")
        ds = st.radio("Calls", ["Audited sample calls (with auditor verdicts)", "Unaudited sample calls"],
                      index=0 if audited else 1, label_visibility="collapsed")
        new_ds = "audited" if ds.startswith("Audited") else "provided"
        if new_ds != st.session_state.dataset:
            st.session_state.dataset = new_ds
            st.rerun()
        if st.button("🔄 Reload data (after running a script)"):
            st.cache_data.clear()
            st.rerun()
        ulog = os.path.join(HERE, "usage_log.csv")
        if os.path.exists(ulog):
            try:
                u = pd.read_csv(ulog)
                st.metric("AI spend so far (estimate)", f"${u.est_usd.sum():.2f}")
                st.caption(f"{int(u.calls.sum())} AI calls · check the provider console for the exact bill")
            except Exception:
                pass
    with s2:
        st.markdown("**AI keys for the live check** (kept in memory for this session only)")
        prov = st.selectbox("AI provider", ["anthropic", "openai", "gemini", "sarvam", "mock"],
                            index=["anthropic", "openai", "gemini", "sarvam", "mock"].index(os.environ.get("LLM_PROVIDER", "anthropic"))
                            if os.environ.get("LLM_PROVIDER", "anthropic") in ["anthropic", "openai", "gemini", "sarvam", "mock"] else 0)
        os.environ["LLM_PROVIDER"] = prov
        k = st.text_input("AI API key", type="password")
        if k:
            os.environ["LLM_API_KEY"] = k
        m_ = st.text_input("AI model (optional)", placeholder="default: claude-sonnet-5-5")
        if m_:
            os.environ["LLM_MODEL"] = m_
        ws = st.text_input("Anthropic workspace ID (only if needed)", placeholder="saved in anthropic_workspace_id.txt")
        if ws:
            os.environ["ANTHROPIC_WORKSPACE_ID"] = ws.strip()
        sk = st.text_input("Sarvam API key (for uploading recordings)", type="password")
        if sk:
            os.environ["SARVAM_API_KEY"] = sk
        st.caption(f"AI key set: {'yes' if os.environ.get('LLM_API_KEY') else 'no'} · "
                   f"Sarvam key set: {'yes' if os.environ.get('SARVAM_API_KEY') else 'no'}")
