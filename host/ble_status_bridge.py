import argparse
import asyncio
import json
import sys
import time
import urllib.error

from bleak import BleakClient, BleakScanner

from codex_status_bridge import (
    COMMAND_RESEND_SECONDS,
    DEFAULT_API_URL,
    DEFAULT_INTERVAL,
    IDLE_RESEND_SECONDS,
    acquire_instance_lock,
    fetch_status,
    map_status_to_command,
)

BLE_CHAR_UUID = "12345678-1234-5678-1234-56789abcdef1"
BLE_RETRY_SECONDS = 3.0
DEVICE_NAMES = ("AgentCore-Light", "SignalLight-C3")


async def find_device():
    devices = await BleakScanner.discover(timeout=8.0)
    for device in devices:
        name = device.name or ""
        if any(token in name for token in DEVICE_NAMES):
            return device
    return None


async def send_ble_status(client, command):
    payload = json.dumps({"status": command}).encode("utf-8")
    await client.write_gatt_char(BLE_CHAR_UUID, payload, response=False)


async def bridge_loop(client, api_url, interval, once):
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
                await send_ble_status(client, command)
                print(f"[ble-send] {command:<12} event={winner_event} effect={effect_id}")
                last_command = command
                last_send_at = now
            else:
                print(f"[ble-keep] {command:<12} event={winner_event} effect={effect_id}")
        except urllib.error.URLError as exc:
            print(f"[warn] 无法访问状态接口: {exc}")
        except Exception as exc:
            print(f"[fatal] BLE 写入失败: {exc}")
            return 1

        if once:
            return 0

        await asyncio.sleep(interval)


def parse_args():
    parser = argparse.ArgumentParser(description="Bridge Codex web status to AgentCore-Light over BLE.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Status API URL")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Fetch and send only once")
    return parser.parse_args()


async def run(args):
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        print("状态桥已在运行，当前进程退出。")
        return 0

    print(f"正在监听 {args.api_url}（BLE 模式）")

    try:
        while True:
            device = await find_device()
            if device is None:
                print("未找到 BLE 设备 AgentCore-Light，稍后重试。")
                if args.once:
                    return 1
                await asyncio.sleep(BLE_RETRY_SECONDS)
                continue

            try:
                async with BleakClient(device.address, timeout=20.0) as client:
                    print(f"已连接 BLE {device.name} ({device.address})")
                    result = await bridge_loop(client, args.api_url, args.interval, args.once)
            except Exception as exc:
                print(f"BLE 连接失败：{exc}")
                if args.once:
                    return 1
                await asyncio.sleep(BLE_RETRY_SECONDS)
                continue

            if args.once:
                return result

            print("BLE 连接已断开，正在尝试重连。")
            await asyncio.sleep(BLE_RETRY_SECONDS)
    finally:
        instance_lock.close()


def main():
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
