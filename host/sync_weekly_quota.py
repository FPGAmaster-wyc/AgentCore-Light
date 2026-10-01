"""Send the real Codex weekly remaining quota to the existing light daemon."""

import argparse
import json
import math
import os
import selectors
import subprocess
import sys
import time

from codex_light_serial import send_command


def weekly_remaining(result, now=None):
    buckets = result.get("rateLimitsByLimitId")
    bucket = buckets.get("codex") if isinstance(buckets, dict) else result.get("rateLimits")
    if not isinstance(bucket, dict) or bucket.get("limitId") not in (None, "codex"):
        raise ValueError("Codex quota bucket is unavailable")
    now = time.time() if now is None else now
    for name in ("primary", "secondary"):
        window = bucket.get(name)
        if not isinstance(window, dict) or window.get("windowDurationMins") != 10080:
            continue
        used = window.get("usedPercent")
        reset = window.get("resetsAt")
        if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100:
            raise ValueError("Invalid weekly usedPercent")
        if type(reset) not in (int, float) or not math.isfinite(reset) or reset <= now:
            raise ValueError("Weekly quota reset timestamp is missing or expired")
        return int(round(100 - used))
    raise ValueError("No weekly quota window returned; display unchanged")


def read_rate_limits(codex, timeout=30):
    process = subprocess.Popen(
        [codex, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        process.stdin.flush()

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "agentcore_light", "version": "0.1.0"}
        }})
        deadline = time.monotonic() + timeout
        buffer = b""
        while time.monotonic() < deadline:
            if not selector.select(max(0, deadline - time.monotonic())):
                break
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Codex App Server closed before returning quota")
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                message = json.loads(line)
                request_id = message.get("id")
                if request_id not in (1, 2):
                    continue
                if "error" in message:
                    raise RuntimeError(f"Codex quota request failed: {message['error']}")
                if request_id == 1:
                    send({"method": "initialized"})
                    send({"id": 2, "method": "account/rateLimits/read"})
                else:
                    return message["result"]
        raise TimeoutError("Codex quota request timed out")
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex", help="Codex executable path")
    parser.add_argument("--dry-run", action="store_true", help="read quota without updating the light")
    args = parser.parse_args()
    try:
        percent = weekly_remaining(read_rate_limits(args.codex))
        if not args.dry_run:
            send_command(f"TOKEN:{percent}", prefer_daemon=True, fallback_direct=False)
        action = "read" if args.dry_run else "sent"
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} weekly_remaining={percent}% {action}", flush=True)
    except Exception as exc:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} quota sync failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
