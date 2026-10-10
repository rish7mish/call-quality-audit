"""
Helpers for the bot's prompt (inputs/bot_prompt.docx, ~160k characters):
load it, split it into sections, pick the sections relevant to a problem, apply edits, make a diff.
"""
import difflib
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROMPT_CANDIDATES = [
    os.path.join(HERE, "inputs", "bot_prompt.docx"),
    os.path.join(HERE, "bot_prompt.docx"),
    os.path.join(HERE, "bot_prompt.txt"),
]
SECTION_LINE = re.compile(r"^[A-Z][A-Z0-9_ &/\-()]{3,60}:?\s*$")  # e.g. 'CONNECTIVITY_ISSUE:' or 'FINALISATION'


def find_prompt(path=None):
    if path:
        return path
    for p in DEFAULT_PROMPT_CANDIDATES:
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(HERE, "..", "**", "*Prompt*VANI*.docx"), recursive=True)
    if hits:
        return hits[0]
    raise FileNotFoundError("Bot prompt not found. Put the bot's prompt in inputs/bot_prompt.docx")


def load_prompt_text(path=None):
    """Return the prompt as plain text; headings are marked with '## ' so sections can be found."""
    path = find_prompt(path)
    if path.lower().endswith(".txt"):
        with open(path, encoding="utf-8") as f:
            return f.read()
    import docx  # pip install python-docx
    d = docx.Document(path)
    out = []
    for p in d.paragraphs:
        t = p.text.rstrip()
        if not t.strip():
            out.append("")
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if style.startswith("heading") or SECTION_LINE.match(t.strip()):
            out.append("## " + t.strip())
        else:
            out.append(t)
    return "\n".join(out)


def split_sections(text):
    sections, title, buf = [], "Global Instructions", []
    for line in text.splitlines():
        if line.startswith("## "):
            if buf:
                sections.append({"title": title, "text": "\n".join(buf).strip()})
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if buf:
        sections.append({"title": title, "text": "\n".join(buf).strip()})
    return sections


def outline(sections):
    return "\n".join(f"- {s['title']}  ({len(s['text'])} chars)" for s in sections)


_WORD = re.compile(r"[a-zA-Zऀ-ॿ]{4,}")
_STOP = set("that this with from have will your their there they what when then than into about which would could "
            "should bot buyer call calls also just like more most only other some such very where while been were".split())


def relevant_sections(sections, query, max_chars=40000, always_first=True):
    q = {w.lower() for w in _WORD.findall(query)} - _STOP
    scored = []
    for i, s in enumerate(sections):
        words = [w.lower() for w in _WORD.findall(s["title"] + " " + s["text"])]
        if not words:
            continue
        hits = sum(1 for w in words if w in q)
        title_hits = sum(3 for w in _WORD.findall(s["title"].lower()) if w in q)
        scored.append(((hits + title_hits) / (len(words) ** 0.5), i))
    scored.sort(reverse=True)
    chosen, total = [], 0
    if always_first and sections:
        chosen.append(0)
        total += min(len(sections[0]["text"]), 6000)
    for _, i in scored:
        if i in chosen:
            continue
        n = len(sections[i]["text"])
        if total + n > max_chars:
            continue
        chosen.append(i)
        total += n
    chosen.sort()
    parts = []
    for i in chosen:
        body = sections[i]["text"] if i != 0 else sections[i]["text"][:6000]
        parts.append(f"## {sections[i]['title']}\n{body}")
    return "\n\n".join(parts), [sections[i]["title"] for i in chosen]


def apply_edits(text, edits):
    """edits: [{action: add|replace|remove, section, old_text, new_text}]. Returns (new_text, report)."""
    report = []
    for e in edits:
        action = (e.get("action") or "add").lower()
        old, new, sec = e.get("old_text") or "", e.get("new_text") or "", e.get("section") or ""
        if action in ("replace", "remove"):
            if old and old in text:
                text = text.replace(old, new if action == "replace" else "", 1)
                report.append({"edit": e, "applied": True, "note": f"{action}d in place"})
                continue
            if action == "remove":
                report.append({"edit": e, "applied": False, "note": "text to remove not found"})
                continue
            action = "add"  # replace target not found -> add the new rule instead
        if not new:
            report.append({"edit": e, "applied": False, "note": "empty new_text"})
            continue
        marker = f"## {sec}".strip()
        pos = text.find(marker) if sec else -1
        if pos >= 0:
            nxt = text.find("\n## ", pos + len(marker))
            nxt = len(text) if nxt < 0 else nxt
            text = text[:nxt].rstrip() + "\n" + new.strip() + "\n" + text[nxt:]
            report.append({"edit": e, "applied": True, "note": f"added at end of section '{sec}'"})
        else:
            if "## Additional Rules (quality fixes)" not in text:
                text = text.rstrip() + "\n\n## Additional Rules (quality fixes)\n"
            text = text.rstrip() + "\n" + new.strip() + "\n"
            report.append({"edit": e, "applied": True, "note": "section not found - added under 'Additional Rules (quality fixes)'"})
    return text, report


def make_diff(old, new, name="bot_prompt"):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=f"{name} (current)", tofile=f"{name} (fixed)", n=2))
