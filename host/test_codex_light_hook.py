import io
import json
import unittest
from unittest.mock import patch

import codex_light_hook as hook


class HookStatusTests(unittest.TestCase):
    def test_successful_or_unstructured_output_does_not_trigger_error(self):
        responses = [
            {"isError": False, "content": [{"type": "text", "text": "error"}]},
            {"exit_code": 0, "output": "STATE_ERROR failed exit code: 1"},
            {"output": {"isError": True, "exit_code": 1}},
            "error failed exit code: 1 exit status 1",
            '{"isError": true, "exit_code": 1}',
            "hook-format-probe\n",  # Actual Bash hook output, without exit metadata.
            {"exit_code": None}, {"exit_code": False}, {"isError": "false"},
            None, [], {},
        ]
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(hook.command_for_event({
                    "hook_event_name": "PostToolUse", "tool_response": response,
                }), "THINKING")

    def test_explicit_failures_trigger_error(self):
        for response in ({"isError": True}, {"exit_code": 1},
                         {"exit_code": 2}, {"exit_code": -9},
                         {"isError": False, "exit_code": 1}):
            with self.subTest(response=response):
                self.assertEqual(hook.command_for_event({
                    "hook_event_name": "PostToolUse", "tool_response": response,
                }), "ERROR")

    def test_permission_and_existing_lifecycle_mappings(self):
        cases = [
            ({"hook_event_name": "PermissionRequest", "tool_name": "Bash"}, "NEED_CONFIRM"),
            ({"hook_event_name": "SessionStart"}, "IDLE"),
            ({"hook_event_name": "UserPromptSubmit"}, "THINKING"),
            ({"hook_event_name": "PreToolUse", "tool_name": "apply_patch"}, "WRITING"),
            ({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, "RUNNING"),
            ({"hook_event_name": "Stop"}, "DONE"),
        ]
        for event, expected in cases:
            with self.subTest(event=event):
                self.assertEqual(hook.command_for_event(event), expected)

    def test_stdin_event_sends_status_without_permission_decision(self):
        event = {"hook_event_name": "PermissionRequest", "tool_name": "Bash"}
        with patch.object(hook.sys, "stdin", io.StringIO(json.dumps(event))), \
             patch.object(hook.sys, "stdout", io.StringIO()) as stdout, \
             patch.object(hook, "compute_token_percent", return_value=None), \
             patch.object(hook, "log"), patch.object(hook, "send_event") as send:
            hook.main()
            send.assert_called_once_with(event, "NEED_CONFIRM")
            self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
