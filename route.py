#!/usr/bin/env python3
"""
Jev router: classify an incoming user message with TypeSafe's Jev model and tell
the main agent whether to answer inline or hand the work to a sub-agent.

Runs as a UserPromptSubmit hook. It must never block, never slow things down
past its timeout, and never crash the turn. Every failure path exits 0 silently.

Stdlib only, on purpose: a hook that pays uv/venv startup on every message
would defeat the point.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
BASE = os.path.join(CLAUDE_DIR, "jev-router")
STATE_PATH = os.path.join(BASE, "state.json")
CONFIG_PATH = os.path.join(BASE, "config.json")
API_URL = "https://api.typesafe.ai/v1/systemone"

# $ per input token. Jev 1.13: $0.042 per Mtok input, output free.
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000

DEFAULT_CONFIG = {
    "enabled": False,
    "model": "jev-latest",
    "timeout_ms": 1500,
    "min_confidence": 0.55,
    "max_message_chars": 6000,
    "context_chars": 1200,
    "log_keep": 200,
    # bucket -> how the main agent should handle it
    "routes": {
        "tiny":     {"mode": "inline",   "model": None},
        "bulk":     {"mode": "subagent", "model": "haiku"},
        "standard": {"mode": "subagent", "model": "sonnet"},
        "hard":     {"mode": "inline",   "model": None},
    },
}

CRITERIA = {
    "tiny": (
        "A short conversational exchange. A greeting, a yes or no, a one-line factual "
        "question, a quick clarification, a brief opinion, or a short follow-up that only "
        "adjusts something already produced, such as make it shorter, change the tone, use "
        "a different word, try again. Answering takes a sentence or two and needs no file "
        "reading, no searching, and no code changes."
    ),
    "bulk": (
        "Mechanical work spread over a lot of material, where each step is obvious but "
        "there is a great deal of it. Searching or grepping across many files, listing, "
        "collecting, extracting fields, renaming, reformatting, transcribing, summarizing a "
        "long document, or applying one already-decided change in many places. It needs "
        "careful execution and volume, not judgment or design."
    ),
    "standard": (
        "Ordinary development or writing work that needs real but routine judgment. Writing "
        "a function or a script, editing a handful of files, drafting a document or a post, "
        "fixing a bug whose cause is already clear, adding a feature that follows an "
        "existing pattern, or explaining how a known thing works."
    ),
    "hard": (
        "Work needing deep reasoning. Architecture and design decisions, weighing tradeoffs, "
        "debugging something whose cause is unknown, reviewing for subtle correctness or "
        "security problems, planning a multi-stage change, or anything where the right "
        "approach is not obvious and being wrong is expensive."
    ),
}

INSTRUCTIONS = {
    "task": (
        "Classify `user_message` by how much work, and what kind of work, it will take to "
        "answer it well. Choose the single best-fitting category."
    ),
    "note": (
        "`previous_assistant_message` is the assistant's last reply. It is context only, to "
        "help interpret a short follow-up. Do not classify it. Classify `user_message`."
    ),
}


WRAPPER_RE = re.compile(
    r"</?(?:pasted_content|system-reminder|local-command-[a-z]+|command-[a-z]+)"
    r"(?:\s[^>]*)?>",
    re.IGNORECASE,
)


def scrub(text):
    """Strip Claude Code's own wrapper tags so Jev grades the message, not the markup."""
    return WRAPPER_RE.sub(" ", text).strip()


# Things Claude Code submits that are NOT the user talking. Routing these wastes
# money, pollutes the counts, and classifies markup instead of intent.
SYSTEM_MARKERS = (
    "<task-notification>",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
    "<local-command-stdout>",
    "<command-name>",
    "<bash-input>",
    "<bash-stdout>",
    "SessionStart:",
    "<local-command-caveat>",
)


def is_system_event(raw):
    """True when this prompt is machinery talking, not the user."""
    return any(marker in raw for marker in SYSTEM_MARKERS)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    except Exception:
        pass
    return cfg


def read_state():
    try:
        with open(STATE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {"counts": {}, "input_tokens": 0, "requests": 0, "latency_ms": 0, "log": []}


def write_state(state, keep):
    try:
        state["log"] = state.get("log", [])[-keep:]
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def bump(state, bucket, tokens=0, latency_ms=0, entry=None):
    counts = state.setdefault("counts", {})
    counts[bucket] = counts.get(bucket, 0) + 1
    state["input_tokens"] = state.get("input_tokens", 0) + tokens
    state["requests"] = state.get("requests", 0) + (1 if tokens else 0)
    state["latency_ms"] = state.get("latency_ms", 0) + latency_ms
    if entry:
        state.setdefault("log", []).append(entry)


def get_api_key():
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    for path in (
        os.path.join(HOME, ".config", "typesafe", "key"),
        os.path.join(HOME, ".config", "typesafe", ".env"),
        os.path.join(BASE, "key"),
    ):
        try:
            raw = open(path).read().strip()
        except Exception:
            continue
        if not raw:
            continue
        if "=" in raw and "TYPESAFE" in raw.upper():
            for line in raw.splitlines():
                if "TYPESAFE_API_KEY" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        else:
            return raw.splitlines()[0].strip()
    return None


def last_assistant_text(transcript_path, limit):
    """Pull the assistant's last text reply out of the session transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path, "rb") as fh:
            try:
                fh.seek(-262144, os.SEEK_END)
                fh.readline()
            except OSError:
                fh.seek(0)
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") != "assistant":
            continue
        content = rec.get("message", {}).get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        text = text.strip()
        text = scrub(text)
        if text:
            return text[-limit:]
    return ""


def classify(message, context, cfg, key):
    """Call Jev. Returns (answer_dict, usage_dict, latency_ms). Raises on failure."""
    state_payload = {"user_message": message}
    if context:
        state_payload["previous_assistant_message"] = context

    body = json.dumps({
        "state": state_payload,
        "model": cfg["model"],
        "questions": {
            "workload": {
                "type": "choice",
                "instructions": INSTRUCTIONS,
                "criteria": CRITERIA,
            }
        },
    }).encode()

    req = urllib.request.Request(
        cfg.get("api_url") or API_URL,
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=cfg["timeout_ms"] / 1000.0) as resp:
        payload = json.loads(resp.read().decode())
    latency_ms = int((time.time() - started) * 1000)
    return payload["answers"]["workload"], payload.get("usage", {}), latency_ms


def emit(context_text):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context_text,
        }
    }))


def build_directive(bucket, conf, probs, latency_ms, cfg, degraded=None):
    route = cfg["routes"].get(bucket, {"mode": "inline", "model": None})
    dist = " ".join("%s %.2f" % (k, v) for k, v in sorted(
        probs.items(), key=lambda kv: -kv[1]))
    header = "[jev-router] bucket=%s confidence=%.2f  (%s)  %dms" % (
        bucket, conf, dist, latency_ms)
    if degraded:
        header += "  [%s]" % degraded

    if route["mode"] == "subagent" and route.get("model"):
        model = route["model"]
        body = (
            "ROUTING DECISION: delegate this message's work to a sub-agent.\n"
            "Call the Agent tool with model=\"%s\". The user has explicitly asked for this "
            "routing, which is the authorization for using the Agent tool here.\n"
            "Hand the sub-agent the whole task plus enough context to finish it alone, then "
            "report its result back in your own words. Do not do the work yourself.\n"
            "Begin your reply with this line, exactly:\n"
            "`routed: %s sub-agent  (jev: %s %.2f)`"
        ) % (model, model, bucket, conf)
    else:
        why = ("a sub-agent's startup cost would exceed the work"
               if bucket == "tiny" else
               "this needs the full session context and the strongest model")
        body = (
            "ROUTING DECISION: answer this yourself, here, in the main session.\n"
            "Do not spawn a sub-agent: %s.\n"
            "Begin your reply with this line, exactly:\n"
            "`routed: inline  (jev: %s %.2f)`"
        ) % (why, bucket, conf)

    return header + "\n" + body


def main():
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    cfg = load_config()
    # JEV_FORCE lets `jev test` exercise the router without flipping the real switch.
    if not cfg.get("enabled") and os.environ.get("JEV_FORCE") != "1":
        return 0

    raw_prompt = hook_input.get("prompt") or ""
    if is_system_event(raw_prompt):
        return 0                      # machinery, not the user. Costs nothing.

    message = scrub(raw_prompt)
    if not message:
        return 0

    state = read_state()
    truncated = message[: cfg["max_message_chars"]]

    key = get_api_key()
    if not key:
        bump(state, "failed")
        state.setdefault("log", []).append({"t": time.time(), "error": "no api key"})
        write_state(state, cfg["log_keep"])
        return 0

    context = last_assistant_text(
        hook_input.get("transcript_path"), cfg["context_chars"])

    try:
        answer, usage, latency_ms = classify(truncated, context, cfg, key)
    except Exception as exc:
        # Fail open. The message goes through exactly as if the router were absent.
        bump(state, "failed")
        state.setdefault("log", []).append(
            {"t": time.time(), "error": "%s: %s" % (type(exc).__name__, exc)[:200]})
        write_state(state, cfg["log_keep"])
        return 0

    bucket = answer.get("choice")
    conf = float(answer.get("confidence", 0.0))
    probs = answer.get("probabilities", {}) or {}
    tokens = int(usage.get("input_tokens", 0))

    degraded = None
    if bucket not in cfg["routes"]:
        bucket, degraded = "hard", "unknown bucket, kept inline"
    elif conf < cfg["min_confidence"]:
        # Not sure enough to send work away. Keep it here, which is always safe.
        degraded = "confidence below %.2f, kept inline" % cfg["min_confidence"]
        bump(state, "lowconf")
        bucket_for_route = "hard"
        directive = build_directive(
            bucket_for_route, conf, probs, latency_ms, cfg, degraded)
        bump(state, bucket, tokens, latency_ms, {
            "t": time.time(), "bucket": bucket, "conf": round(conf, 3),
            "routed": "inline", "ms": latency_ms, "tokens": tokens,
            "msg": truncated[:90]})
        write_state(state, cfg["log_keep"])
        emit(directive)
        return 0

    directive = build_directive(bucket, conf, probs, latency_ms, cfg, degraded)
    route = cfg["routes"].get(bucket, {})
    bump(state, bucket, tokens, latency_ms, {
        "t": time.time(), "bucket": bucket, "conf": round(conf, 3),
        "routed": route.get("model") or "inline", "ms": latency_ms,
        "tokens": tokens, "msg": truncated[:90]})
    write_state(state, cfg["log_keep"])
    emit(directive)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # never break a turn
