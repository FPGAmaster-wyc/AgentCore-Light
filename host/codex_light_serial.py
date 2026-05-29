import argparse
import socket
import sys
import time
from pathlib import Path

import serial


PORT = "COM37"
BAUD_RATE = 115200
HOST = "127.0.0.1"
TCP_PORT = 37637
AUTO_IDLE_SECONDS = 45

COMMAND_ALIASES = {
    "idle": "IDLE",
    "green": "IDLE",
    "thinking": "THINKING",
    "think": "THINKING",
    "ai": "WRITING",
    "writing": "WRITING",
    "write": "WRITING",
    "busy": "RUNNING",
    "running": "RUNNING",
    "run": "RUNNING",
    "success": "DONE",
    "done": "DONE",
    "error": "ERROR",
    "alarm": "ERROR",
}


def normalize_command(value):
    command = value.strip()
    if not command:
        raise ValueError("empty command")

    if command.upper().startswith("TOKEN:"):
        return command.upper()

    return COMMAND_ALIASES.get(command.lower(), command.upper())


def send_direct(command):
    with serial.Serial(PORT, BAUD_RATE, timeout=1) as ser:
        time.sleep(0.05)
        ser.write((command + "\n").encode("utf-8"))
        ser.flush()


def send_via_daemon(command):
    with socket.create_connection((HOST, TCP_PORT), timeout=0.3) as sock:
        sock.sendall((command + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        reply = sock.recv(64).decode("utf-8", errors="replace").strip()
        return reply == "OK"


def send_command(command, prefer_daemon=True, fallback_direct=True):
    normalized = normalize_command(command)

    if prefer_daemon:
        try:
            if send_via_daemon(normalized):
                return normalized
        except OSError:
            pass

    if not fallback_direct:
        raise ConnectionError("Codex light daemon is not running")

    send_direct(normalized)
    return normalized


def run_daemon():
    log_path = Path(__file__).with_name("codex_light.log")
    last_command = "IDLE"
    last_command_at = time.monotonic()

    with serial.Serial(PORT, BAUD_RATE, timeout=1) as ser:
        time.sleep(1.0)
        ser.write(b"IDLE\n")
        ser.flush()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((HOST, TCP_PORT))
            server.listen(8)
            server.settimeout(1.0)

            print(f"Codex light daemon started: {PORT} @ {BAUD_RATE}, tcp {HOST}:{TCP_PORT}")

            while True:
                if (
                    last_command in ("THINKING", "WRITING", "RUNNING")
                    and time.monotonic() - last_command_at > AUTO_IDLE_SECONDS
                ):
                    ser.write(b"IDLE\n")
                    ser.flush()
                    last_command = "IDLE"
                    last_command_at = time.monotonic()
                    with log_path.open("a", encoding="utf-8") as log_fp:
                        log_fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} IDLE auto-timeout\n")

                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue

                with conn:
                    raw = conn.recv(128).decode("utf-8", errors="replace").strip()
                    try:
                        command = normalize_command(raw)
                        ser.write((command + "\n").encode("utf-8"))
                        ser.flush()
                        last_command = command
                        last_command_at = time.monotonic()
                        conn.sendall(b"OK\n")
                        with log_path.open("a", encoding="utf-8") as log_fp:
                            log_fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {command}\n")
                    except Exception as exc:
                        conn.sendall(f"ERR {exc}\n".encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Codex Agent light serial bridge")
    subparsers = parser.add_subparsers(dest="command")

    send_parser = subparsers.add_parser("send", help="send one command")
    send_parser.add_argument("value", help="IDLE, THINKING, WRITING, RUNNING, DONE, ERROR, TOKEN:x")
    send_parser.add_argument("--direct", action="store_true", help="open COM port directly")

    subparsers.add_parser("daemon", help="keep COM port open and receive local commands")

    args = parser.parse_args()

    if args.command == "daemon":
        run_daemon()
        return

    if args.command == "send":
        sent = send_command(args.value, prefer_daemon=not args.direct)
        print(f"已发送：{sent}")
        return

    parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("退出")
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
