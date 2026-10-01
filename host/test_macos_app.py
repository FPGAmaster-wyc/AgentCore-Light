"""Validate packaged service setup without modifying this machine's hooks or jobs."""
import json
from pathlib import Path
import plistlib
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import macos_app as app


class MacAppSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bundle = self.home / "Applications/AgentCore Light.app"
        self.helper = self.bundle / "Contents/MacOS/agentcore-host"
        self.helper.parent.mkdir(parents=True)
        self.helper.touch()
        self.codex = self.home / "codex"
        self.codex.touch(); self.codex.chmod(0o755)
        self.root = self.home / "Library/Application Support/AgentCore Light"
        self.hooks = self.home / ".codex/hooks.json"
        self.hooks.parent.mkdir()
        self.labels = (app.LABEL, app.LABEL + "-quota", app.LABEL + "-menu")
        self.paths = {label: self.home / "Library/LaunchAgents" / (label + ".plist") for label in self.labels}
        self.paths[app.LABEL].parent.mkdir(parents=True)
        self.running = set()
        self.fail_bootstrap = False
        for mock in (patch("macos_app.Path.home", return_value=self.home),
                     patch("macos_app.data_root", return_value=self.root),
                     patch("macos_app.devices", return_value=[{"serial_number": "ESP32", "port": "/dev/test"}]),
                     patch("macos_app.subprocess.run", side_effect=self.launchctl)):
            mock.start(); self.addCleanup(mock.stop)

    def launchctl(self, arguments, **kwargs):
        operation = arguments[1]
        if operation == "print":
            return SimpleNamespace(returncode=0 if arguments[2].split("/")[-1] in self.running else 1)
        if operation == "bootout":
            self.running.discard(arguments[2].split("/")[-1])
        if operation == "bootstrap":
            if self.fail_bootstrap:
                self.fail_bootstrap = False
                raise subprocess.CalledProcessError(1, arguments)
            self.running.add(plistlib.loads(Path(arguments[3]).read_bytes())["Label"])
        return SimpleNamespace(returncode=0)

    def install(self):
        app.configure(self.bundle, "ESP32", str(self.codex))

    def legacy(self):
        source = self.home / "Old Project"
        (source / ".local").mkdir(parents=True)
        (source / ".local/device.json").write_text('{"brightness":25,"enabled":false,"quota":75}')
        python = str(source / ".venv/bin/python")
        for label, path in self.paths.items():
            path.write_bytes(plistlib.dumps({"Label": label, "WorkingDirectory": str(source),
                "ProgramArguments": [python, str(source / "host/light_daemon.py")]}))
        self.running.update(self.labels)
        old = shlex.join([python, str(source / "host/codex_light_hook.py")])
        self.hooks.write_text(json.dumps({"extra": "preserve", "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-hook"},
                                           {"type": "command", "command": old}]}]}}))

    def test_install_migrates_settings_and_replaces_only_our_hooks(self):
        self.legacy()
        self.install()
        hooks = json.loads(self.hooks.read_text())
        self.assertEqual(hooks["extra"], "preserve")
        self.assertEqual(hooks["hooks"]["PreToolUse"][0]["matcher"], "Bash")
        self.assertEqual(hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "other-hook")
        expected = shlex.join([str(self.helper), "hook"])
        for event in app.EVENTS:
            self.assertEqual(sum(h["command"] == expected for g in hooks["hooks"][event] for h in g["hooks"]), 1)
        settings = json.loads((self.root / ".local/device.json").read_text())
        self.assertEqual(settings["brightness"], 25)
        self.assertFalse(settings["enabled"])
        daemon = plistlib.loads(self.paths[app.LABEL].read_bytes())
        self.assertEqual(daemon["ProgramArguments"], [str(self.helper), "daemon", "--serial-number", "ESP32"])
        self.assertEqual(daemon["EnvironmentVariables"]["AGENTCORE_LIGHT_HOME"], str(self.root))
        self.assertEqual(self.running, set(self.labels))
        self.assertTrue(list((self.root / "backups").glob("*/hooks.json")))

    def test_reinstall_is_idempotent_and_uninstall_retains_other_hooks(self):
        self.legacy(); self.install(); self.install()
        hooks = json.loads(self.hooks.read_text())
        self.assertEqual(len(hooks["hooks"]["Stop"]), 1)
        app.configure(self.bundle, uninstall=True)
        self.assertFalse(self.running)
        self.assertTrue(all(not p.exists() for p in self.paths.values()))
        self.assertFalse((self.root / "install.json").exists())
        self.assertTrue((self.root / ".local/device.json").exists())
        hooks = json.loads(self.hooks.read_text())
        self.assertEqual(hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "other-hook")
        self.assertFalse(hooks["hooks"]["Stop"])

    def test_bootstrap_failure_restores_original_files_and_running_jobs(self):
        self.legacy()
        originals = {p: p.read_bytes() for p in [self.hooks, *self.paths.values()]}
        self.fail_bootstrap = True
        with self.assertRaisesRegex(RuntimeError, "已恢复原配置"):
            self.install()
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)
        self.assertEqual(self.running, set(self.labels))
        self.assertFalse((self.root / "install.json").exists())

    def test_invalid_codex_is_rejected_before_any_configuration_changes(self):
        self.legacy()
        original = self.hooks.read_bytes()
        with self.assertRaises(ValueError):
            app.configure(self.bundle, "ESP32", "/missing/codex")
        self.assertEqual(self.hooks.read_bytes(), original)
        self.assertEqual(self.running, set(self.labels))
        self.assertFalse(self.root.exists())

    def test_moved_app_removes_previous_packaged_hook(self):
        self.install()
        new_bundle = self.home / "Other Location/AgentCore Light.app"
        new_helper = new_bundle / "Contents/MacOS/agentcore-host"
        new_helper.parent.mkdir(parents=True); new_helper.touch()
        app.configure(new_bundle, "ESP32", str(self.codex))
        hooks = json.loads(self.hooks.read_text())
        self.assertEqual(hooks["hooks"]["Stop"][0]["hooks"][0]["command"], shlex.join([str(new_helper), "hook"]))
        self.assertEqual(len(hooks["hooks"]["Stop"]), 1)
