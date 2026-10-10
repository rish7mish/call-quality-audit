"""
One small function, ask_llm(), that works with whichever AI the team has a key for.
Uses only Python's standard library - nothing extra to install.

Set these before running (PowerShell):
    $env:LLM_PROVIDER = "anthropic"   # or: openai, gemini, sarvam, openai_compatible, mock
    $env:LLM_API_KEY  = "your-key"
    $env:LLM_MODEL    = ""            # optional - leave empty for the default below
    $env:LLM_BASE_URL = ""            # only for openai_compatible (e.g. Groq, Azure, local server)
    $env:ANTHROPIC_WORKSPACE_ID = ""  # only if Anthropic says the key "is not scoped to a workspace" (wrkspc_...)
"""
import atexit
import json
import os
import random
import threading
import re
import time
import urllib.error
import urllib.request

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",   # cheaper: claude-haiku-5-5
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-2.5-flash",
    "sarvam": "sarvam-m",
    "openai_compatible": "",
    "mock": "mock",
}


# ---- token usage + rough cost (printed when the script ends, and appended to usage_log.csv)
USAGE = {"calls": 0, "input": 0, "output": 0}
_LOCK = threading.Lock()
# USD per million tokens (input, output). Rough list prices - check your provider console for the real bill.
PRICES = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (5.0, 25.0), "gpt-4.1-mini": (0.4, 1.6),
          "gemini-2.5-flash": (0.3, 2.5)}


BY_MODEL = {}
LAST_META = {}  # stop_reason / block types of the most recent Anthropic reply (for debugging)


def _add_usage(inp, out, model=None):
    with _LOCK:
        USAGE["calls"] += 1
        USAGE["input"] += int(inp or 0)
        USAGE["output"] += int(out or 0)
        m = (model or model_name()).lower()
        a = BY_MODEL.setdefault(m, [0, 0])
        a[0] += int(inp or 0)
        a[1] += int(out or 0)


def estimated_cost():
    total = 0.0
    for m, (i, o) in (BY_MODEL.items() or [(model_name().lower(), (USAGE["input"], USAGE["output"]))]):
        pin, pout = next((v for k, v in PRICES.items() if k in m), (3.0, 15.0))
        total += i / 1e6 * pin + o / 1e6 * pout
    return total


@atexit.register
def _report():
    if USAGE["calls"] and provider() != "mock":
        cost = estimated_cost()
        print(f"\n[AI usage] {USAGE['calls']} calls, {USAGE['input']:,} input + {USAGE['output']:,} output tokens "
              f"~ ${cost:.2f} ({model_name()}, rough estimate)")
        try:
            log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_log.csv")
            new = not os.path.exists(log)
            with open(log, "a", encoding="utf-8") as f:
                if new:
                    f.write("time,script,model,calls,input_tokens,output_tokens,est_usd\n")
                import sys as _s
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{os.path.basename(_s.argv[0])},{model_name()},"
                        f"{USAGE['calls']},{USAGE['input']},{USAGE['output']},{cost:.4f}\n")
        except Exception:
            pass


def provider():
    return os.environ.get("LLM_PROVIDER", "").strip().lower()


def model_name():
    return os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODELS.get(provider(), "")


def _post(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _call(system, user, max_tokens, model=None):
    p, key, m = provider(), os.environ.get("LLM_API_KEY", ""), (model or model_name())
    if p == "mock":
        return _mock(user)
    if not key:
        raise RuntimeError("LLM_API_KEY is not set")
    if p == "anthropic":
        hdr = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
        if not ws:  # fall back to the ID saved in this folder
            wf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anthropic_workspace_id.txt")
            if os.path.exists(wf):
                with open(wf, encoding="utf-8") as f:
                    ws = f.read().strip()
        if ws:  # needed for personal / multi-workspace keys (Console > Settings > Workspaces, starts with wrkspc_)
            hdr["anthropic-workspace-id"] = ws
        r = _post("https://api.anthropic.com/v1/messages", hdr,
                  {"model": m, "max_tokens": max_tokens, "system": system,  # newer Claude models reject 'temperature'
                   "messages": [{"role": "user", "content": user}]})
        u = r.get("usage", {})
        _add_usage(u.get("input_tokens"), u.get("output_tokens"), m)
        LAST_META["stop_reason"] = r.get("stop_reason")
        LAST_META["block_types"] = [b.get("type") for b in r.get("content", [])]
        return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type", "text") == "text")
    if p == "gemini":
        r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}", {},
                  {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens,
                                        "responseMimeType": "application/json"}})
        u = r.get("usageMetadata", {})
        _add_usage(u.get("promptTokenCount"), u.get("candidatesTokenCount"), m)
        return "".join(p_.get("text", "") for p_ in r["candidates"][0]["content"]["parts"])
    # OpenAI-style chat completions: openai, sarvam, openai_compatible
    if p == "openai":
        url, headers = "https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {key}"}
    elif p == "sarvam":
        url, headers = "https://api.sarvam.ai/v1/chat/completions", {"api-subscription-key": key,
                                                                      "Authorization": f"Bearer {key}"}
    elif p == "openai_compatible":
        base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
        if not base:
            raise RuntimeError("LLM_BASE_URL is not set")
        url, headers = f"{base}/chat/completions", {"Authorization": f"Bearer {key}"}
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER '{p}'. Use anthropic, openai, gemini, sarvam, openai_compatible or mock.")
    body = {"model": m, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if p == "openai":
        body["response_format"] = {"type": "json_object"}
    r = _post(url, headers, body)
    u = r.get("usage", {}) or {}
    _add_usage(u.get("prompt_tokens"), u.get("completion_tokens"), m)
    return r["choices"][0]["message"]["content"]


def ask_llm(system, user, max_tokens=4000, retries=4, model=None):
    """Returns (text, seconds). Retries on rate limits / server errors. model= overrides LLM_MODEL for this call."""
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            return _call(system, user, max_tokens, model), round(time.time() - t0, 1)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            raise RuntimeError(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(5 * 2 ** attempt)
                continue
            raise RuntimeError(f"Network error: {e}")


def parse_json(text):
    """Pull the JSON object out of a model reply (handles ```json fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start:end + 1])


def _mock(user):
    """Fake answer for testing the pipeline without any API key."""
    from rubric import CHECKS
    rnd = random.Random(hash(user) % 10_000)
    checks = {}
    for c in CHECKS:
        g = "NA" if not c["from_call"] else rnd.choices(["Pass", "Non-Fatal", "Fatal", "NA"], [80, 8, 4, 8])[0]
        bad = g in ("Fatal", "Non-Fatal")
        checks[c["id"]] = {"grade": g, "evidence": "[00:10] Bot: (mock evidence)" if bad else "",
                           "reason": "mock" if bad else "", "cause_type": c["cause_hint"] if bad else "",
                           "root_cause": f"Mock root cause for {c['id']}" if bad else ""}
    return json.dumps({"bot_speaker": "S0", "summary": "mock summary", "checks": checks,
                       "risk_flags": {k: rnd.random() < 0.1 for k in
                                      ["wrong_requirement", "frustration", "loop", "low_confidence", "human_request"]},
                       "risk_reason": "mock"})
