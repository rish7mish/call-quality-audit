"""
The audit checklist, written so an AI can apply it.

Source: the auditors' "Call Quality Matrix" (VANI) plus how auditors graded the sample
audit sheet shared with the problem statement. Thresholds that the matrix left
vague are fixed here and documented, so the team can defend them to the jury.

Key fact learned from the sample audit sheet: the human OVERALL grade equals the WORST
grade of any single check in 97% of calls. We use the same rule in code.
"""

# Each check:
#   id          short name used in code and output
#   name        display name
#   human_col   column in the sample audit sheet holding the human grade
#   from_call   True  -> can be judged from the conversation itself
#               False -> needs data we don't have (BL dashboard, MCAT mapping, seller list).
#                        The AI must return "NA" for these; we report them as not assessable.
#   rule        what Fatal / Non-Fatal / Pass mean (our resolved version of the matrix)
#   cause_hint  which root-cause type it usually falls under
CHECKS = [
    dict(id="outcome", name="Outcome accuracy (buyer intent)", human_col="Outcome Accuracy  (Intent)", from_call=True,
         cause_hint="flow_logic",
         rule="""Did the call produce a genuine, confirmed buying requirement?
Auditors grade the LEAD that gets created, not the bot's politeness: a lead is created whenever the call ends.
FATAL: the buyer never confirmed the requirement AND never gave any quantity, spec or product detail - e.g. the call
was on hold or silent, the buyer only said 'haan'/'hello'/'huh'/'ek minute', or disconnected early - WHATEVER the bot
did; OR the buyer clearly wants a job, or is selling, not buying. (This is ALWAYS fatal in the matrix.)
Use the BUYER WORD COUNT given with the transcript: very few buyer words almost always means Fatal here.
NON-FATAL: genuine edge case where intent is ambiguous.
PASS: the buyer confirmed, or answered quantity/spec questions. Asking for a specific seller is NORMAL - the bot only
exists because that seller did not pick up - so it is Pass (raise the human_request risk flag instead)."""),

    dict(id="qty_value", name="Quantity accuracy (number)", human_col="Quantity Accuracy (Numeric)", from_call=True,
         cause_hint="asr_stt",
         rule="""Compare the quantity the BUYER said with the quantity the BOT confirmed / read back / captured.
FATAL: bot's number is materially different (300 -> 600, 500 -> 5, one -> 11), or the bot assumed/filled a quantity the
buyer never said, or took a spec value (e.g. length) as the quantity.
NON-FATAL: small difference; buyer gave a range and bot took the lower value (should take the higher);
'paanch-das' captured as 5.
PASS: same quantity. NA: quantity never came up."""),

    dict(id="qty_unit", name="Quantity unit accuracy", human_col="Quantity Unit Accuracy", from_call=True,
         cause_hint="asr_stt",
         rule="""Compare the UNIT the buyer used with the unit the bot confirmed (piece, kg, tonne, box, crate, meter, litre...).
FATAL: unit changes the meaning of the order (crate -> piece, tonne -> kg, meter -> piece).
NON-FATAL: similar-value units (packet vs pack, nos vs piece).
PASS: same unit. NA: quantity never came up."""),

    dict(id="qty_probing", name="Quantity probing error", human_col="Quantity Probing Error", from_call=True,
         cause_hint="prompt",
         rule="""FATAL: the bot never asked for quantity but still stated/assumed one ('aapko 4 piece chahiye'). Otherwise NA.
(Do NOT flag calls that end with a transfer to a seller - the seller handles quantity.) (The matrix's non-fatal case - 'quantity probed although not defined for the category' - needs category
data we don't have, so do NOT grade it; use NA.)"""),

    dict(id="qty_missed", name="Quantity missed opportunity", human_col="Quantity Missed Opportunity (Capture)", from_call=True,
         cause_hint="flow_logic",
         rule="""Buyer clearly shared a quantity but the bot did not capture/confirm it and moved on, or kept looping and never got it.
FATAL: quantity clearly said and lost. NON-FATAL: the buyer's voice/answer was unclear. NA: no such situation."""),

    dict(id="spec1", name="Spec 1 accuracy", human_col="Spec1  Accuracy", from_call=True,
         cause_hint="asr_stt",
         rule="""First product specification the bot asked about (brand, type, material, size, grade...).
Compare the buyer's answer with what the bot confirmed/captured.
FATAL: a value the buyer CLEARLY stated was captured differently - any changed number or unit counts
(8 feet -> 8 inch, brand 'Dubai Kunafa' -> 'Dubai Kona'), or the bot invented a value the buyer never said.
NON-FATAL: a clear minor difference in a number (3.6 -> 3), or an ambiguous answer (300 mm / 6 inch) captured
without clarifying.
PASS: correct; OR the buyer's answer was unclear, garbled or not one of the offered options and the bot picked the
nearest option ('above three hundred' -> 500 Mbps) - auditors do not count that; OR the buyer was vague and the bot
kept it vague. Do not flag spelling/transcription differences. NA: no spec asked."""),

    dict(id="spec2", name="Spec 2 accuracy", human_col="Spec2  Accuracy", from_call=True,
         cause_hint="asr_stt",
         rule="Same as Spec 1, for the SECOND specification the bot asked about. NA if there was no second spec."),

    dict(id="spec_missed", name="Spec missed opportunity", human_col="Spec Missed Opportunity", from_call=True,
         cause_hint="prompt",
         rule="""Buyer volunteered a spec value (diameter, tea type, floors...) that the bot ignored, or the bot asked only one spec and
skipped the others, or the bot stopped probing specs too early.
FATAL: spec 1 or spec 2 information given by the buyer was lost.
NON-FATAL: only a 3rd spec lost, or the buyer gave several values (8, 12 and 25 mm) and the bot kept only some.
NA: no such situation."""),

    dict(id="addl_details", name="Additional details accuracy", human_col="Additional Details Accuracy", from_call=True,
         cause_hint="prompt",
         rule="""Extra details the buyer shared beyond qty/specs (usage, delivery place, design, budget).
FATAL: the bot recorded something grossly wrong or irrelevant that would mislead a seller.
NON-FATAL: duplicate or very generic details. NA: no extra details shared."""),

    dict(id="looping", name="Looping behaviour", human_col="Looping  Behavior", from_call=True,
         cause_hint="prompt",
         rule="""The bot repeats the same question/statement.
FATAL: repetition irritates the buyer, makes them disconnect, or loses qty/spec (e.g. same spec asked 5 times, bot restarts
the flow after all details were given, buyer says 'connect karo' 3 times and bot keeps asking 'kya aap call par hain').
NON-FATAL: the identical statement said twice in a row; or the buyer had JUST given a clear answer and the bot
immediately asks the same question again; or the buyer complains 'bataya na' / 'already told you'.
PASS: re-asking because the answer was unclear, garbled, off-option or missing; re-confirming or summarising the
requirement; or asking about something again much later in the call - none of these is looping."""),

    dict(id="stt", name="Mishearing (WER/STT)", human_col="WER/STT", from_call=True,
         cause_hint="asr_stt",
         rule="""The bot misheard the buyer's words (visible when the bot's reply/read-back does not match what the buyer said,
or the bot answers something unrelated, e.g. buyer says 'Ceramic' and bot says 'main intezar kar raha hoon').
Only count it when the BOT's own reply/read-back shows it heard something different from what the buyer meant.
Garbled or odd words in the BUYER's lines come from OUR transcription of the recording - never count those.
FATAL: mishearing changed the captured lead (quantity/product/spec) or derailed the call.
NON-FATAL: the bot read back a clearly wrong word (product name variant) with no major impact. PASS: otherwise."""),

    dict(id="dead_air", name="Dead air", human_col="Dead air", from_call=True,
         cause_hint="flow_logic",
         rule="""Silence of more than 5 seconds where the BOT should have spoken (8 seconds if there was background noise).
You are given the measured silences that start right after the BUYER spoke (the bot's turn), excluding the first
10 seconds of the call. Waiting on hold while the bot transfers the call to a seller ('line par bane rahein') is NOT dead air.
FATAL: the bot went silent and the buyer HUNG UP because of it (the call ends after the silence).
NON-FATAL: bot dead air happened (even if the buyer said 'hello?') but the call continued.
PASS: no bot dead air over the threshold."""),

    dict(id="pronunciation", name="Pronunciation / language", human_col="Pronunciation", from_call=True,
         cause_hint="tts_voice",
         rule="""Judged only where the transcript shows it: the buyer clearly speaks English (or another language) and the bot keeps
replying in Hindi -> FATAL. Bot oddly switching language mid-call or mangling a product word -> NON-FATAL.
Otherwise PASS. Odd spellings in the BOT's lines come from our transcription of its voice - never grade those."""),

    dict(id="product_change", name="Product change / no product", human_col="Product Change/ No Product Accuracy", from_call=True,
         cause_hint="flow_logic",
         rule="""The bot opens with a product. If the buyer says they want a DIFFERENT product (bot says rice, buyer wants eggs),
did the bot switch correctly to the buyer's product?
FATAL: wrong product carried forward / approved. NON-FATAL: switched, but the product name is slightly off.
PASS: switched correctly. NA: buyer wanted the product offered."""),

    dict(id="isq", name="Category spec questions (ISQ)", human_col="Category ISQ's Error", from_call=True,
         cause_hint="knowledge",
         rule="""The spec questions/options the bot offered contradict each other or don't fit the product
(asks 'breed' options for eggs that are chicken breeds mixed with duck breeds, offers sizes that don't exist).
FATAL: contradictory questions that clearly confuse the buyer. NON-FATAL: the buyer is visibly confused by an option.
PASS: otherwise (if the questions belong to a DIFFERENT product altogether, grade that under mcat, not here)."""),

    dict(id="mcat", name="MCAT / search category", human_col="MCAT/ Search errors", from_call=True,
         cause_hint="data_mapping",
         rule="""The category the lead is filed under is not in the call, EXCEPT when the bot's spec questions/options clearly
belong to a different product than the buyer wants (e.g. oil grades and litre packs for sugar) - that means the lead
is mapped to the wrong category.
FATAL: spec questions clearly from a different product category. NA: otherwise (can't be judged from the call)."""),

    dict(id="astbuy", name="On-call seller transfer (AstBuy)", human_col="OnCall AstBuy Error (Transferred)", from_call=False,
         cause_hint="flow_logic",
         rule="Needs seller availability data. Always NA. (If the buyer asked to be connected and was not, report it as a risk flag instead.)"),
]

CHECK_IDS = [c["id"] for c in CHECKS]
GRADES = ["Pass", "Non-Fatal", "Fatal", "NA"]
SEVERITY = {"NA": 0, "Pass": 0, "Non-Fatal": 1, "Fatal": 2}

CAUSE_TYPES = {
    "prompt": "the bot's instructions are missing or wrong for this situation",
    "asr_stt": "speech recognition misheard the buyer",
    "knowledge": "the bot lacks product/category knowledge",
    "flow_logic": "call flow/logic problem (turn-taking, transfer, confirmation, ending)",
    "tts_voice": "voice output problem (pronunciation, language)",
    "data_mapping": "category/data mapping outside the call",
}

RISK_FLAGS = {
    "wrong_requirement": "bot captured something different from what the buyer wanted",
    "frustration": "buyer sounds annoyed, repeats themselves, or complains",
    "loop": "bot repeats itself or the conversation goes in circles",
    "low_confidence": "transcript is garbled/unclear at a key moment (product, quantity, spec)",
    "human_request": "buyer asks to speak to a person/seller",
}


def overall_grade(grades: dict) -> str:
    """Human rule: overall = worst single check. NA counts as Pass."""
    worst = max((SEVERITY.get(g, 0) for g in grades.values()), default=0)
    return {0: "Pass", 1: "Non-Fatal", 2: "Fatal"}[worst]


def build_system_prompt() -> str:
    lines = [
        "You are a senior call-quality auditor for an AI voice bot (VANI) that calls BUYERS on IndiaMART, a B2B marketplace.",
        "The bot confirms the buyer's requirement (product, quantity + unit, 2-3 product specifications, extra details),",
        "then creates a Buy Lead (BL) for sellers and may transfer the call to a live seller.",
        "Calls are in Hindi, English and Hinglish. The transcript was produced by speech-to-text, so it may itself contain errors;",
        "judge the BOT's behaviour, and do not blame the bot for an obvious transcription glitch in the BUYER's lines.",
        "",
        "Grade EVERY check below as one of: Pass, Non-Fatal, Fatal, NA. Use NA only where the rule says so or the situation never arose.",
        "Grade like the human auditors: they only write up CLEAR, MATERIAL problems. Around 70% of calls are Pass overall.",
        "When in doubt, grade Pass. Minor wording, a single re-ask, or transcription noise is NOT a problem.",
        "For every Non-Fatal or Fatal you MUST quote the exact transcript line(s) with timestamps as evidence.",
        "",
        "CHECKS:",
    ]
    for c in CHECKS:
        lines.append(f"\n[{c['id']}] {c['name']}\n{c['rule']}")
    lines += [
        "",
        "For each Non-Fatal/Fatal also give cause_type, one of: " + ", ".join(f"{k} ({v})" for k, v in CAUSE_TYPES.items()),
        "and root_cause: ONE short, specific, reusable sentence about WHY it happened, written so similar failures in other calls",
        "would get the same sentence (e.g. 'Bot re-asks a spec after the buyer already answered it', not call-specific details).",
        "",
        "RISK FLAGS (true/false): " + "; ".join(f"{k} = {v}" for k, v in RISK_FLAGS.items()),
        "",
        "Reply with ONLY a JSON object, no other text. Keep it SHORT:",
        "- For a check graded Pass or NA, give ONLY the grade string, e.g. \"looping\": \"Pass\".",
        "- For Non-Fatal / Fatal give an object; evidence = the key quote(s) with timestamp, max ~120 characters;",
        "  reason max 20 words. Do not repeat the transcript. Use straight double quotes only for JSON syntax;",
        "  inside text use single quotes.",
        "Shape:",
        '{"bot_speaker": "S0", "summary": "<max 25 words: what the buyer wanted and what happened>",',
        ' "checks": {"outcome": "Pass", "qty_value": {"grade": "Fatal", "evidence": "[00:15] Buyer: 50 piece / [00:31] Bot: 500 piece",',
        '            "reason": "bot saved 500, buyer said 50", "cause_type": "asr_stt", "root_cause": "<one reusable sentence>"},',
        '            ...every check id...},',
        ' "risk_flags": {"wrong_requirement": false, "frustration": false, "loop": false, "low_confidence": false, "human_request": false},',
        ' "risk_reason": "<short, empty if no flags>"}',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- how each rule was created (shown in the app)
# Groups: A = copied from the auditors' matrix, B = confirmed with the sample audit sheet,
#         C = clarified from the auditors' notes (our interpretation), D = measured by code, not judged by the AI,
#         E = set aside: can't be judged from the call, F = required by the problem statement.
RULE_GROUPS = {
    "A": ("Copied from the auditors' rulebook", "Where the auditors' matrix was already clear, we used it as written."),
    "B": ("Confirmed with sample grading data", "Checked against the sample audit sheet (calls the auditors already graded)."),
    "C": ("Clarified from the auditors' notes", "The matrix was vague, so we read the auditors' written notes to see where they draw the line. Our interpretation - the most likely place for mistakes."),
    "D": ("Measured by the computer", "Measured exactly from timestamps instead of asking the AI's opinion."),
    "E": ("Set aside - not visible in the call", "Needs dashboard data the conversation doesn't contain, so marked 'not assessable' instead of guessing."),
    "F": ("Required by the problem statement", "Evidence, risk flags, cause types and a transparent priority score are asked for in PS01."),
}
RULE_ORIGIN = {
    "outcome":        ("ABC", "Matrix says always Fatal; the sample audit sheet agrees (almost always Fatal). v4: Fatal when the buyer never confirmed and gave no detail, whatever the bot did ('on hold, then disconnected, lead approved'); the code counts the buyer's words as a hard signal. Asking for a specific seller is normal (auditors Pass it)."),
    "qty_value":      ("AC", "Matrix: a small difference is OK. Notes: '300 captured as 600' was Fatal; '10-15 box, captured 10' was Non-Fatal."),
    "qty_unit":       ("AC", "Matrix: similar units are OK. Clarified: a unit that changes the order (crate -> piece) is Fatal."),
    "qty_probing":    ("CE", "Notes: bot assumed a quantity it never asked = Fatal. v3 also flagged 'qty never asked' but it fired on calls handed to a seller, so v4 reverted it. 'Asked when not needed' needs category data, so set aside."),
    "qty_missed":     ("AC", "Matrix: Fatal. Notes: Non-Fatal only when the buyer's voice was unclear."),
    "spec1":          ("AC", "Notes: a clearly stated value changed (8 feet -> 8 inch) or invented = Fatal; '3.6 captured as 3' = Non-Fatal. v3: picking the nearest option for an unclear answer is not an error."),
    "spec2":          ("AC", "Same rule as Spec 1, for the second spec."),
    "spec_missed":    ("AC", "Matrix: spec 1 or 2 lost = Fatal; only spec 3 lost = Non-Fatal. Notes: several sizes given, only one kept = Non-Fatal."),
    "addl_details":   ("A",  "Matrix: grossly wrong details = Fatal; generic or duplicate = Non-Fatal."),
    "looping":        ("AC", "Matrix says 'probing more than 1+2 times' (vague). Notes: Fatal only when it irritated the buyer or lost information; Non-Fatal when 'probed even with clear input'. Re-asking after an unclear answer, re-confirming, or asking again much later is normal."),
    "stt":            ("AC", "Matrix: Fatal if it hurts the lead. Notes: '500 heard as 5' Fatal; a misheard product name Non-Fatal. v2: only when the bot's reply shows it - garbled buyer lines are our own transcription."),
    "dead_air":       ("ADC", "Matrix: over 5s (8s with noise). The computer measures only gaps after the buyer spoke, skipping the first 10s. Gaps over 7s count (auditors did not flag ~6s gaps). Fatal only when the buyer hung up because of it; transfer hold is not dead air."),
    "pronunciation":  ("C",  "A transcript can't capture sound, so we only judge the wrong language (buyer speaks English, bot stays in Hindi)."),
    "product_change": ("AC", "Matrix: wrong product approved = Fatal. Notes example: bot offered rice, buyer wanted eggs."),
    "isq":            ("A",  "Matrix: contradicting or confusing spec questions."),
    "mcat":           ("CE", "Needs the dashboard's category mapping - except when the bot asks questions from a different product (seen in auditor notes: sugar call asked oil questions -> 'wrongly mapped'). Otherwise not assessable."),
    "astbuy":         ("E",  "Needs seller availability - not in the call. 'Buyer asked for a person' is raised as a risk flag instead."),
}
OVERALL_ORIGIN = ("B", "Overall = the worst single check. The auditors' own verdicts in the sample audit sheet follow this rule 97% of the time.")
SOURCES = [
    ("Call Quality Matrix (image)", "The auditors' rulebook: the 17 checks and their Fatal / Non-Fatal wording."),
    ("Sample audit sheet", "Sample calls graded by the auditors: grades per check, their written notes, and the overall verdict."),
    ("PS01 problem statement", "The problem statement: evidence for every grade, risk flags, cause types, transparent priority."),
    ("Sarvam transcripts of the sample calls", "Timestamps and speaker turns, so silences can be measured by code."),
]


def rules_table():
    """One row per check, for the app and the downloadable rules file."""
    import re
    rows = []
    for c in CHECKS:
        parts = {"FATAL": "", "NON-FATAL": "", "PASS": "", "NA": ""}
        text = c["rule"]
        first = re.split(r"\b(FATAL|NON-FATAL|PASS|NA):", text, maxsplit=1)[0].strip()
        for m in re.finditer(r"\b(NON-FATAL|FATAL|PASS|NA):\s*(.*?)(?=\b(?:NON-FATAL|FATAL|PASS|NA):|$)", text, re.S):
            parts[m.group(1)] = " ".join(m.group(2).split())
        groups, why = RULE_ORIGIN.get(c["id"], ("", ""))
        rows.append({"id": c["id"], "check": c["name"], "what_it_checks": " ".join(first.split()),
                     "fatal_when": parts["FATAL"], "non_fatal_when": parts["NON-FATAL"], "pass_when": parts["PASS"],
                     "na_when": parts["NA"], "judged_from_call": "yes" if c["from_call"] else "no - not assessable",
                     "how_created": " + ".join(RULE_GROUPS[g][0] for g in groups), "group_codes": groups,
                     "reasoning": why, "human_column": c["human_col"], "rules_version": RULES_VERSION})
    return rows


RULES_VERSION = "v4 (2026-10-10)"
RULES_CHANGELOG = [
    ("v1 (2026-10-09)", "First version: auditors' matrix + overall rule confirmed on the sample audit sheet + clarifications from auditor notes.", ""),
    ("v2 (2026-10-10)", "Calibrated after the first 11 tune calls (36% agreement): the AI flagged far more than auditors do.",
     "Global 'only clear, material problems'; dead air only after buyer turns, not first 10s or transfer hold; mishearing only "
     "when the bot's reply shows it; one re-ask is not looping; spec/pronunciation/ISQ tightened; outcome Fatal when no clear "
     "confirmation; MCAT Fatal when spec questions belong to another product."),
    ("v3 (2026-10-10)", "31 tune calls: 48% agreement. v2 over-corrected in places and missed patterns auditors care about.",
     "Asking for a specific seller is normal (Pass); picking the nearest option for an unclear answer is not an error; any "
     "changed number/unit in a clearly stated spec is Fatal; several values given but only some kept = spec missed; "
     "looping only after a clear answer; outcome Fatal only when no requirement at all; quantity never asked + lead closed "
     "= Fatal (matrix rule); dead air counted from 7s, Fatal only if the buyer hung up."),
    ("v4 (2026-10-10)", "v3 kept 48% but Fatal recall fell to 36%: outcome missed 'never confirmed' calls, the new "
     "quantity rule fired on seller transfers, looping still over-flagged.",
     "Outcome Fatal when the buyer never confirmed AND gave no detail, whatever the bot did (+ buyer word count from code); "
     "quantity-never-asked rule reverted; looping only for an immediate re-ask after a clear answer or a buyer complaint. "
     "Rules frozen after this version; holdout graded once."),
]
