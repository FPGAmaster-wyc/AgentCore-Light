# BLE 状态桥接（host/ble_status_bridge.py）

将 HTTP 状态 API（默认 `http://127.0.0.1:8787/api/status`）轮询结果通过 BLE 写入 AgentCore-Light 设备。

## 依赖

```bash
pip install -r requirements.txt
```

需要 `bleak`（BLE）与 `pyserial`（串口桥接脚本共用）。

## 用法

```bash
cd host
python3 ble_status_bridge.py
```

可选参数：

- `--api-url` — 状态 API 地址（默认 `http://127.0.0.1:8787/api/status`）
- `--interval` — 轮询间隔秒数（默认 `0.5`）
- `--once` — 只拉取并发送一次（调试用）

## 设备名

自动扫描 BLE 名称包含 `AgentCore-Light` 或 `SignalLight-C3` 的设备。

## 串口模式

若使用 USB 串口而非 BLE，运行：

```bash
cd host
python3 codex_status_bridge.py
```

> 状态 API 由 `host/server.js` 提供（见 Cursor 集成 PR）。在仅有 Codex 串口直连模式时，可继续使用 `codex_light_serial.py`。
