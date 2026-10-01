"""Read-only reconciliation of hook sessions with local Codex thread records."""
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3


def completed_after(path, turn, last_event_wall):
    if not path:
        return False
    try:
        with Path(path).open('rb') as stream:
            size = stream.seek(0, 2)
            start = max(0, size - 262144)
            stream.seek(start)
            lines = stream.read(262144).splitlines()
        if start:
            lines = lines[1:]
        for line in reversed(lines):
            try:
                record = json.loads(line)
                payload = record.get('payload', {})
                if record.get('type') != 'event_msg':
                    continue
                kind = payload.get('type')
                if kind not in ('task_started', 'task_complete', 'turn_aborted'):
                    continue
                if kind == 'task_started':
                    return False
                if turn and payload.get('turn_id') != turn:
                    return False
                stamp = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp()
                return stamp >= last_event_wall
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    except OSError:
        pass
    return False


class ThreadReconciler:
    def __init__(self, database=None):
        self.database = database or Path.home() / '.codex/state_5.sqlite'
        self.next_check = 0
        self.missing = {}

    def is_registered(self, session):
        try:
            with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True, timeout=0.05)) as db:
                return db.execute('SELECT 1 FROM threads WHERE id=?', (session,)).fetchone() is not None
        except (sqlite3.Error, OSError):
            return None  # Absence and an unavailable database are different evidence.

    def reconcile(self, sessions, now):
        if now < self.next_check:
            return []
        self.next_check = now + 30
        self.missing = {key: value for key, value in self.missing.items() if key in sessions}
        if not sessions:
            return []
        try:
            with closing(sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True, timeout=0.05)) as db:
                records = {}
                for key in sessions:
                    row = db.execute('SELECT rollout_path FROM threads WHERE id=?', (key,)).fetchone()
                    if row is not None:
                        records[key] = row[0]
        except (sqlite3.Error, OSError):
            self.missing.clear()
            return []
        removed = []
        for key, item in list(sessions.items()):
            if key in records:
                self.missing.pop(key, None)
                if item['state'] not in ('DONE', 'IDLE', 'OFF') and completed_after(
                        records[key], item.get('turn'), item.get('wall', float('inf'))):
                    removed.append((key, 'completed transcript'))
            else:
                count = self.missing.get(key, 0) + 1
                self.missing[key] = count
                if count >= 2 and now - item['at'] >= 300:
                    removed.append((key, 'absent from registry and inactive for 5 minutes'))
        for key, _ in removed:
            sessions.pop(key, None)
            self.missing.pop(key, None)
        return removed
