# macOS 真实周额度同步

安装器配置的 `com.garyjiang.agentcore-light-quota` LaunchAgent 登录后及每
5 分钟运行 `host/sync_weekly_quota.py`。它短暂启动 Codex App Server，通过
`account/rateLimits/read` 读取现有登录账号的额度，随后退出。不会创建会话或调用模型。

屏幕的 `Week xx%`（原版固件为 `Token xx%`）表示 **Codex 周额度剩余百分比**，不是剩余 Token 数量，
也不是 5 小时额度。仅选择 `codex` 桶内长度为 10080 分钟的窗口；计算方式为
`100 - usedPercent`，四舍五入为整数。优先使用 `rateLimitsByLimitId`。

同步沿用串口后台服务的 `TOKEN:x` 指令。不会直接打开串口；请保持原串口服务运行。
缺少周窗口、数据过期、接口失败或服务不可用时记录错误，不发送替代估算值。
屏幕会保留上次数值，因此断网期间可能显示旧数据。不要同时启用
`CODEX_TOKEN_AUTO_ESTIMATE`，否则原 hooks 的会话估算会覆盖真实额度。

配置位置：`~/Library/LaunchAgents/com.garyjiang.agentcore-light-quota.plist`。
它记录了当前项目路径及 ChatGPT.app 内的 Codex 可执行文件绝对路径；移动项目或
应用后需要更新该配置。此脚本的额度来源以 Codex CLI 当前登录账号为准。

从项目根目录手动同步：

```sh
.venv/bin/python host/sync_weekly_quota.py --codex /Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex
```

加 `--dry-run` 只读取额度，不更新设备。运行日志为 `host/quota.stdout.log` 和
`host/quota.stderr.log`；串口发送日志为 `host/device.log`。

停止自动同步（不影响状态灯服务）：

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.garyjiang.agentcore-light-quota.plist"
```

重新启用：

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.garyjiang.agentcore-light-quota.plist"
```

验证：

```sh
.venv/bin/python -m unittest discover -s host -p 'test_sync_weekly_quota.py' -v
```

人工验收：使用 Codex 当前登录账号，对照其周剩余额度与 OLED 的 `Week xx%`。
后台最多约 5 分钟刷新一次（Mac 睡眠时不运行）。无需重新信任状态 hooks。

菜单栏、重连、多会话协调和 MAC4 固件说明见 [macOS v3 完整适配](MACOS_V3.md)。

接口参考：https://learn.chatgpt.com/docs/app-server
