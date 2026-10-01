"""Single USB owner: verified transport, reconnect, session arbitration and local control."""

import argparse
from contextlib import closing
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time

import serial
from serial.tools import list_ports

from light_state import LightState, STATES
from thread_reconcile import ThreadReconciler

ROOT = Path(os.environ.get("AGENTCORE_LIGHT_HOME", Path(__file__).resolve().parent.parent))
SETTINGS = ROOT / ".local/device.json"
STATUS_RE = re.compile(r"^STATUS:([A-Z_]+),TOKEN:(\d+),BRIGHTNESS:(\d+)")


def validate_scroll_bitmap(value):
    width, bitmap = value.split(":", 1)
    width = int(width)
    if not 92 <= width <= 2048 or len(bitmap) != ((width + 7) // 8) * 14 * 2 or not re.fullmatch(r"[0-9A-F]+", bitmap):
        raise ValueError("Invalid scrolling title bitmap")
    return value


class Device:
    def __init__(self, serial_number):
        self.serial_number = serial_number
        self.port = None
        self.connection = None
        self.last_status = None
        self.extended = False
        self.threads_supported = False
        self.titles_supported = False
        self.scroll_supported = False
        self.thread_frame = None

    def close(self):
        if self.connection:
            self.connection.close()
        self.connection = None
        self.port = None

    def exchange(self, command, accepts):
        self.connection.reset_input_buffer()
        self.connection.write((command + "\n").encode())
        self.connection.flush()
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            line = self.connection.readline().decode("utf-8", errors="replace").strip()
            if accepts(line):
                return line
        raise TimeoutError(f"Device did not acknowledge {command.split(':')[0]}")

    def connect(self):
        ports = [p for p in list_ports.comports()
                 if p.vid == 0x303A and p.pid == 0x1001 and p.serial_number == self.serial_number]
        if len(ports) != 1:
            raise ConnectionError("Configured ESP32 is absent or ambiguous")
        self.port = ports[0].device
        try:
            self.connection = serial.Serial(self.port, 115200, timeout=0.1, write_timeout=1)
            time.sleep(0.3)
            self.exchange("PING", lambda s: s == "PONG:AGENTCORE-LIGHT-V3")
            self.status()
        except Exception:
            self.close()
            raise

    def status(self):
        line = self.exchange("STATUS", lambda s: STATUS_RE.match(s) is not None)
        match = STATUS_RE.match(line)
        if match[1] not in STATES or not 0 <= int(match[2]) <= 100 or not 0 <= int(match[3]) <= 100:
            raise OSError("Device returned invalid status")
        self.last_status = {"state": match[1], "token": int(match[2]), "brightness": int(match[3])}
        self.scroll_supported = "FW:MAC4" in line
        self.titles_supported = "FW:MAC3" in line or self.scroll_supported
        self.threads_supported = "FW:MAC2" in line or self.titles_supported
        self.extended = "FW:MAC1" in line or self.threads_supported
        frame = re.search(r"THREADS:[0-6]{8},[0-9]+,[0-9]+,[0-9]+", line)
        self.thread_frame = frame[0] if frame else None
        return self.last_status

    def send(self, command):
        if command.startswith("SCROLLTITLE:"):
            _, slot, width, bitmap = command.split(":", 3)
            if not slot.isdigit() or not 1 <= int(slot) <= 8:
                raise ValueError("Invalid title slot")
            validate_scroll_bitmap(width + ":" + bitmap)
            parts = [f"TBEGIN:{slot}:{width}"]
            parts.extend(f"TDATA:{slot}:{offset // 2}:{bitmap[offset:offset + 256]}"
                         for offset in range(0, len(bitmap), 256))
            parts.append(f"TEND:{slot}")
            for part in parts:
                self.exchange(part, lambda reply, expected=part: reply == expected)
            return
        if command in STATES:
            expected = "State changed to: " + command
        elif command.startswith("TOKEN:"):
            expected = "Token percent: " + command.split(":")[1]
        else:
            expected = command
        self.exchange(command, lambda s: s == expected)


class Service:
    def __init__(self, device, settings=SETTINGS):
        self.device = device
        self.settings = settings
        self.state = LightState()
        self.reconciler = ThreadReconciler()
        self.pending_events = {}
        self.pending_check_at = 0
        self.saved = {"brightness": 16, "enabled": True, "quota": None, "quota_at": None}
        if settings.exists():
            self.saved.update(json.loads(settings.read_text()))
        self.state.enabled = self.saved["enabled"]
        self.sent = {}
        self.last_state_at = 0
        self.retry_at = 0
        self.poll_at = 0
        self.error = None
        self.title_cache = {}
        self.bitmap_cache = {}

    def save(self):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.saved))
        temporary.replace(self.settings)

    def titles(self, rows):
        # Optional local metadata only; internal schema changes must not affect USB control.
        now = time.monotonic()
        missing = [row["id"] for row in rows
                   if now - self.title_cache.get(row["id"], ("", -1000))[1] >= 60]
        if missing:
            found = {}
            try:
                path = Path.home() / ".codex/state_5.sqlite"
                with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.05)) as db:
                    marks = ",".join("?" for _ in missing)
                    found = dict(db.execute(f"SELECT id, title FROM threads WHERE id IN ({marks})", missing))
            except (sqlite3.Error, OSError):
                pass
            # The database title can be the first prompt; the index stores the Chat title.
            # The index is append-only, so the last valid name for an ID wins.
            wanted = set(missing)
            try:
                with (Path.home() / ".codex/session_index.jsonl").open(encoding="utf-8", errors="replace") as index:
                    for line in index:
                        try:
                            entry = json.loads(line)
                        except ValueError:
                            continue  # Includes a partially written final line.
                        if not isinstance(entry, dict):
                            continue
                        key, title = entry.get("id"), entry.get("thread_name")
                        if isinstance(key, str) and key in wanted and isinstance(title, str) and title.strip():
                            found[key] = title.strip()
            except OSError:
                pass
            for key in missing:
                self.title_cache[key] = (found.get(key) or key[:12], now)
        for row in rows:
            row["title"] = " ".join(str(self.title_cache[row["id"]][0]).split())[:160]
        current = set(self.state.sessions)
        self.title_cache = {key: value for key, value in self.title_cache.items() if key in current}
        return rows

    def title_commands(self, now):
        rows = self.titles([row for row in self.state.layout(now) if row["slot"] is not None])
        commands = {}
        scroll = self.device.scroll_supported is True
        current_titles = {(scroll, row["title"]) for row in rows}
        self.bitmap_cache = {title: value for title, value in self.bitmap_cache.items() if title in current_titles}
        for row in rows:
            title = row["title"]
            cache_key = (scroll, title)
            if cache_key not in self.bitmap_cache:
                try:
                    result = subprocess.run([os.environ.get("AGENTCORE_LIGHT_RENDERER", str(ROOT / ".local/AgentCore Light.app/Contents/MacOS/AgentCoreLight")),
                                             "--render-scroll-title" if scroll else "--render-title", title], capture_output=True, text=True,
                                            timeout=2, check=True)
                    bitmap = result.stdout.strip().upper()
                    if scroll:
                        validate_scroll_bitmap(bitmap)
                    elif not re.fullmatch(r"[0-9A-F]{336}", bitmap):
                        raise ValueError("Invalid title bitmap")
                    self.bitmap_cache[cache_key] = bitmap
                except (OSError, subprocess.SubprocessError, ValueError):
                    # An unavailable renderer must never block state updates.
                    self.bitmap_cache[cache_key] = ("92:" if scroll else "") + "0" * 336
            prefix = "SCROLLTITLE" if scroll else "TITLE"
            commands[f"title{row['slot']}"] = f"{prefix}:{row['slot']}:{self.bitmap_cache[cache_key]}"
        return commands

    def snapshot(self):
        age = time.time() - self.saved["quota_at"] if self.saved["quota_at"] else None
        rows = self.state.layout(time.monotonic())
        return {"threads": self.titles(rows[:64]), "threads_total": len(rows),
                "firmware_threads": self.device.threads_supported is True,
                "connected": self.device.connection is not None, "port": self.device.port,
                "state": self.state.desired(time.monotonic()), "device": self.device.last_status,
                "sessions": len(self.state.sessions), "enabled": self.state.enabled,
                "brightness": self.saved["brightness"], "quota": self.saved["quota"],
                "quota_at": self.saved["quota_at"], "quota_stale": age is None or age > 900,
                "error": self.error, "firmware_extended": self.device.extended}

    def accept_event(self, event, now):
        session = event.get("session_id")
        if not isinstance(session, str) or not session or len(session) > 200 or event.get("state") not in STATES:
            raise ValueError("Invalid session event")
        canonical = self.state.aliases.get(session, session)
        if event.get("event") in ("Stop", "SessionEnd", "Interrupt"):
            self.pending_events.pop(session, None)
            if canonical not in self.state.sessions and "transcript_path" in event and not event["transcript_path"]:
                return  # A hidden task's completion must not light the ring either.
        has_metadata = "transcript_path" in event
        has_transcript = isinstance(event.get("transcript_path"), str) and bool(event["transcript_path"].strip())
        if (has_metadata and not has_transcript and canonical not in self.state.sessions
                and self.reconciler.is_registered(canonical) is not True):
            if event.get("event") != "SessionStart":
                self.pending_events[session] = (event, now)
            logging.info("Deferred non-persisted session=%r event=%r", session, event.get("event"))
            return
        self.pending_events.pop(session, None)
        self.state.event(event, now)

    def promote_pending_events(self, now):
        if not self.pending_events or now < self.pending_check_at:
            return
        self.pending_check_at = now + 1
        for session, (event, at) in list(self.pending_events.items()):
            if now - at >= 300:
                self.pending_events.pop(session, None)
            elif self.reconciler.is_registered(session) is True:
                self.pending_events.pop(session, None)
                self.state.event(event, now)
                logging.info("Activated newly registered session=%r", session)

    def request(self, raw):
        now = time.monotonic()
        if raw.startswith("{"):
            event = json.loads(raw)
            self.accept_event(event, now)
            logging.info("event session=%r turn=%r name=%r state=%r source_session=%r",
                         event.get("session_id"), event.get("turn_id"), event.get("event"),
                         event.get("state"), event.get("source_session_id"))
            return "QUEUED"
        raw = raw.strip().upper()
        if raw == "HOST_STATUS":
            return json.dumps(self.snapshot())
        if raw == "RECONNECT":
            self.device.close()
            self.retry_at = 0
            return "QUEUED"
        if raw == "ON":
            self.state.enabled = True
            self.saved["enabled"] = True
            self.save()
        elif raw in STATES:
            self.state.command(raw, now)
            if raw == "OFF":
                self.saved["enabled"] = False
                self.save()
        elif raw.startswith(("TOKEN:", "BRIGHTNESS:")):
            kind, value = raw.split(":", 1)
            value = int(value)
            if not 0 <= value <= 100:
                raise ValueError("Percentage must be 0-100")
            if kind == "TOKEN":
                self.saved.update(quota=value, quota_at=time.time())
                # Refresh the firmware freshness timer even if the percentage is unchanged.
                self.sent.pop("stale", None)
            else:
                self.saved["brightness"] = value
            self.save()
        else:
            raise ValueError("Unsupported host command")
        self.tick(force=True)
        if not self.device.connection:
            raise ConnectionError("Device offline; value saved for reconnect")
        return "OK"

    def tick(self, force=False):
        now = time.monotonic()
        self.promote_pending_events(now)
        for key, reason in self.reconciler.reconcile(self.state.sessions, now):
            logging.info("Removed session=%r reason=%s", key, reason)
        try:
            if not self.device.connection:
                if now < self.retry_at:
                    return
                self.retry_at = now + 5
                self.device.connect()
                self.sent.clear()
                force = True
                logging.info("Connected %s", self.device.port)
            desired = self.state.desired(now)
            commands = {"brightness": f"BRIGHTNESS:{self.saved['brightness']}"}
            if self.saved["quota"] is not None:
                commands["quota"] = f"TOKEN:{self.saved['quota']}"
            if self.device.extended:
                commands["stale"] = "STALE:" + str(int(not self.saved["quota_at"] or time.time() - self.saved["quota_at"] > 900))
            if self.device.titles_supported is True:
                commands.update(self.title_commands(now))
            if self.device.threads_supported is True:
                commands["threads"] = self.state.frame(now)
            # Urgent states bypass the small transition hold; duplicates never restart animation.
            if (force or desired in ("ERROR", "NEED_CONFIRM", "OFF")
                    or now - self.last_state_at >= 0.35):
                commands["state"] = desired
            for key, command in commands.items():
                if self.sent.get(key) != command:
                    self.device.send(command)
                    self.sent[key] = command
                    if key == "state":
                        self.last_state_at = now
                    logging.info("ack %s", command)
            if now >= self.poll_at:
                actual = self.device.status()
                self.poll_at = now + 5
                # Detect spontaneous device resets and replay persistent values.
                if actual["brightness"] != self.saved["brightness"]:
                    self.sent.pop("brightness", None)
                if self.saved["quota"] is not None and actual["token"] != self.saved["quota"]:
                    self.sent.pop("quota", None)
                if self.device.threads_supported is True and self.device.thread_frame != self.sent.get("threads"):
                    self.sent.pop("threads", None)
                    for key in list(self.sent):
                        if key.startswith("title"):
                            self.sent.pop(key, None)
                if actual["state"] != desired:
                    self.sent.pop("state", None)
            self.error = None
        except (OSError, serial.SerialException, TimeoutError) as exc:
            self.device.close()
            self.error = str(exc)
            self.retry_at = now + 5
            logging.warning("Disconnected: %s", exc)


def run_daemon():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-number", required=True)
    parser.add_argument("--tcp-port", type=int, default=37637)
    args = parser.parse_args()
    handler = RotatingFileHandler(ROOT / "host/device.log", maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[handler])
    service = Service(Device(args.serial_number))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", args.tcp_port))
        server.listen(16)
        server.settimeout(0.1)
        try:
            while True:
                service.tick()
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(0.5)
                    try:
                        data = b""
                        while b"\n" not in data and len(data) <= 4096:
                            part = connection.recv(4096)
                            if not part:
                                break
                            data += part
                        if len(data) > 4096:
                            raise ValueError("Request too large")
                        reply = service.request(data.decode("utf-8").strip())
                    except Exception as exc:
                        reply = "ERR " + str(exc)
                    try:
                        connection.sendall((reply + "\n").encode())
                    except OSError:
                        pass
        finally:
            service.device.close()


if __name__ == "__main__":
    run_daemon()
