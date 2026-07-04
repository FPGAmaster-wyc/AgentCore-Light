import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request

import serial
from serial.tools import list_ports


DEFAULT_API_URL = "http://127.0.0.1:8787/api/status"
DEFAULT_BAUD_RATE = 115200
DEFAULT_INTERVAL = 0.5
INSTANCE_LOCK_PORT = 37638
SERIAL_RETRY_SECONDS = 2.0
COMMAND_RESEND_SECONDS = 2.0
IDLE_RESEND_SECONDS = 30.0


def score_port(port):
    text = " ".join(
        [
            port.device or "",
            port.description or "",
            port.manufacturer or "",
            port.hwid or "",
        ]
    ).lower()

    score = 0
    if "1a86" in text or "ch340" in text or "ch341" in text:
        return -1000
    if "espressif" in text or "303a" in text:
        score += 200
    if "esp32" in text:
        score += 100
    if "jtag" in text:
        score += 80
    if "usbmodem" in text:
        score += 60
    if "usb" in text:
        score += 20
    if "bluetooth" in text or "bth" in text:
        score -= 100
    return score


def detect_port():
    ports = list(list_ports.comports())
    if not ports:
        return None

    ranked = sorted(ports, key=score_port, reverse=True)
    return ranked[0].device


def open_serial(port, baud_rate):
    ser = serial.Serial(port=port, baudrate=baud_rate, timeout=0.3, write_timeout=1)
    time.sleep(0.5)
    try:
        if ser.in_waiting:
            ser.read(ser.in_waiting)
    except serial.SerialException:
        pass
    return ser


def acquire_instance_lock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", INSTANCE_LOCK_PORT))
    except OSError:
        sock.close()
        return None
    sock.listen(1)
    return sock


def fetch_status(api_url):
    with urllib.request.urlopen(api_url, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def map_status_to_command(payload):
    normalized_status = str(payload.get("device_status") or payload.get("display_state") or "").strip().lower()
    if normalized_status == "off":
        return "off"
    if normalized_status in {"idle", "thinking", "ai", "busy", "success", "error", "unknown"}:
        return normalized_status
    if normalized_status in {"waiting", "wait_confirm", "confirm"}:
        return "wait_confirm"

    winner_event = str(payload.get("winner_event") or "").strip()
    effect_id = str(payload.get("effect_id") or "").strip()

    if winner_event in {"PermissionRequest", "Notification", "Elicitation", "PreToolUse:AskUserQuestion"}:
        return "wait_confirm"
    if winner_event == "StopFailure":
        return "error"
    if winner_event == "Stop":
        return "success"
    if winner_event in {
        "UserPromptSubmit",
        "PreCompact",
        "PostCompact",
        "SubagentStart",
        "SubagentStop",
    }:
        return "thinking"
    if winner_event == "PostToolUse":
        return "thinking"
    if winner_event == "PreToolUse":
        return "busy"
    if winner_event == "SessionStart":
        return "idle"
    if winner_event in {"SessionEnd", "off"}:
        return "off"

    if effect_id == "wait_user":
        return "wait_confirm"
    if effect_id == "error_red":
        return "error"
    if effect_id == "working_yellow":
        return "thinking"
    if effect_id == "idle_green":
        return "idle"
    if effect_id == "off":
        return "off"

    return "idle"


def bridge_loop(ser, api_url, interval, once):
    last_command = None
    last_send_at = 0.0
    while True:
        try:
            payload = fetch_status(api_url)
            command = map_status_to_command(payload)
            winner_event = payload.get("winner_event", "")
            effect_id = payload.get("effect_id", "")
            now = time.monotonic()

            resend_interval = IDLE_RESEND_SECONDS if command == "idle" else COMMAND_RESEND_SECONDS
            if command != last_command or now - last_send_at >= resend_interval:
                ser.write((command + "\n").encode("utf-8"))
                ser.flush()
                print(f"[send] {command:<12} event={winner_event} effect={effect_id}")
                last_command = command
                last_send_at = now
            else:
                print(f"[keep] {command:<12} event={winner_event} effect={effect_id}")
        except urllib.error.URLError as exc:
            print(f"[warn] 无法访问状态接口: {exc}")
        except json.JSONDecodeError as exc:
            print(f"[warn] 状态接口返回了无效 JSON: {exc}")
        except serial.SerialException as exc:
            print(f"[fatal] 串口写入失败: {exc}")
            return 1

        if once:
            return 0

        time.sleep(interval)


def parse_args():
    parser = argparse.ArgumentParser(description="Bridge Codex web status to ESP32 traffic light.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Status API URL")
    parser.add_argument("--port", default="", help="Serial port, auto-detect when omitted")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD_RATE, help="Serial baud rate")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Fetch and send only once")
    return parser.parse_args()


def main():
    args = parse_args()
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        print("串口桥已在运行，当前进程退出。")
        return 0

    print(f"正在监听 {args.api_url}")

    try:
        while True:
            port = args.port or detect_port()
            if not port:
                print("未检测到可用串口，稍后重试。")
                if args.once:
                    return 1
                time.sleep(SERIAL_RETRY_SECONDS)
                continue

            try:
                ser = open_serial(port, args.baud)
            except Exception as exc:
                print(f"打开串口失败：{port} - {exc}")
                if args.once:
                    return 1
                time.sleep(SERIAL_RETRY_SECONDS)
                continue

            print(f"已连接 {port}，波特率 {args.baud}")
            try:
                result = bridge_loop(ser, args.api_url, args.interval, args.once)
            finally:
                ser.close()

            if args.once:
                return result

            print("串口连接已断开，正在尝试重连。")
            time.sleep(SERIAL_RETRY_SECONDS)
    finally:
        instance_lock.close()


if __name__ == "__main__":
    sys.exit(main())
