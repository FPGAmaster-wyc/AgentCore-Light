# Cursor 状态服务（host/server.js）

Node.js 状态聚合服务：接收 Cursor Hooks（经队列 worker 转发）、合并多窗口会话、提供 Dashboard 与 `/api/status`。

## 依赖

- Node.js 18+（`brew install node`）
- Python 桥接见 [BLE-BRIDGE_CN.md](./BLE-BRIDGE_CN.md)

## 启动

```bash
# 终端 1：状态服务
./host/start-server.sh

# 终端 2：Cursor hook 队列消费者（需先安装 hooks，见 hooks/cursor/）
./host/start-queue-worker.sh

# 终端 3：BLE 桥接（可选）
cd host && python3 ble_status_bridge.py
```

浏览器打开：http://127.0.0.1:8787

## Hook 安装

见 [CURSOR-HOOKS_CN.md](./CURSOR-HOOKS_CN.md)（Cursor hooks PR）。

## 配置

灯效映射：`host/data/config.json`（首次运行可从 `host/config.default.json` 复制）。

Contributed from https://github.com/gjc1202/agent-light-dev
