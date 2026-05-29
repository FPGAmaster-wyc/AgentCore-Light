# 排障指南

## 1. `/hooks` 全是 0

现象：`Installed=0 Active=0`  
处理：

1. 确认 `hooks.json` 路径正确（项目内或全局）
2. 重启 Codex 会话
3. 会话输入 `/hooks`，按提示 trust/enable
4. 检查 JSON schema 是否匹配当前 Codex 版本

---

## 2. 灯一直停在 IDLE

现象：Codex 在工作，但灯不变。  
处理：

1. 确认 daemon 是否在运行（`127.0.0.1:37637` 监听）
2. 运行手动命令测试：
   - `py -3 host/codex_light_serial.py send THINKING`
3. 查看日志：
   - `host/codex_light_hook.log`
   - `host/codex_light.log`

---

## 3. 串口占用

现象：打开 COM37 失败。  
原因：Serial Monitor / 其它脚本占用了串口。  
处理：关闭 Arduino Serial Monitor、关闭其他串口程序，只保留 daemon。

---

## 4. OLED 显示正确但 Token 不准

当前系统没有稳定读取官方“剩余额度百分比”的本地字段。  
建议：

1. 使用手动同步脚本：
   - `powershell -File host/set_token_percent.ps1 15`
2. 自动估算仅作为辅助，不应视为计费精确值。

---

## 5. 退出 daemon

在 daemon 终端窗口按：

```text
Ctrl + C
```
