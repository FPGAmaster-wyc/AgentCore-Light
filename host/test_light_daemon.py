import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from light_daemon import Device, Service
from light_state import LightState


class StateTests(unittest.TestCase):
    def event(self, state, session, value, at, turn="t", event="PostToolUse"):
        state.event({"session_id": session, "turn_id": turn, "state": value, "event": event}, at)

    def test_one_completed_session_cannot_finish_another(self):
        state = LightState()
        self.event(state, "a", "RUNNING", 1)
        self.event(state, "b", "DONE", 2, event="Stop")
        self.assertEqual(state.desired(3), "RUNNING")
        self.event(state, "a", "DONE", 4, event="Stop")
        self.assertEqual(state.desired(5), "DONE")
        self.assertEqual(state.desired(15), "IDLE")

    def test_priority_stale_turn_and_interrupt(self):
        state = LightState()
        self.event(state, "a", "RUNNING", 1, turn="old")
        self.event(state, "a", "THINKING", 2, turn="new", event="UserPromptSubmit")
        self.event(state, "a", "DONE", 3, turn="old", event="Stop")
        self.assertEqual(state.desired(4), "THINKING")
        self.event(state, "b", "NEED_CONFIRM", 4)
        self.assertEqual(state.desired(5), "NEED_CONFIRM")
        self.event(state, "b", "IDLE", 6, event="Interrupt")
        self.assertEqual(state.desired(7), "THINKING")
        self.assertEqual(state.desired(2000), "IDLE")

    def test_off_survives_hooks_and_error_expires(self):
        state = LightState()
        state.command("OFF", 1)
        self.event(state, "a", "ERROR", 2)
        self.assertEqual(state.desired(3), "OFF")
        state.enabled = True
        self.assertEqual(state.desired(3), "ERROR")
        self.assertEqual(state.desired(13), "THINKING")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.device = MagicMock()
        self.device.connection = True
        self.device.port = "fake"
        self.device.extended = True
        self.device.status.return_value = {"state": "THINKING", "token": 90, "brightness": 16}
        self.service = Service(self.device, Path(self.directory.name) / "settings.json")

    def test_token_does_not_reset_legacy_activity_and_duplicates_are_suppressed(self):
        with patch("light_daemon.time.monotonic", return_value=1):
            self.service.request("THINKING")
        with patch("light_daemon.time.monotonic", return_value=40):
            self.service.request("TOKEN:90")
            before = [c.args[0] for c in self.device.send.call_args_list].count("TOKEN:90")
            self.service.request("TOKEN:90")
            self.assertEqual(before, [c.args[0] for c in self.device.send.call_args_list].count("TOKEN:90"))
            self.assertEqual(self.device.send.call_args_list[-1].args[0], "STALE:0")
        self.assertEqual(self.service.state.desired(47), "IDLE")
        self.assertEqual(self.service.saved["quota"], 90)

    def test_offline_records_desired_value_and_reports_failure(self):
        self.device.connection = None
        self.device.connect.side_effect = ConnectionError("unplugged")
        with self.assertRaises(ConnectionError):
            self.service.request("BRIGHTNESS:20")
        self.assertEqual(self.service.saved["brightness"], 20)

    def test_reconnect_replays_values_and_uses_acknowledgements(self):
        self.service.saved.update(quota=90, quota_at=1)
        self.device.connection = None
        self.device.connect.side_effect = lambda: setattr(self.device, "connection", True)
        self.service.tick()
        sent = [c.args[0] for c in self.device.send.call_args_list]
        for value in ("BRIGHTNESS:16", "TOKEN:90", "STALE:1", "IDLE"):
            self.assertIn(value, sent)
        self.device.send.side_effect = TimeoutError("no ack")
        self.service.sent.clear()
        self.service.tick()
        self.device.close.assert_called()
        self.assertIn("no ack", self.service.error)

    def test_saved_settings_reload_and_invalid_commands(self):
        self.service.request("OFF")
        loaded = Service(self.device, self.service.settings)
        self.assertFalse(loaded.state.enabled)
        for command in ("TOKEN:101", "BRIGHTNESS:-1", "invalid"):
            with self.assertRaises(ValueError):
                self.service.request(command)


class DeviceTests(unittest.TestCase):
    def test_only_exact_configured_device_is_opened(self):
        device = Device("wanted")
        ports = [SimpleNamespace(vid=0x303A, pid=0x1001, serial_number="other", device="wrong")]
        with patch("light_daemon.list_ports.comports", return_value=ports), \
             patch("light_daemon.serial.Serial") as serial:
            with self.assertRaises(ConnectionError):
                device.connect()
            serial.assert_not_called()

    def test_state_and_quota_ack_are_distinct(self):
        device = Device("wanted")
        device.connection = MagicMock()
        device.connection.readline.side_effect = [b"stale\n", b"Token percent: 90\n"]
        device.send("TOKEN:90")
        device.connection.write.assert_called_once_with(b"TOKEN:90\n")


if __name__ == "__main__":
    unittest.main()
