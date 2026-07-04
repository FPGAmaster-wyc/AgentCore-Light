#!/usr/bin/env python3
"""Hook queue worker (Linux side).

Reads JSON payloads written by the hook script from a queue directory,
POSTs them to the AgentCore-Light server via the SSH reverse tunnel,
and removes the files.

Uses only the Python standard library so it runs on machines without Node.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

HOOK_URL = os.environ.get(
    "AGENT_LIGHT_HOOK_URL",
    "http://127.0.0.1:18787/hook?agent=cursor",
)
QUEUE_DIR = Path(os.environ.get(
    "AGENT_LIGHT_QUEUE_DIR",
    os.path.expanduser("~/.cursor/hooks/queue"),
))
ATTEMPTS_DIR = QUEUE_DIR / ".attempts"
POLL_SECONDS = 0.05
STALE_SECONDS = 60.0
MAX_ATTEMPTS = 3


def _attempts_path(name: str) -> Path:
    return ATTEMPTS_DIR / f"{name}.count"


def attempts_for(name: str) -> int:
    try:
        return int(_attempts_path(name).read_text(encoding="utf-8")) or 0
    except Exception:
        return 0


def bump_attempts(name: str) -> int:
    nxt = attempts_for(name) + 1
    try:
        _attempts_path(name).write_text(str(nxt), encoding="utf-8")
    except Exception:
        pass
    return nxt


def clear_attempts(name: str) -> None:
    try:
        _attempts_path(name).unlink()
    except Exception:
        pass


def post_payload(raw: str) -> None:
    request = urllib.request.Request(
        HOOK_URL,
        data=raw.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    response = opener.open(request, timeout=2)
    response.read()
    if response.status >= 400:
        raise RuntimeError(f"hook post failed: {response.status}")


def drain_once() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ATTEMPTS_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(QUEUE_DIR.iterdir()):
        if path.suffix != ".json":
            continue
        name = path.name
        try:
            age = time.time() - path.stat().st_mtime
            if age > STALE_SECONDS:
                path.unlink()
                clear_attempts(name)
                continue
            raw = path.read_text(encoding="utf-8")
            if raw.strip():
                post_payload(raw)
            path.unlink()
            clear_attempts(name)
        except Exception as exc:  # noqa: BLE001
            tries = bump_attempts(name)
            if tries >= MAX_ATTEMPTS:
                try:
                    path.unlink()
                except Exception:
                    pass
                clear_attempts(name)
                print(
                    f"[hook-queue] {name}: dropping after {tries} attempts ({exc})",
                    file=sys.stderr,
                )


def main() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[hook-queue] draining {QUEUE_DIR} -> {HOOK_URL}", file=sys.stderr)
    while True:
        try:
            drain_once()
        except Exception as exc:  # noqa: BLE001
            print(f"[hook-queue] {exc}", file=sys.stderr)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
