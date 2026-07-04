# Cursor Hooks 安装（AgentCore-Light）

Cursor IDE 原生 Hooks：事件写入本地队列（毫秒级返回），由 `host/hook-queue-worker.js` 异步 POST 到状态服务。

## 安装

```bash
node host/install-cursor-hooks.js
```

脚本会：

1. 复制 `hooks/cursor/cursor-hook-fast.sh` → `~/.cursor/hooks/agentcore-light.sh`
2. 合并 `~/.cursor/hooks.json`（不覆盖你的其他 hook）

## 运行链路

```bash
./host/start-server.sh          # :8787 状态服务
./host/start-queue-worker.sh    # 消费 ~/.cursor/hooks/queue
cd host && python3 ble_status_bridge.py   # 可选：BLE 控灯
```

## SSH 远程 Cursor

Linux 上使用 `hooks/cursor/cursor-hook-remote.sh`（标记 `source=ssh`），配合 `host/hook-queue-worker.py` 与 SSH `RemoteForward`。详见贡献者文档：

https://github.com/gjc1202/agent-light-dev/blob/master/docs/SSH-SETUP.md

## 参考

示例配置：`hooks/cursor-hooks.json.example`

Contributed from https://github.com/gjc1202/agent-light-dev
