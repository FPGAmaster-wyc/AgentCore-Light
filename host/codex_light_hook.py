import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from codex_light_serial import send_command, send_event


LOG_PATH = (Path(os.environ["AGENTCORE_LIGHT_HOME"]) / "host/codex_light_hook.log"
            if "AGENTCORE_LIGHT_HOME" in os.environ else Path(__file__).with_name("codex_light_hook.log"))
STATE_DB_PATH = Path.home() / ".codex" / "state_5.sqlite"
DEFAULT_TOKEN_BUDGET = 120000


def log(message):
    with LOG_PATH.open("a", encoding="utf-8") as fp:
        fp.write(message + "\n")


def load_event():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def read_budget_tokens():
    raw = os.getenv("CODEX_TOKEN_BUDGET", str(DEFAULT_TOKEN_BUDGET))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TOKEN_BUDGET


def find_thread_id(event):
    for key in ("thread_id", "session_id", "conversation_id"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def query_tokens_used(thread_id):
    if not STATE_DB_PATH.exists():
        return None

    try:
        con = sqlite3.connect(str(STATE_DB_PATH))
        cur = con.cursor()
        if thread_id:
            cur.execute("SELECT tokens_used FROM threads WHERE id = ? LIMIT 1", (thread_id,))
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        cur.execute("SELECT tokens_used FROM threads ORDER BY updated_at_ms DESC LIMIT 1")
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception as exc:
        log(f"token query error: {exc}")
    finally:
        try:
            con.close()
        except Exception:
            pass

    return None


def compute_token_percent(event):
    if os.getenv("CODEX_TOKEN_AUTO_ESTIMATE", "0").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        return None

    for key in ("token_percent", "tokenPercent"):
        value = event.get(key)
        if isinstance(value, int):
            return clamp(value, 0, 100)
        if isinstance(value, str) and value.isdigit():
            return clamp(int(value), 0, 100)

    thread_id = find_thread_id(event)
    used = query_tokens_used(thread_id)
    if used is None:
        return None

    budget = read_budget_tokens()
    percent = int(round(100 - (used * 100.0 / budget)))
    return clamp(percent, 0, 100)


def command_for_event(event):
    event_name = event.get("hook_event_name", "")
    tool_name = event.get("tool_name", "")

    if event_name == "SessionStart":
        return "IDLE"

    if event_name == "UserPromptSubmit":
        return "THINKING"

    if event_name == "PreToolUse":
        if tool_name == "apply_patch":
            return "WRITING"
        return "RUNNING"

    if event_name == "PostToolUse":
        response = event.get("tool_response")
        # Output text can contain source code or quoted errors, even on success.
        # Some Codex tools return text only; do not infer failure from that text.
        if isinstance(response, dict):
            exit_code = response.get("exit_code")
            if response.get("isError") is True or (type(exit_code) is int and exit_code != 0):
                return "ERROR"
        return "THINKING"

    if event_name == "PermissionRequest":
        return "NEED_CONFIRM"

    if event_name == "Stop":
        return "DONE"

    if event_name in ("Interrupt", "SessionEnd"):
        return "IDLE"

    if event_name in ("PreCompact", "PostCompact"):
        return "THINKING"

    return None


def main():
    event = load_event()
    command = command_for_event(event)
    event_name = event.get("hook_event_name", "unknown")
    tool_name = event.get("tool_name", "")

    log(json.dumps({"at": datetime.now().astimezone().isoformat(), "event": event_name,
                    "tool": tool_name, "command": command, "thread_id": event.get("thread_id"),
                    "session_id": event.get("session_id"), "turn_id": event.get("turn_id"),
                    "transcript_field_present": "transcript_path" in event,
                    "session_has_transcript": bool(event.get("transcript_path"))}, ensure_ascii=False))

    token_percent = compute_token_percent(event)
    if token_percent is not None:
        sent_token = send_command(f"TOKEN:{token_percent}", prefer_daemon=True, fallback_direct=False)
        log(f"sent={sent_token}")

    if command:
        sent = send_event(event, command)
        log(f"sent={sent}")

    if event.get("hook_event_name") == "Stop":
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"error: {exc}")
        if "Stop" in sys.argv:
            print(json.dumps({"continue": True}))
        sys.exit(0)
