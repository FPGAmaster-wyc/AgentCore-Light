# 快速上手（Windows）

## 1. 烧录固件

1. Arduino IDE 安装以下库：
   - `Adafruit NeoPixel`
   - `Adafruit SSD1306`
   - `Adafruit GFX Library`
2. 选择板卡：`ESP32-C3 Dev Module`
3. 打开并上传：`firmware/esp32c3_codex_status_light.ino`
4. 串口波特率：`115200`

---

## 2. 安装主机端依赖

```powershell
cd codex-agent-status-light
pip install -r requirements.txt
```

---

## 3. 启动串口 daemon（必须）

```powershell
powershell -ExecutionPolicy Bypass -File .\host\start_codex_light_daemon.ps1
```

正常会看到：

```text
Codex light daemon started: COM37 @ 115200, tcp 127.0.0.1:37637
```

这个窗口保持打开。

---

## 4. 手动连通性测试

新开一个 PowerShell：

```powershell
cd codex-agent-status-light
py -3 .\host\codex_light_serial.py send THINKING
py -3 .\host\codex_light_serial.py send WRITING
py -3 .\host\codex_light_serial.py send RUNNING
py -3 .\host\codex_light_serial.py send DONE
py -3 .\host\codex_light_serial.py send TOKEN:75
py -3 .\host\codex_light_serial.py send IDLE
```

---

## 5. 配置 Codex hooks

将 `hooks/hooks.json.example` 复制到你的 hooks 配置位置并启用。  
项目内方式（推荐）：

```text
<repo>/.codex/hooks.json
```

全局方式（可选）：

```text
C:\Users\<你的用户名>\.codex\hooks.json
```

然后重启 Codex，会话里输入 `/hooks` 检查 Installed/Active 是否非 0。

---

## 6. Token 百分比同步

### 手动精确同步（推荐）

```powershell
powershell -ExecutionPolicy Bypass -File .\host\set_token_percent.ps1 15
```

### 自动估算同步（可选）

默认关闭。  
要开启，设置环境变量：

```powershell
setx CODEX_TOKEN_AUTO_ESTIMATE 1
```

估算基于本地 `tokens_used`，不是官方剩余额度精确值。
