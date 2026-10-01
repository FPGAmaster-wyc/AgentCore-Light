import AppKit

// Native menu-bar controls; all hardware access remains in the Python service.
final class LightMenu: NSObject, NSApplicationDelegate {
    let root: String
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    let connection = NSMenuItem(title: "正在连接服务…", action: nil, keyEquivalent: "")
    let activity = NSMenuItem(title: "状态：—", action: nil, keyEquivalent: "")
    let quota = NSMenuItem(title: "周剩余：—", action: nil, keyEquivalent: "")
    let updated = NSMenuItem(title: "尚未同步额度", action: nil, keyEquivalent: "")
    let threads = NSMenuItem(title: "任务颜色 · 每项轮播 5 秒", action: nil, keyEquivalent: "")
    let feedback = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    let power = NSMenuItem(title: "关闭灯光", action: #selector(togglePower), keyEquivalent: "")
    var enabled = true
    var refreshing = false
    var timer: Timer?
    var brightnessItems: [NSMenuItem] = []
    let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/agentcore-host").path
    var bundled: Bool { FileManager.default.isExecutableFile(atPath: helper) }

    init(root: String) { self.root = root; super.init() }

    func applicationDidFinishLaunching(_ notification: Notification) {
        item.button?.image = NSImage(systemSymbolName: "lightbulb", accessibilityDescription: "AgentCore 状态灯")
        item.button?.toolTip = "AgentCore 状态灯"
        for row in [connection, activity, quota, updated] { menu.addItem(row) }
        threads.submenu = NSMenu(); menu.addItem(threads)
        menu.addItem(.separator())
        power.target = self; menu.addItem(power)
        let brightness = NSMenuItem(title: "亮度", action: nil, keyEquivalent: "")
        let levels = NSMenu()
        for level in [0, 5, 10, 16, 25, 50, 75, 100] {
            let row = NSMenuItem(title: "\(level)%", action: #selector(control(_:)), keyEquivalent: "")
            row.target = self; row.representedObject = "BRIGHTNESS:\(level)"
            levels.addItem(row); brightnessItems.append(row)
        }
        brightness.submenu = levels; menu.addItem(brightness)
        add("重新连接设备", #selector(control(_:)), "RECONNECT")
        add("立即同步周额度", #selector(syncQuota), nil)
        menu.addItem(.separator())
        if bundled {
            add("安装 / 更新后台服务…", #selector(setup), nil)
            add("停止并移除后台服务…", #selector(uninstall), nil)
        }
        feedback.isHidden = true; menu.addItem(feedback)
        add("打开运行日志", #selector(openLogs), nil)
        add("退出菜单栏（服务继续运行）", #selector(quit), nil)
        item.menu = menu
        refresh()
        timer = Timer(timeInterval: 5, target: self, selector: #selector(refresh), userInfo: nil, repeats: true)
        RunLoop.main.add(timer!, forMode: .common)
        if bundled {
            run(["doctor"]) { ok, text in
                if ok, let data = text.data(using: .utf8),
                   let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   value["configured"] as? Bool != true { self.setup() }
            }
        }
    }

    func add(_ title: String, _ action: Selector, _ value: String?) {
        let row = NSMenuItem(title: title, action: action, keyEquivalent: "")
        row.target = self; row.representedObject = value; menu.addItem(row)
    }

    func run(_ arguments: [String], completion: @escaping (Bool, String) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            let process = Process()
            if self.bundled {
                process.executableURL = URL(fileURLWithPath: self.helper)
                process.arguments = arguments
            } else {
                process.executableURL = URL(fileURLWithPath: self.root + "/.venv/bin/python")
                let script = arguments.first == "quota" ? "sync_weekly_quota.py" : "codex_light_serial.py"
                process.arguments = [self.root + "/host/" + script] + arguments.dropFirst()
            }
            let output = Pipe(); process.standardOutput = output; process.standardError = output
            do {
                try process.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let text = String(data: data, encoding: .utf8) ?? ""
                DispatchQueue.main.async { completion(process.terminationStatus == 0, text) }
            } catch {
                DispatchQueue.main.async { completion(false, error.localizedDescription) }
            }
        }
    }

    @objc func refresh() {
        guard !refreshing else { return }; refreshing = true
        run(["bridge", "status"]) { ok, text in
            self.refreshing = false
            guard ok, let data = text.data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.connection.title = "服务不可用 · 请检查后台任务"
                self.item.button?.title = "离线"
                self.activity.title = "状态：未知"; self.quota.title = "周剩余：未知"
                self.updated.title = "未能获取最新状态"
                self.threads.submenu?.removeAllItems()
                return
            }
            let connected = value["connected"] as? Bool ?? false
            self.connection.title = connected ? "设备已连接" : "设备断开 · 自动重连中"
            let names = ["IDLE":"空闲", "THINKING":"思考", "WRITING":"写入", "RUNNING":"执行",
                         "DONE":"完成", "ERROR":"错误", "NEED_CONFIRM":"等待确认", "OFF":"已关闭"]
            let state = value["state"] as? String ?? "—"
            self.activity.title = "状态：\(names[state] ?? state) · \(value["sessions"] as? Int ?? 0) 个会话"
            self.threads.submenu?.removeAllItems()
            let rows = value["threads"] as? [[String: Any]] ?? []
            for thread in rows {
                let slot = thread["slot"] as? Int
                let colorName = thread["color_name"] as? String ?? ""
                let title = thread["title"] as? String ?? "未知任务"
                let status = thread["state"] as? String ?? ""
                let label = slot.map { "任务\($0) · \(colorName)" } ?? "等待轮播位"
                let row = NSMenuItem(title: "\(label) · \(title.prefix(40)) · \(names[status] ?? status)", action: nil, keyEquivalent: "")
                row.toolTip = title + "\n" + (thread["id"] as? String ?? "")
                if let hex = thread["color"] as? String, let rgb = UInt32(hex, radix: 16) {
                    row.image = NSImage(size: NSSize(width: 12, height: 12), flipped: false) { rect in
                        NSColor(srgbRed: CGFloat((rgb >> 16) & 255)/255,
                                green: CGFloat((rgb >> 8) & 255)/255,
                                blue: CGFloat(rgb & 255)/255, alpha: 1).setFill()
                        NSBezierPath(ovalIn: rect.insetBy(dx: 1, dy: 1)).fill()
                        return true
                    }
                }
                self.threads.submenu?.addItem(row)
            }
            let total = value["threads_total"] as? Int ?? 0
            if rows.isEmpty || total > rows.count {
                self.threads.submenu?.addItem(NSMenuItem(title: rows.isEmpty ? "暂无活动任务" : "另有 \(total - rows.count) 个任务", action: nil, keyEquivalent: ""))
            }
            if value["firmware_threads"] as? Bool != true {
                self.threads.submenu?.addItem(NSMenuItem(title: "当前固件使用汇总灯效", action: nil, keyEquivalent: ""))
            }
            let stale = value["quota_stale"] as? Bool ?? true
            if let percent = value["quota"] as? Int {
                self.quota.title = "周剩余：\(percent)%" + (stale ? " · 已过期" : "")
                self.item.button?.title = connected ? "\(percent)%" + (stale ? "!" : "") : "离线"
            } else {
                self.quota.title = "周剩余：尚未同步"; self.item.button?.title = connected ? "—" : "离线"
            }
            if let at = value["quota_at"] as? Double {
                let formatter = DateFormatter(); formatter.dateFormat = "MM-dd HH:mm:ss"
                self.updated.title = "更新于 " + formatter.string(from: Date(timeIntervalSince1970: at))
            }
            self.enabled = value["enabled"] as? Bool ?? true
            self.power.title = self.enabled ? "关闭灯光" : "开启灯光"
            let brightness = value["brightness"] as? Int ?? 16
            for row in self.brightnessItems {
                row.state = row.representedObject as? String == "BRIGHTNESS:\(brightness)" ? .on : .off
            }
        }
    }

    @objc func togglePower() { command(enabled ? "OFF" : "ON") }
    @objc func control(_ sender: NSMenuItem) {
        if let value = sender.representedObject as? String { command(value) }
    }
    func command(_ value: String) {
        run(["bridge", "send", value]) { ok, text in
            self.feedback.title = ok ? "操作已完成" : String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(90))
            self.feedback.isHidden = false; self.refresh()
        }
    }
    @objc func syncQuota() {
        feedback.title = "正在同步周额度…"; feedback.isHidden = false
        let codex = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
        run(bundled ? ["quota"] : ["quota", "--codex", codex]) { ok, _ in
            self.feedback.title = ok ? "周额度已更新" : "同步失败 · 请查看运行日志"
            self.refresh()
        }
    }
    @objc func setup() {
        run(["doctor"]) { ok, text in
            guard ok, let data = text.data(using: .utf8),
                  let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                self.showMessage("无法检查安装环境", text); return
            }
            let devices = value["devices"] as? [[String: String]] ?? []
            guard !devices.isEmpty else {
                self.showMessage("请连接 ESP32-C3", "使用支持数据传输的 USB 线连接 v3 状态灯，然后从菜单选择“安装 / 更新后台服务”。"); return
            }
            let alert = NSAlert()
            alert.messageText = "安装 AgentCore Light 后台服务"
            alert.informativeText = "将备份并更新本项目的登录项与 Codex hooks。退出菜单栏后仍会同步。不会烧录固件。请先将应用移到 Applications，安装后保持应用位置不变。"
            alert.addButton(withTitle: "安装"); alert.addButton(withTitle: "取消")
            let serial = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 420, height: 26))
            serial.addItems(withTitles: devices.map { "\($0["serial_number"] ?? "") · \($0["port"] ?? "")" })
            if let known = value["serial_number"] as? String,
               let index = devices.firstIndex(where: { $0["serial_number"] == known }) { serial.selectItem(at: index) }
            let codex = NSTextField(string: value["codex"] as? String ?? "")
            codex.placeholderString = "Codex 可执行文件的完整路径"
            let stack = NSStackView(views: [NSTextField(labelWithString: "设备"), serial,
                                          NSTextField(labelWithString: "Codex 可执行文件"), codex])
            stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 8
            stack.frame = NSRect(x: 0, y: 0, width: 420, height: 110)
            codex.widthAnchor.constraint(equalToConstant: 420).isActive = true
            alert.accessoryView = stack
            NSApp.activate(ignoringOtherApps: true)
            guard alert.runModal() == .alertFirstButtonReturn else { return }
            self.feedback.title = "正在安装后台服务…"; self.feedback.isHidden = false
            self.run(["install", "--serial-number", devices[serial.indexOfSelectedItem]["serial_number"]!,
                      "--codex", codex.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)]) { success, message in
                self.showMessage(success ? "安装完成" : "安装失败", message)
                self.refresh()
            }
        }
    }
    @objc func uninstall() {
        let alert = NSAlert()
        alert.messageText = "停止并移除后台服务？"
        alert.informativeText = "移除本项目的登录项和 hooks，停止状态与额度同步。保留配置、日志和备份。"
        alert.addButton(withTitle: "移除"); alert.addButton(withTitle: "取消")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        run(["uninstall"]) { ok, text in
            self.showMessage(ok ? "后台服务已移除" : "移除失败", text); self.refresh()
        }
    }
    func showMessage(_ title: String, _ message: String) {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = message
        NSApp.activate(ignoringOtherApps: true); alert.runModal()
    }
    @objc func openLogs() { NSWorkspace.shared.open(URL(fileURLWithPath: root + "/host/device.log")) }
    @objc func quit() { NSApplication.shared.terminate(nil) }
}

// Render a Unicode title using macOS fonts; the ESP32 only receives a monochrome bitmap.
if CommandLine.arguments.count == 3 && ["--render-title", "--render-scroll-title"].contains(CommandLine.arguments[1]) {
    let scrolling = CommandLine.arguments[1] == "--render-scroll-title"
    let font = NSFont.systemFont(ofSize: 12)
    let measured = Int(ceil((CommandLine.arguments[2] as NSString).size(withAttributes: [.font: font]).width)) + 2
    let width = scrolling ? min(2048, max(92, measured)) : 92
    let height = 14, stride = (width + 7) / 8
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: width * 4, bitsPerPixel: 32)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.black.setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = scrolling && width > 92 ? .left : .center
    paragraph.lineBreakMode = .byTruncatingTail
    (CommandLine.arguments[2] as NSString).draw(in: NSRect(x: 0, y: 0, width: width, height: height),
        withAttributes: [.font: font, .foregroundColor: NSColor.white,
                         .paragraphStyle: paragraph])
    NSGraphicsContext.restoreGraphicsState()
    var bytes = [UInt8](repeating: 0, count: stride * height)
    for y in 0..<height {
        for x in 0..<width {
            if let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB),
               color.redComponent > 0.5 {
                bytes[y * stride + x / 8] |= UInt8(0x80 >> (x % 8))
            }
        }
    }
    print((scrolling ? "\(width):" : "") + bytes.map { String(format: "%02X", $0) }.joined())
    exit(0)
}

let packaged = FileManager.default.isExecutableFile(atPath:
    Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/agentcore-host").path)
guard CommandLine.arguments.count == 2 || packaged else { fatalError("Expected project root argument") }
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let root = packaged ? FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/AgentCore Light").path : CommandLine.arguments[1]
let delegate = LightMenu(root: root)
app.delegate = delegate
app.run()
