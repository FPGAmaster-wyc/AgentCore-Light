# macOS v3 完整适配

这是本项目的 macOS 自定义适配，不是厂商 Windows 控制台。
运行依赖仍只有 Python 和 pyserial；菜单栏使用 macOS AppKit，无第三方 GUI 框架。
独立 App 已内置上述运行依赖，无需源码目录；安装、使用及构建方法见 [README](../README.md#macos-独立-app-使用方法)。以下命令面向源码安装，配置位于项目目录；独立 App 的配置与日志位于 `~/Library/Application Support/AgentCore Light/`。

## 首次安装

需要 macOS、Python 3、Xcode Command Line Tools（`xcode-select --install`）及已登录的 Codex。
从本 fork 克隆后，在项目根目录执行：

```sh
git clone https://github.com/flytianwu/AgentCore-Light.git
cd AgentCore-Light
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m serial.tools.list_ports -v
```

从端口列表中找到目标 ESP32-C3 的 USB 序列号（VID/PID 为 `303A:1001`），然后安装：

```sh
.venv/bin/python host/install_macos.py \
  --serial-number '<你的设备 USB 序列号>' \
  --codex '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
```

Codex 路径需按实际安装位置调整；上面是已验证的桌面应用捆绑路径。安装器会创建三个用户 LaunchAgent、编译菜单栏应用，并合并全局 hooks；先备份现有配置，不会自动烧录设备。历史服务标识 `com.garyjiang.agentcore-light*` 为兼容现有安装而保留。
首次安装后在 Codex Settings → Hooks 信任新增 hooks。所有本机项目共用该服务。

手动打开菜单栏（不是独立窗口）：

```sh
open "$PWD/.local/AgentCore Light.app" --args "$PWD"
```

下文 `.local` 编译命令面向已经配置本地 Arduino 工具链的环境；新机器也可用 Arduino IDE，安装 ESP32 3.3.12、Adafruit NeoPixel 1.15.5、Adafruit SSD1306 2.5.17、Adafruit GFX 1.12.6 和 Adafruit BusIO 1.17.4，然后打开 `firmware/agentcore_light_v3_macos/agentcore_light_v3_macos.ino`。板型 ESP32C3 Dev Module，USB CDC On Boot 开启，Flash 为 4MB / DIO / 80MHz。v3 接线为 LED GPIO4，OLED SDA8 / SCL9；先核对实际硬件并备份 Flash，再烧录。

## 服务与协议

- `host/light_daemon.py` 是 macOS 的唯一串口持有者；仅连接安装时指定的 USB
  序列号以及 VID/PID `303A:1001`，并检查 `PONG:AGENTCORE-LIGHT-V3`。
- 断线或回执超时后，每 5 秒重新发现端口。重连恢复亮度、最后成功获取的额度和当前状态。
- 状态/额度/亮度写入必须收到设备匹配回执；每 5 秒读取 `STATUS` 检查设备。
- 本机 TCP `127.0.0.1:37637` 继续支持原有文本状态、`TOKEN:x` 和 `BRIGHTNESS:x`。
  `OK` 表示设备回执成功（相同设置已确认时不重复发送）。
- JSON 会话事件返回 `QUEUED`，表示主机接受事件；不代表已经显示在设备上。
  包含 `session_id`、`turn_id`、`event`、`state`，不传递对话正文或工具输出。
- `HOST_STATUS` 返回主机快照；`RECONNECT` 请求重新连接；`OFF` 持久关闭灯光，
  `ON` 恢复自动显示。hooks 不会取消用户手动关闭。
- 原 `codex_light_serial.py daemon` 保留为旧版桥接入口；不要与新版服务同时运行。

## 多会话规则

显示优先级为：等待确认 → 明确错误 → 写入 → 执行 → 思考。
其他会话仍工作时，单个会话 `Stop` 不会显示全局完成。
错误提示持续约 10 秒后回思考；全部完成显示约 10 秒后回空闲。
`Interrupt` / `SessionEnd` 清理对应会话。旧轮次的迟到事件不会结束新轮次。
同状态不重复发送，普通状态切换间隔至少 350 毫秒；确认、错误、关灯立即处理。

具名会话超过 30 分钟没有事件会过期，防止丢失终止 hook 后永久占灯；
没有会话信息的旧文本工作状态仍沿用 45 秒自动空闲。
这不是精确的 Codex 任务存活检测，超过 30 分钟完全没有 hook 的长操作可能显示空闲。
同一会话内并行工具仍以最近的事件为准。

## 菜单栏

本地构建产物为 `.local/AgentCore Light.app`，由当前用户 LaunchAgent 登录时启动。
菜单提供连接与工作状态、周剩余额度、最后更新时间、亮度、开关、重连和手动额度同步。
退出菜单栏不会停止后台设备服务或额度同步。

## 固件能力（当前 MAC4，兼容 MAC1–MAC3）

源码：`firmware/agentcore_light_v3_macos/agentcore_light_v3_macos.ino`，基于厂商 v3
客户交付包的 `agentcore_light_v3_neopixel_oled.ino`，保留原灯效、引脚和亮度上限。
原始来源：https://light.buildfpga.com/light-v3/source-files/v3%20%E5%AE%A2%E6%88%B7%E4%BA%A4%E4%BB%98%E5%8C%85.zip

- OLED 显示 `Week xx%`；未获取额度时显示 `Week --%`。
- `*` 表示额度已过期（最后成功获取超过 15 分钟）；保留数值供参考。
- 超过 20 秒没有主机通信时，标题显示 `Host offline`。
- `OFF` 同时关闭灯环与 OLED；通信和后续状态恢复仍可用。
- 支持 `STALE:0/1` 回执；当前 `STATUS` 追加 `FW:MAC4`（MAC1 起支持额度过期标记）。
  电脑端识别能力后才发送新指令，兼容原版 v3 固件。

## 本机配置、重装与恢复

`.local/device.json` 保存亮度、开关和额度时间，按临时文件替换方式写入。
`.local/backups/` 保存配置和原设备完整 Flash。该目录不入 Git，请另行保留重要备份。
日志：`host/device.log` 最多轮转 3 个 1 MB 备份；额度日志仍在 `host/quota.*.log`。

重装电脑端（从项目根目录；会备份并更新当前用户登录项、合并 hooks）：

```sh
.venv/bin/python host/install_macos.py --serial-number '<你的设备 USB 序列号>' --codex '<Codex 可执行文件绝对路径>'
```

安装器不会烧录固件。新增的 hooks 需要在 Codex Settings → Hooks 中信任。
不要手动同时启动两个串口服务。

编译固件（工具链局限于 `.local`，Arduino ESP32 3.3.12）：

```sh
.local/tools/arduino-cli compile --config-file .local/arduino-cli.yaml \
  --fqbn 'esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashMode=dio,FlashFreq=80,FlashSize=4M' \
  --build-path .local/firmware-build --output-dir .local/firmware-output \
  firmware/agentcore_light_v3_macos
```

烧录或恢复前必须停止设备 LaunchAgent，确认设备身份及 4 MB 备份哈希。
将备份或生成的 merged bin 写到地址 `0x0` 后验证，再恢复服务；不要烧录旧仓库的蜂鸣器版固件。

## 验收

自动测试：`.venv/bin/python -m unittest discover -s host -p 'test_*.py' -v`。

人工验证：
1. 点击 macOS 菜单栏灯泡，调整亮度、关灯、开灯，检查灯环与 OLED。
2. 同一 Codex 账号下开两个项目会话，让一个完成、另一个继续执行，观察不会提前全局完成。
3. 拔下再插入 USB（或更换接口），等待数秒，检查恢复亮度、额度及状态。
4. 对照 Codex 周额度；超过 15 分钟未成功同步时应出现 `*`。
5. 电脑睡眠/唤醒后检查自动恢复。自动化测试不替代这些实体硬件观察。

## 多任务分色轮播（MAC2）

整圈灯每次展示一个任务，每个任务展示 5 秒后切换到下一个。任务运行期间保持颜色：1 紫、2 红、3 青、4 橙、5 蓝、6 粉、7 绿、8 黄。只有一个任务时持续显示该任务。
思考使用较慢的拖尾走马灯，写入和执行使用更快的走马灯；等待确认整圈双闪，错误整圈快闪，完成常亮。颜色始终代表任务。普通 hook 更新不会重置 5 秒计时；当前任务移除后立即补到下一项。
任务完成 10 秒后释放颜色，30 分钟没有事件的任务自动清理；服务重启后重新分配颜色。目前轮播容量仍为 8 个任务，超出后按到达顺序等待空位，不挤走已有任务。菜单栏“任务颜色 · 每项轮播 5 秒”显示对应关系（最多 64 行，额外显示数量）。
菜单栏与 OLED 优先读取本机 `~/.codex/session_index.jsonl` 中当前 thread ID 对应的 `thread_name`（Chat Title），同一 ID 使用最后一条有效标题。缺失时回退到只读数据库 `state_5.sqlite` 的 `threads.title`，再回退到 ID 前缀。保留 60 秒缓存，重命名写入索引后随缓存刷新同步；忽略损坏或尚未写完的索引行，不读取对话正文。
OLED 顶部显示当前轮播任务的真实标题（支持中文，MAC4 长标题横向滚动），中间显示该任务的 THINK / WRITE / RUN / CONFIRM / ERROR / DONE，底部保留周额度。标题、状态随灯光同步切换；关闭灯光覆盖所有任务，无任务恢复额度灯效。
串口仍使用兼容的 MAC2 `THREADS:12345600,6,1,0`：八位代表八个任务的状态（0 空、1 思考、2 写入、3 执行、4 完成、5 错误、6 确认），后三项是活动、确认、溢出数量，上限 999。MAC1 或官方固件仍显示汇总状态。

手动验收：同时运行两个持续超过 10 秒的 Codex 任务，对照菜单颜色，确认整圈以第一种颜色走马灯 5 秒，再以第二种颜色展示 5 秒并循环。任务更新状态不应打断轮换。只有一个任务时保持其颜色。等待确认时在对应任务的轮播时间内整圈双闪。检查关闭/开启与周额度仍正常。


### MAC3 标题显示

Mac 菜单栏程序提供 `--render-title` 模式，使用系统字体将 Unicode 标题渲染为 92×14 单色位图（168 字节），主机缓存后通过 `TITLE:1:<336个十六进制字符>` 发送。固件 USB CDC 收发队列设为 1024 字节，串口行缓冲上限调整为 383 字符；接收标题严格校验 344 字符、任务编号及十六进制内容后原样确认。标题只在改变或设备重连时传输，轮播切换由设备本地刷新。字体渲染失败则回退 Thread N，完整任务名称仍可在菜单栏查看。
`FW:MAC3` 同时支持原 MAC2 状态帧；旧固件不会收到 TITLE 命令。没有额外 Python 包或 ESP32 中文字库依赖。
验收时同时运行两个任务，确认顶部真实标题、中央状态和轮播颜色一一对应；改变其中一个任务的状态，确认它下一次轮播显示正确状态。中文长标题应横向滚动，短标题居中，周额度及关闭/开启功能保持正常。


### 任务身份与残留清理

hook 中提供了 `transcript_path`、但没有 transcript 且本机数据库也未登记的会话，不进入灯光任务列表。这些事件暂存为待确认身份，每秒只读核对；正常新任务稍后写入数据库时自动恢复，收到 Stop / Interrupt / SessionEnd 时丢弃待确认事件，避免后台临时会话结束后出现完成灯效。待确认状态 5 分钟没有更新后丢弃。数据库不可用时不清除已有正常任务，身份未确认的新事件等待数据库恢复。未提供该字段的旧事件保留兼容行为；未来 Codex 字段变化仍需核对。
字段参考：[OpenAI Hooks 文档](https://learn.chatgpt.com/docs/hooks)。只向灯光服务传递身份字段，不读取 transcript 正文来判定是否临时会话。

hook 优先使用 thread_id，缺失时使用 session_id；同时出现两者时合并映射，避免重复计数。事件日志记录时间、任务 ID、回合 ID 和事件类型，不记录工具输入或对话正文。
后台每 30 秒只读核对本机任务数据库。已注册任务仅在最近的会话记录明确表明当前回合结束、且该记录晚于最后 hook 时清理；读取范围限于末尾 256 KB，信息不足时保留。未注册任务连续两次核对不存在且 5 分钟没有新事件才清理。数据库不可用时不执行此类清理，正常任务仍保留原有超时规则。尚未写入数据库的临时任务若静默超过 5 分钟，可能暂时从灯光列表消失，收到新事件后会恢复。


### MAC4 滚动标题

顶部仍为 92×14 像素窗口，短标题居中，长标题以每 50ms 一像素（约 20px/s）向左滚动。开始停留约 0.5 秒，末尾停留约 0.7 秒后回到开头。每个任务独立保存滚动进度，只在展示该任务时推进；切换任务不会丢失其阅读位置。状态文字、周额度不滚动，5 秒任务轮播保持不变。
Mac 使用 `--render-scroll-title` 输出 `宽度:位图十六进制`，宽度 92–2048，标题仍沿用主机 160 字符上限。极宽字符组合超过 2048 像素时仍截断。MAC4 使用 TBEGIN/TDATA/TEND 分段传输，每段最多 128 字节，全部收齐后替换标题；旧 MAC3 固件继续使用静态 TITLE 协议。固件无需中文字库。
手动验收：运行一个长标题任务，观察开头停留、向左滚动、末尾停留及回到开头；运行两个任务，确认切换回来继续原来的滚动位置，任务状态与灯光颜色仍对应。短标题应静止居中，周额度不移动。
