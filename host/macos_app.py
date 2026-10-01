"""Bundled host entry point and per-user setup for the standalone macOS app."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

LABEL = "com.garyjiang.agentcore-light"
EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
          "PermissionRequest", "Stop", "Interrupt", "SessionEnd")


def data_root():
    return Path(os.environ.get("AGENTCORE_LIGHT_HOME",
                Path.home() / "Library/Application Support/AgentCore Light"))


def app_path():
    return Path(sys.executable).resolve().parents[2] if getattr(sys, "frozen", False) else None


def discover_codex():
    candidates = [shutil.which("codex")]
    for name in ("Codex", "ChatGPT"):
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            candidates.append(str(folder / f"{name}.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"))
            candidates.append(str(folder / f"{name}.app/Contents/Resources/codex"))
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def devices():
    from serial.tools import list_ports
    return [{"serial_number": p.serial_number, "port": p.device}
            for p in list_ports.comports()
            if p.vid == 0x303A and p.pid == 0x1001 and p.serial_number]


def jobs(app, root, serial, codex):
    helper = app / "Contents/MacOS/agentcore-host"
    renderer = app / "Contents/MacOS/AgentCoreLight"
    entries = {
        LABEL: ([str(helper), "daemon", "--serial-number", serial],
                {"KeepAlive": True, "ThrottleInterval": 5}, "daemon"),
        LABEL + "-quota": ([str(helper), "quota", "--codex", codex], {"StartInterval": 300}, "quota"),
        LABEL + "-menu": (["/usr/bin/open", "-g", str(app)], {}, "menu"),
    }
    return {name: {"Label": name, "ProgramArguments": arguments, "RunAtLoad": True,
                   "WorkingDirectory": str(root), "EnvironmentVariables": {
                       "AGENTCORE_LIGHT_HOME": str(root), "AGENTCORE_LIGHT_RENDERER": str(renderer)},
                   "StandardOutPath": str(root / "host" / (log + ".stdout.log")),
                   "StandardErrorPath": str(root / "host" / (log + ".stderr.log")), **options}
            for name, (arguments, options, log) in entries.items()}


def hook_commands(previous):
    commands = set()
    for job in previous.values():
        args = job.get("ProgramArguments", [])
        if len(args) > 1 and Path(args[1]).name == "light_daemon.py":
            commands.add(shlex.join([args[0], str(Path(args[1]).with_name("codex_light_hook.py"))]))
        elif len(args) > 1 and args[1] == "daemon" and Path(args[0]).name == "agentcore-host":
            commands.add(shlex.join([args[0], "hook"]))
    return commands


def merge_hooks(data, old_commands, new_command=None):
    for event, groups in data.get("hooks", {}).items():
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if h.get("command") not in old_commands]
        data["hooks"][event] = [g for g in groups if g.get("hooks")]
    if new_command:
        for event in EVENTS:
            data.setdefault("hooks", {}).setdefault(event, []).append({
                "hooks": [{"type": "command", "command": new_command, "timeout": 3}]})
    return data


def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def configure(app, serial=None, codex=None, uninstall=False):
    root = data_root()
    agents = Path.home() / "Library/LaunchAgents"
    labels = (LABEL, LABEL + "-quota", LABEL + "-menu")
    paths = {label: agents / (label + ".plist") for label in labels}
    previous = {label: plistlib.loads(path.read_bytes()) for label, path in paths.items() if path.exists()}
    hooks = Path.home() / ".codex/hooks.json"
    data = json.loads(hooks.read_text()) if hooks.exists() else {"hooks": {}}
    new_jobs = {}
    if not uninstall:
        if not app or not (app / "Contents/MacOS/agentcore-host").is_file():
            raise ValueError("请从已解压并移到固定位置的 AgentCore Light.app 安装")
        if not codex or not Path(codex).is_file() or not os.access(codex, os.X_OK):
            raise ValueError("请选择已安装的 Codex 可执行文件，并先登录 Codex")
        if sum(p["serial_number"] == serial for p in devices()) != 1:
            raise ValueError("所选 ESP32 未连接或序列号不唯一，请重新连接设备")
        new_jobs = jobs(app, root, serial, str(Path(codex).resolve()))
    helper = app / "Contents/MacOS/agentcore-host" if app else None
    owned = hook_commands(previous)
    if helper:
        owned.add(shlex.join([str(helper), "hook"]))
    merge_hooks(data, owned, shlex.join([str(helper), "hook"]) if not uninstall else None)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = root / "backups" / stamp
    backup.mkdir(parents=True)
    (root / "host").mkdir(exist_ok=True)
    config = root / "install.json"
    originals = {p: p.read_bytes() if p.exists() else None for p in [*paths.values(), hooks, config]}
    for path, content in originals.items():
        if content is not None:
            (backup / path.name).write_bytes(content)
    # Preserve device settings when moving an existing source installation into the app.
    for job in previous.values():
        old_root = job.get("WorkingDirectory")
        if old_root and not (root / ".local/device.json").exists():
            settings = Path(old_root) / ".local/device.json"
            if settings.exists():
                write_file(root / ".local/device.json", settings.read_bytes())
    domain = f"gui/{os.getuid()}"

    def stop(label):
        if subprocess.run(["launchctl", "print", domain + "/" + label], capture_output=True).returncode == 0:
            subprocess.run(["launchctl", "bootout", domain + "/" + label], check=True, capture_output=True)

    running = [label for label in labels if subprocess.run(
        ["launchctl", "print", domain + "/" + label], capture_output=True).returncode == 0]
    try:
        for label in labels:
            stop(label)
        write_file(hooks, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())
        for label, path in paths.items():
            if uninstall:
                path.unlink(missing_ok=True)
            else:
                write_file(path, plistlib.dumps(new_jobs[label]))
        if uninstall:
            config.unlink(missing_ok=True)
        else:
            write_file(config, json.dumps({"serial_number": serial, "codex": codex, "app": str(app)}).encode())
            for path in paths.values():
                subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True, capture_output=True)
    except Exception as exc:
        for label in labels:
            stop(label)
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                write_file(path, content)
        for label in running:
            subprocess.run(["launchctl", "bootstrap", domain, str(paths[label])], capture_output=True)
        raise RuntimeError(f"安装失败，已恢复原配置；备份：{backup}；{exc}") from exc
    print(f"{'后台服务已移除' if uninstall else '安装成功，请在 Codex Settings → Hooks 信任更新后的 hooks'}。备份：{backup}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "install", "uninstall", "daemon", "quota", "bridge", "hook"))
    args, rest = parser.parse_known_args()
    root, app = data_root(), app_path()
    os.environ["AGENTCORE_LIGHT_HOME"] = str(root)
    (root / "host").mkdir(parents=True, exist_ok=True)
    if app:
        os.environ["AGENTCORE_LIGHT_RENDERER"] = str(app / "Contents/MacOS/AgentCoreLight")
    if args.action == "doctor":
        config = json.loads((root / "install.json").read_text()) if (root / "install.json").exists() else {}
        print(json.dumps({"devices": devices(), "codex": config.get("codex") or discover_codex(),
                          "serial_number": config.get("serial_number"), "configured": bool(config),
                          "data_root": str(root)}, ensure_ascii=False))
        return 0
    if args.action in ("install", "uninstall"):
        setup = argparse.ArgumentParser()
        setup.add_argument("--serial-number")
        setup.add_argument("--codex", default=discover_codex())
        setup.add_argument("--app", type=Path, default=app)
        options = setup.parse_args(rest)
        configure(options.app, options.serial_number, options.codex, args.action == "uninstall")
        return 0
    sys.argv = [sys.argv[0], *rest]
    if args.action == "daemon":
        from light_daemon import run_daemon
        run_daemon()
    elif args.action == "quota":
        if "--codex" not in rest:
            config = json.loads((root / "install.json").read_text())
            sys.argv.extend(["--codex", config["codex"]])
        from sync_weekly_quota import main as sync
        return sync()
    elif args.action == "bridge":
        from codex_light_serial import main as bridge
        bridge()
    elif args.action == "hook":
        from codex_light_hook import main as hook
        try:
            hook()
        except Exception as exc:
            print(str(exc), file=sys.stderr)  # A disconnected lamp must never interrupt Codex.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
