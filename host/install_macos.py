"""Install/reinstall the per-user services, native menu and Codex hooks (no firmware flashing)."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-number", required=True, help="USB serial number of the intended ESP32")
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    python = root / ".venv/bin/python"
    if not python.exists() or not args.codex or not Path(args.codex).is_file():
        parser.error("Project .venv and an installed Codex executable are required")
    local = root / ".local"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = local / "backups" / stamp
    backup.mkdir(parents=True)
    contents = local / "AgentCore Light.app/Contents"
    executable = contents / "MacOS/AgentCoreLight"
    executable.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["xcrun", "swiftc", str(root / "host/LightMenu.swift"), "-o", str(executable),
                    "-module-cache-path", str(local / "swift-cache")], check=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": "com.garyjiang.agentcore-light-menu", "CFBundleName": "AgentCore Light",
        "CFBundleExecutable": "AgentCoreLight", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
        "LSUIElement": True, "NSHighResolutionCapable": True,
    }))
    jobs = {
        "com.garyjiang.agentcore-light": ([str(python), "-u", str(root / "host/light_daemon.py"),
                                          "--serial-number", args.serial_number], {"KeepAlive": True, "ThrottleInterval": 5}, "daemon"),
        "com.garyjiang.agentcore-light-quota": ([str(python), str(root / "host/sync_weekly_quota.py"),
                                                "--codex", args.codex], {"StartInterval": 300}, "quota"),
        "com.garyjiang.agentcore-light-menu": ([str(executable), str(root)], {}, "menu"),
    }
    domain = f"gui/{os.getuid()}"
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    for name, (arguments, options, log) in jobs.items():
        target = agents / (name + ".plist")
        if target.exists():
            shutil.copy2(target, backup / target.name)
        running = subprocess.run(["launchctl", "print", domain + "/" + name], capture_output=True).returncode == 0
        if running:
            subprocess.run(["launchctl", "bootout", domain, str(target)], check=True)
        target.write_bytes(plistlib.dumps({"Label": name, "ProgramArguments": arguments,
            "WorkingDirectory": str(root), "RunAtLoad": True,
            "StandardOutPath": str(root / "host" / (log + ".stdout.log")),
            "StandardErrorPath": str(root / "host" / (log + ".stderr.log")), **options}))
        subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    hooks = Path.home() / ".codex/hooks.json"
    if hooks.exists():
        data = json.loads(hooks.read_text())
        shutil.copy2(hooks, backup / "hooks.json")
    else:
        data = {"hooks": {}}
    command = shlex.join([str(python), str(root / "host/codex_light_hook.py")])
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                  "PermissionRequest", "Stop", "Interrupt", "SessionEnd"):
        groups = data.setdefault("hooks", {}).setdefault(event, [])
        if not any(h.get("command") == command for group in groups for h in group.get("hooks", [])):
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": 3}]})
    hooks.parent.mkdir(parents=True, exist_ok=True)
    hooks.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print("Installed. Review new hooks in Codex Settings → Hooks. Backups:", backup)


if __name__ == "__main__":
    main()
