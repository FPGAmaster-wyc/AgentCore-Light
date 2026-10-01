"""Host-side session arbitration, independent of the USB device."""

import time

STATES = {"IDLE", "THINKING", "WRITING", "RUNNING", "DONE", "ERROR", "NEED_CONFIRM", "OFF"}
PRIORITY = {"NEED_CONFIRM": 5, "ERROR": 4, "WRITING": 3, "RUNNING": 2, "THINKING": 1}

PALETTE = [("紫色", "A050FF"), ("红色", "FF5050"), ("青色", "00D6DC"),
           ("橙色", "FF941F"), ("蓝色", "398CFF"), ("粉色", "FF63AE"),
           ("绿色", "53DB79"), ("黄色", "FFD34D")]
CODES = {"THINKING": "1", "WRITING": "2", "RUNNING": "3", "DONE": "4",
         "ERROR": "5", "NEED_CONFIRM": "6"}


class LightState:
    def __init__(self):
        self.sessions = {}
        self.aliases = {}
        self.legacy = ("IDLE", 0)
        self.enabled = True

    def event(self, event, now):
        session = event.get("session_id")
        turn = event.get("turn_id")
        state = event.get("state")
        name = event.get("event")
        if not isinstance(session, str) or not session or len(session) > 200 or state not in STATES:
            raise ValueError("Invalid session event")
        session = self.aliases.get(session, session)
        alias = event.get("source_session_id")
        if isinstance(alias, str) and alias and alias != session:
            self.aliases[alias] = session
        if isinstance(alias, str) and alias != session and alias in self.sessions:
            old = self.sessions.pop(alias)
            if session not in self.sessions:
                self.sessions[session] = old
        previous = self.sessions.get(session)
        if previous and turn and previous["turn"] and turn != previous["turn"]:
            if name != "UserPromptSubmit":
                return  # A delayed event from an older turn must not finish the new one.
        if name in ("SessionEnd", "Interrupt"):
            self.sessions.pop(session, None)
            return
        if name == "SessionStart":
            return  # Opening another chat does not override active work.
        self.sessions[session] = {"state": state, "at": now, "turn": turn,
                                  "slot": previous["slot"] if previous else None, "wall": time.time()}
        self.layout(now)

    def command(self, state, now):
        if state not in STATES:
            raise ValueError("Unknown state")
        if state == "OFF":
            self.enabled = False
        else:
            self.legacy = (state, now)

    def layout(self, now):
        for session, item in list(self.sessions.items()):
            age = now - item["at"]
            if age >= 1800 or item["state"] in ("DONE", "IDLE", "OFF") and age >= 10:
                del self.sessions[session]
        used = {item["slot"] for item in self.sessions.values() if item["slot"] is not None}
        free = [slot for slot in range(8) if slot not in used]
        rows = []
        for session, item in self.sessions.items():
            if item["slot"] is None and free:
                item["slot"] = free.pop(0)
            slot = item["slot"]
            state = item["state"]
            if state == "ERROR" and now - item["at"] >= 10:
                state = "THINKING"
            rows.append({"id": session, "slot": slot + 1 if slot is not None else None,
                         "color_name": PALETTE[slot][0] if slot is not None else "待分配",
                         "color": PALETTE[slot][1] if slot is not None else "808080",
                         "state": state})
        return rows

    def frame(self, now):
        rows = self.layout(now)
        digits = ["0"] * 8
        for row in rows:
            if row["slot"] is not None:
                digits[row["slot"] - 1] = CODES.get(row["state"], "0")
        active = sum(row["state"] in PRIORITY for row in rows)
        waiting = sum(row["state"] == "NEED_CONFIRM" for row in rows)
        overflow = sum(row["slot"] is None for row in rows)
        return f"THREADS:{''.join(digits)},{min(active,999)},{min(waiting,999)},{min(overflow,999)}"

    def desired(self, now):
        rows = self.layout(now)
        if not self.enabled:
            return "OFF"
        candidates = [row["state"] for row in rows if row["state"] in PRIORITY]
        done = any(row["state"] == "DONE" for row in rows)
        state, at = self.legacy
        age = now - at
        if state in ("THINKING", "WRITING", "RUNNING") and age > 45:
            state = "IDLE"
        if state in ("DONE", "ERROR") and age >= 10:
            state = "IDLE"
        if state in PRIORITY:
            candidates.append(state)
        done |= state == "DONE"
        return max(candidates, key=PRIORITY.get) if candidates else ("DONE" if done else "IDLE")
