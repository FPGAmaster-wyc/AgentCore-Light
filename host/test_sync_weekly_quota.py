import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_weekly_quota as sync


class WeeklyQuotaTests(unittest.TestCase):
    def window(self, used=9, minutes=10080):
        return {"usedPercent": used, "windowDurationMins": minutes, "resetsAt": 2000}

    def test_weekly_window_can_be_primary_or_secondary(self):
        for field in ("primary", "secondary"):
            result = {"rateLimitsByLimitId": {"codex": {field: self.window()}}}
            self.assertEqual(sync.weekly_remaining(result, now=1000), 91)

    def test_multi_bucket_takes_precedence_over_legacy(self):
        result = {"rateLimitsByLimitId": {"other": {"primary": self.window()}},
                  "rateLimits": {"primary": self.window()}}
        with self.assertRaises(ValueError):
            sync.weekly_remaining(result, now=1000)

    def test_legacy_and_boundaries(self):
        for used, expected in ((0, 100), (100, 0), (9, 91)):
            self.assertEqual(sync.weekly_remaining({"rateLimits": {
                "primary": self.window(used)}}, now=1000), expected)

    def test_missing_wrong_period_invalid_and_stale_data(self):
        windows = [None, self.window(minutes=300), self.window(used=None),
                   self.window(used=True), self.window(used=-1), self.window(used=101),
                   self.window(used=float("nan")), {**self.window(), "resetsAt": 999}]
        for window in windows:
            with self.subTest(window=window), self.assertRaises(ValueError):
                sync.weekly_remaining({"rateLimits": {"primary": window}}, now=1000)

    def test_rpc_handshake_and_notifications(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fake-codex"
            executable.write_text("#!" + sync.sys.executable + "\n" + '''
import json, sys
assert json.loads(sys.stdin.readline())["method"] == "initialize"
print(json.dumps({"id": 1, "result": {}}), flush=True)
assert json.loads(sys.stdin.readline())["method"] == "initialized"
assert json.loads(sys.stdin.readline())["method"] == "account/rateLimits/read"
print(json.dumps({"method": "notification"}), flush=True)
print(json.dumps({"id": 2, "result": {"ok": True}}), flush=True)
sys.stdin.read()
''')
            executable.chmod(0o700)
            self.assertEqual(sync.read_rate_limits(str(executable), timeout=2), {"ok": True})
            executable.write_text("#!" + sync.sys.executable + "\nimport time; time.sleep(30)\n")
            with self.assertRaises(TimeoutError):
                sync.read_rate_limits(str(executable), timeout=0.1)

    def test_failure_does_not_send_a_percentage(self):
        with patch.object(sync.sys, "argv", ["sync"]), \
             patch.object(sync, "read_rate_limits", return_value={}), \
             patch.object(sync, "send_command") as send:
            self.assertEqual(sync.main(), 1)
            send.assert_not_called()

    def test_success_only_uses_existing_daemon(self):
        result = {"rateLimits": {"primary": {**self.window(), "resetsAt": 9999999999}}}
        with patch.object(sync.sys, "argv", ["sync"]), \
             patch.object(sync, "read_rate_limits", return_value=result), \
             patch.object(sync, "send_command") as send:
            self.assertEqual(sync.main(), 0)
            send.assert_called_once_with("TOKEN:91", prefer_daemon=True, fallback_direct=False)


if __name__ == "__main__":
    unittest.main()
