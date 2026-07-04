const body = document.body;
const connLabel = document.getElementById("connLabel");
const currentModelLabel = document.getElementById("currentModelLabel");
const countLabel = document.getElementById("countLabel");
const heroConnectionModeValue = document.getElementById("heroConnectionModeValue");
const effectLabel = document.getElementById("effectLabel");
const eventLabel = document.getElementById("eventLabel");
const agentLabel = document.getElementById("agentLabel");
const sessionLabel = document.getElementById("sessionLabel");
const modeLabel = document.getElementById("modeLabel");
const stateLabel = document.getElementById("stateLabel");
const durationLabel = document.getElementById("durationLabel");
const uptimeLabel = document.getElementById("uptimeLabel");
const connectionStateValue = document.getElementById("connectionStateValue");
const latencyValue = document.getElementById("latencyValue");
const signalValue = document.getElementById("signalValue");
const firmwareValue = document.getElementById("firmwareValue");
const connectionModeValue = document.getElementById("connectionModeValue");
const connectionModeDescription = document.getElementById("connectionModeDescription");
const bleControlRow = document.getElementById("bleControlRow");
const bleConnectButton = document.getElementById("bleConnectButton");
const bleReconnectButton = document.getElementById("bleReconnectButton");
const bleDisconnectButton = document.getElementById("bleDisconnectButton");
const bleConnectionLabel = document.getElementById("bleConnectionLabel");
const bleConnectionHint = document.getElementById("bleConnectionHint");
const deviceIdLabel = document.getElementById("deviceIdLabel");
const deviceBadgeLabel = document.getElementById("deviceBadgeLabel");
const themeIndicator = document.getElementById("themeIndicator");
const statusDescription = document.getElementById("statusDescription");
const historyList = document.getElementById("historyList");
const logList = document.getElementById("logList");
const historyStateInline = document.getElementById("historyStateInline");
const historyTimeInline = document.getElementById("historyTimeInline");
const historyEventInline = document.getElementById("historyEventInline");
const historySessionInline = document.getElementById("historySessionInline");
const historySourceInline = document.getElementById("historySourceInline");
const historyDurationInline = document.getElementById("historyDurationInline");
const activeSessionBindState = document.getElementById("activeSessionBindState");
const activeSessionModel = document.getElementById("activeSessionModel");
const activeSessionBindMode = document.getElementById("activeSessionBindMode");
const activeSessionModelValue = document.getElementById("activeSessionModelValue");
const activeSessionStatus = document.getElementById("activeSessionStatus");
const activeSessionStateValue = document.getElementById("activeSessionStateValue");
const activeSessionId = document.getElementById("activeSessionId");
const activeSessionPath = document.getElementById("activeSessionPath");
const activeSessionEvent = document.getElementById("activeSessionEvent");
const activeSessionUpdated = document.getElementById("activeSessionUpdated");
const activeSessionCard = document.getElementById("activeSessionCard");
const activeSessionEmpty = document.getElementById("activeSessionEmpty");
const activeSessionNote = document.getElementById("activeSessionNote");
const sessionList = document.getElementById("sessionList");
const sessionListCount = document.getElementById("sessionListCount");
const sessionDebug = document.getElementById("sessionDebug");
const copySessionPathBtn = document.getElementById("copySessionPathBtn");
const unbindSessionBtn = document.getElementById("unbindSessionBtn");
const rebindSessionBtn = document.getElementById("rebindSessionBtn");
const detailDrawer = document.getElementById("detailDrawer");
const drawerBackdrop = document.getElementById("drawerBackdrop");
const drawerClose = document.getElementById("drawerClose");
const lamps = [...document.querySelectorAll(".lamp")];

const APP_STARTED_AT = Date.now();
const HISTORY_LIMIT = 12;
const SIGNAL_STRENGTH = "98%";
const FIRMWARE_VERSION = "v1.0.3";
const DEVICE_ID = "ESP32-C3-01";

const TEXT_MAP = {
  all: "自动",
  claude: "Claude",
  codex: "Codex",
  cursor: "Cursor",
  manual: "手动模拟",
  none: "无",
  unknown: "未知",
  off: "熄灭",
  idle_green: "空闲",
  success: "成功",
  busy: "执行中",
  ai: "生成中",
  thinking: "分析中",
  working_yellow: "工作中",
  wait_user: "等待确认",
  error_red: "错误",
  auto: "自动",
  SessionStart: "空闲状态",
  SessionEnd: "熄灭",
  UserPromptSubmit: "分析 / 生成",
  PreToolUse: "工具调用前",
  PostToolUse: "工具调用后",
  PermissionRequest: "等待确认",
  PreCompact: "压缩前",
  PostCompact: "压缩后",
  SubagentStart: "子代理启动",
  SubagentStop: "子代理结束",
  Stop: "任务完成",
  StopFailure: "错误异常",
  Notification: "通知",
  Elicitation: "提问等待",
  hook: "Hook 事件",
  manual_log: "手动操作",
  session_end: "会话结束",
  config: "配置更新"
};

const THEME_MAP = {
  idle_green: "idle",
  success: "idle",
  working_yellow: "thinking",
  wait_user: "waiting",
  error_red: "error",
  off: "off"
};

const STATUS_DESCRIPTION_MAP = {
  idle: "设备空闲待命，绿色呼吸灯表示系统已连接并等待新任务。",
  thinking: "设备处于分析阶段，跑马灯正在快速轮询当前任务。",
  ai: "设备处于生成阶段，跑马灯以更柔和的节奏持续推进。",
  busy: "设备正在执行命令，黄色状态灯以慢闪方式提示执行中。",
  waiting: "设备正在等待用户确认或权限批准，黄色灯效提示需要人工介入。",
  success: "任务已成功完成，绿色常亮后将自动回到空闲呼吸灯。",
  error: "设备检测到错误或异常，红色告警灯提示当前流程中断。",
  off: "设备未输出灯效，等待状态信号。"
};

let currentStatusKey = "";
let currentStatusSince = Date.now();
let currentStatusSnapshot = {
  state: "熄灭",
  event: "熄灭",
  source: "无",
  session: "自动",
  theme: "off",
  at: Date.now(),
  durationMs: 0
};
let stateHistory = [];
let lastLatencyMs = null;
let successResetTimer = null;
let latestPayload = null;
let selectedAgentScope = "all";
let selectedConnectionMode = "serial";
let followMode = "auto";
let selectedFollowSessionId = "";
let currentDisplayPayload = null;
const frontendSessions = new Map();
const bleClient = typeof AgentBleClient === "function" ? new AgentBleClient() : null;
const deviceTransport = typeof DeviceTransport === "function"
  ? new DeviceTransport({ mode: selectedConnectionMode, bleClient })
  : null;
let bleConnectionState = bleClient?.isSupported() ? "未连接 BLE" : "当前浏览器不支持 BLE";

if (bleClient) {
  bleClient.onDisconnected = () => {
    bleConnectionState = "BLE已断开";
    updateBleControls("设备已断开，可重新连接。");
  };
}

const REAL_AGENT_SCOPES = new Set(["all", "codex", "claude", "cursor"]);
const CONNECTION_MODE_LABELS = {
  bluetooth: "蓝牙",
  serial: "串口",
  wifi: "WiFi"
};
const CONNECTION_MODE_DESCRIPTIONS = {
  bluetooth: "适合无线近距离连接",
  serial: "适合开发调试",
  wifi: "适合局域网控制"
};

deviceIdLabel.textContent = DEVICE_ID;
deviceBadgeLabel.textContent = DEVICE_ID;
signalValue.textContent = SIGNAL_STRENGTH;
firmwareValue.textContent = FIRMWARE_VERSION;
connectionModeValue.textContent = CONNECTION_MODE_LABELS[selectedConnectionMode];
heroConnectionModeValue.textContent = CONNECTION_MODE_LABELS[selectedConnectionMode];
connectionModeDescription.textContent = CONNECTION_MODE_DESCRIPTIONS[selectedConnectionMode];

function updateBleControls(hintText = "") {
  if (!bleControlRow) return;

  const isBluetoothMode = selectedConnectionMode === "bluetooth";
  bleControlRow.hidden = !isBluetoothMode;
  if (!isBluetoothMode) {
    return;
  }

  bleConnectionLabel.textContent = bleConnectionState;
  if (hintText) {
    bleConnectionHint.textContent = hintText;
  } else if (!bleClient?.isSupported()) {
    bleConnectionHint.textContent = "请使用支持 Web Bluetooth 的 Chrome / Edge HTTPS 页面。";
  } else if (bleClient?.device?.name) {
    bleConnectionHint.textContent = `当前设备：${bleClient.device.name}`;
  } else {
    bleConnectionHint.textContent = "请选择 AgentCore-Light 或 SignalLight-C3";
  }

  const connected = !!bleClient?.device?.gatt?.connected;
  bleConnectButton.hidden = connected;
  bleReconnectButton.hidden = !connected && !bleClient?.device;
  bleDisconnectButton.hidden = !connected;
  bleConnectButton.disabled = !bleClient?.isSupported();
  bleReconnectButton.disabled = !bleClient?.isSupported();
  bleDisconnectButton.disabled = !connected;
}

function localize(value) {
  if (value == null || value === "") return "无";
  return TEXT_MAP[value] || String(value);
}

function localizeLogKind(value) {
  if (value === "manual") return TEXT_MAP.manual_log;
  if (value === "session-end") return TEXT_MAP.session_end;
  return localize(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeAgentScope(value) {
  const scope = String(value || "all").toLowerCase();
  if (REAL_AGENT_SCOPES.has(scope)) return scope;
  return "all";
}

function selectedModelName() {
  return localize(selectedAgentScope);
}

function syncModelDisplay() {
  currentModelLabel.textContent = selectedModelName();
  document.querySelectorAll("[data-scope]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scope === selectedAgentScope);
  });
}

function syncConnectionModeDisplay() {
  connectionModeValue.textContent = CONNECTION_MODE_LABELS[selectedConnectionMode] || "串口";
  heroConnectionModeValue.textContent = CONNECTION_MODE_LABELS[selectedConnectionMode] || "串口";
  connectionModeDescription.textContent = CONNECTION_MODE_DESCRIPTIONS[selectedConnectionMode] || CONNECTION_MODE_DESCRIPTIONS.serial;
  if (deviceTransport) {
    deviceTransport.setMode(selectedConnectionMode);
  }
  document.querySelectorAll("[data-connection-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.connectionMode === selectedConnectionMode);
  });
  updateBleControls();
}

function updateFollowModeButtons() {
  document.querySelectorAll("[data-follow-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.followMode === followMode);
  });
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatAgo(seconds) {
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  return `${Math.floor(seconds / 3600)} 小时前`;
}

function formatTime(value) {
  if (!value) return "--:--:--";
  return new Date(value).toLocaleTimeString();
}

function formatThemeLabel(theme) {
  const map = {
    idle: "空闲",
    thinking: "分析中",
    ai: "生成中",
    busy: "执行中",
    waiting: "等待确认",
    success: "成功",
    error: "错误",
    off: "熄灭"
  };
  return map[theme] || "待机";
}

function themeToDeviceStatus(theme) {
  const map = {
    idle: "idle",
    thinking: "thinking",
    ai: "ai",
    busy: "busy",
    waiting: "wait_confirm",
    success: "success",
    error: "error",
    off: "off"
  };
  return map[theme] || "off";
}

async function pushDeviceStatus(theme) {
  if (!deviceTransport || selectedConnectionMode !== "bluetooth") {
    return;
  }

  try {
    await deviceTransport.sendStatus(themeToDeviceStatus(theme));
    if (bleClient?.device?.gatt?.connected) {
      bleConnectionState = "已连接 BLE";
      updateBleControls();
    }
  } catch (error) {
    bleConnectionState = "BLE发送失败";
    updateBleControls(error?.message || "BLE 写入失败，请重新连接。");
  }
}

function deriveTheme(payload) {
  const event = String(payload.winner_event || "");
  const effect = String(payload.effect_id || "");
  const normalized = `${event} ${effect}`.toLowerCase();
  if (event === "Stop" || effect === "success") return "success";
  if (event === "StopFailure" || effect === "error_red") return "error";
  if (
    event === "PermissionRequest" ||
    event === "Elicitation" ||
    effect === "wait_user" ||
    normalized.includes("wait_confirm") ||
    normalized.includes("waiting") ||
    normalized.includes("confirm")
  ) return "waiting";
  if (event === "PreToolUse" || event === "PostToolUse" || event === "busy") return "busy";
  if (event === "SubagentStart" || event === "SubagentStop" || event === "PreCompact" || event === "PostCompact" || event === "ai") {
    return "ai";
  }
  if (
    event === "UserPromptSubmit" ||
    event === "thinking" ||
    effect === "working_yellow"
  ) {
    return "thinking";
  }
  return THEME_MAP[effect] || "off";
}

function setLampState(lamp, classes = []) {
  lamp.className = lamp.className
    .split(" ")
    .filter((token) => !["off", "on", "breathe", "blink", "blink-fast", "seq-fast", "seq-slow", "seq-1", "seq-2", "seq-3"].includes(token))
    .join(" ");
  lamp.classList.add(...classes);
}

function renderLamps(theme) {
  lamps.forEach((lamp) => {
    setLampState(lamp, ["off"]);
  });

  const [greenLamp, amberLamp, redLamp] = lamps;
  switch (theme) {
    case "idle":
      setLampState(greenLamp, ["green", "breathe"]);
      break;
    case "thinking":
      setLampState(greenLamp, ["green", "seq-fast", "seq-1"]);
      setLampState(amberLamp, ["amber", "seq-fast", "seq-2"]);
      setLampState(redLamp, ["red", "seq-fast", "seq-3"]);
      break;
    case "ai":
      setLampState(greenLamp, ["green", "seq-slow", "seq-1"]);
      setLampState(amberLamp, ["amber", "seq-slow", "seq-2"]);
      setLampState(redLamp, ["red", "seq-slow", "seq-3"]);
      break;
    case "busy":
      setLampState(amberLamp, ["amber", "blink"]);
      break;
    case "waiting":
      setLampState(amberLamp, ["amber", "on"]);
      break;
    case "success":
      setLampState(greenLamp, ["green", "on"]);
      break;
    case "error":
      setLampState(redLamp, ["red", "blink-fast"]);
      break;
    default:
      break;
  }
}

function buildVisualPayload(payload, theme) {
  if (theme !== "success") return payload;
  return {
    ...payload,
    effect_id: "success",
    effect_name: "success",
    winner_event: "Stop",
    display_state: "success"
  };
}

function isManualSession(session) {
  if (!session) return false;
  return (
    session.agent === "manual" ||
    session.sid === "__manual__" ||
    session.sid === "(manual)" ||
    String(session.cwd || "").toLowerCase().includes("(manual)")
  );
}

function normalizeSession(session) {
  const now = Date.now();
  const id = String(
    session.sid ||
    session.sessionId ||
    session.session_id ||
    session.id ||
    session.conversationId ||
    session.conversation_id ||
    session.conversation ||
    ""
  ).trim();
  if (!id) return null;
  const ageValue = Number(session.age_s ?? session.ageSeconds ?? session.age ?? 0);
  const explicitUpdate =
    session.lastUpdate ||
    session.lastSeen ||
    session.updatedAt ||
    session.updated_at ||
    session.timestamp ||
    session.at;
  const parsedUpdate = explicitUpdate ? Date.parse(explicitUpdate) : NaN;
  const lastUpdate = Number.isFinite(parsedUpdate)
    ? parsedUpdate
    : now - Math.max(0, ageValue * 1000);
  const agentSource = String(session.agent || session.app || session.model || session.client || "unknown").toLowerCase();
  const origin = String(session.source || "unknown").toLowerCase();  // local / ssh / unknown
  const path = session.cwd || session.workspace || session.projectPath || session.project_path || session.sessionPath || session.path || "";
  const event =
    session.event ||
    session.lastEvent ||
    session.last_event ||
    session.eventName ||
    session.hookEvent ||
    session.winner_event ||
    "off";
  const effectId =
    session.effect_id ||
    session.effectId ||
    session.status ||
    session.currentStatus ||
    session.eventState ||
    session.state ||
    "off";
  return {
    id,
    sid: id,
    source: agentSource,
    agent: agentSource,
    origin,
    path,
    cwd: path,
    status: effectId,
    event,
    lastEvent: event,
    lastUpdate,
    age_s: Math.max(0, Math.floor((now - lastUpdate) / 1000)),
    effect_id: effectId
  };
}

function updateFrontendSessions(payload) {
  const hasSessionPayload =
    payload.sessions != null ||
    payload.activeSessions != null ||
    payload.active_sessions != null;
  if (!hasSessionPayload) return;

  const rawSessions = payload.sessions || payload.activeSessions || payload.active_sessions || [];
  const incoming = Array.isArray(rawSessions)
    ? rawSessions
    : Object.values(rawSessions || {});
  frontendSessions.clear();
  incoming.forEach((session) => {
    const normalized = normalizeSession(session);
    if (normalized) frontendSessions.set(normalized.id, normalized);
  });
}

function sessionSortValue(session) {
  return Number(session.lastUpdate || 0);
}

function allSessions() {
  return [...frontendSessions.values()].sort((a, b) => sessionSortValue(b) - sessionSortValue(a));
}

function realSessions() {
  return allSessions().filter((session) => !isManualSession(session));
}

function latestSession() {
  return realSessions()[0] || null;
}

function manualTestSession() {
  return allSessions().find(isManualSession) || null;
}

function followedSession() {
  if (followMode === "test") return manualTestSession();
  if (followMode === "manual") {
    return selectedFollowSessionId ? frontendSessions.get(selectedFollowSessionId) || null : null;
  }
  return latestSession();
}

function payloadFromSession(session, basePayload = {}) {
  const effectId = session?.effect_id || session?.status || "off";
  const event = session?.event || session?.lastEvent || "off";
  const payload = {
    ...basePayload,
    effect_id: effectId,
    effect_name: effectId,
    winner_event: event,
    agent: session?.agent || session?.source || "none",
    selected_session_id: followMode === "manual" ? selectedFollowSessionId : "",
    controlling_session_id: session?.id || "",
    display_state: deriveTheme({ effect_id: effectId, winner_event: event }),
    sessions: basePayload.sessions || allSessions().map((item) => ({
      sid: item.id,
      agent: item.agent,
      event: item.event,
      effect_id: item.effect_id,
      cwd: item.cwd,
      age_s: Math.max(0, Math.floor((Date.now() - item.lastUpdate) / 1000))
    }))
  };
  return payload;
}

function emptyFollowPayload(basePayload = {}) {
  return {
    ...basePayload,
    effect_id: "off",
    effect_name: "off",
    winner_event: followMode === "test" ? "manual_log" : "off",
    agent: followMode === "test" ? "manual" : "none",
    selected_session_id: selectedFollowSessionId,
    controlling_session_id: "",
    display_state: "off"
  };
}

function chooseDisplayPayload(payload, options = {}) {
  if (options.fromTimer) return payload;
  const session = followedSession();
  if (session) return payloadFromSession(session, payload);
  if (
    payload.agent === "manual" &&
    payload.device_status &&
    payload.device_status !== "off"
  ) {
    return payload;
  }
  return emptyFollowPayload(payload);
}

function historyPayloadFromIncoming(payload) {
  const sourceSession = latestSession();
  return sourceSession ? payloadFromSession(sourceSession, payload) : payload;
}

function scheduleSuccessReset() {
  if (successResetTimer) {
    clearTimeout(successResetTimer);
  }
  successResetTimer = setTimeout(() => {
    const basePayload = currentDisplayPayload || latestPayload;
    if (!basePayload) return;
    const idlePayload = {
      ...basePayload,
      effect_id: "idle_green",
      effect_name: "idle_green",
      winner_event: "SessionStart",
      display_state: "idle"
    };
    renderStatus(idlePayload, { fromTimer: true, keepHistory: true });
    successResetTimer = null;
  }, 5000);
}

function pushHistoryItem(now) {
  if (!currentStatusKey) return;
  stateHistory.unshift({
    state: currentStatusSnapshot.state,
    event: currentStatusSnapshot.event,
    source: currentStatusSnapshot.source,
    session: currentStatusSnapshot.session,
    theme: currentStatusSnapshot.theme,
    at: currentStatusSnapshot.at,
    durationMs: now - currentStatusSince
  });
  stateHistory = stateHistory.slice(0, HISTORY_LIMIT);
}

function syncStatusHistory(payload) {
  const nextKey = [
    payload.effect_id || "off",
    payload.winner_event || "off",
    payload.agent || "none",
    payload.controlling_session_id || "",
    payload.selected_session_id || ""
  ].join("|");

  const now = Date.now();
    const nextSnapshot = {
      state: localize(payload.effect_id) || localize(payload.effect_name),
      event: localize(payload.winner_event || payload.effect_id),
      source: localize(payload.agent),
      session: payload.selected_session_id
        ? payload.selected_session_id.slice(0, 8)
        : payload.controlling_session_id
          ? payload.controlling_session_id.slice(0, 8)
          : "自动",
      theme: payload.display_state || deriveTheme(payload),
      at: now,
      durationMs: now - currentStatusSince
    };

  if (!currentStatusKey) {
    currentStatusKey = nextKey;
    currentStatusSince = now;
    currentStatusSnapshot = nextSnapshot;
    return;
  }

  if (nextKey !== currentStatusKey) {
    pushHistoryItem(now);
    currentStatusKey = nextKey;
    currentStatusSince = now;
    currentStatusSnapshot = nextSnapshot;
    return;
  }

  currentStatusSnapshot = {
    ...currentStatusSnapshot,
    durationMs: now - currentStatusSince
  };
}

function renderHistoryInline() {
  const item = stateHistory[0] || {
    state: currentStatusSnapshot.state,
    event: currentStatusSnapshot.event,
    source: currentStatusSnapshot.source,
    session: currentStatusSnapshot.session || "自动",
    at: currentStatusSnapshot.at,
    durationMs: Date.now() - currentStatusSince
  };

  historyStateInline.textContent = item.state;
  historyTimeInline.textContent = formatTime(item.at);
  historyEventInline.textContent = `${item.source} ${item.session || "自动"} ${item.event}`;
  historySessionInline.textContent = `会话: ${item.session || "自动"}`;
  historySourceInline.textContent = `来源: ${item.source}`;
  historyDurationInline.textContent = `持续时间: ${formatDuration(item.durationMs)}`;
}

function renderHistoryDrawer() {
  if (!stateHistory.length) {
    historyList.className = "list empty";
    historyList.textContent = "还没有状态变化";
    return;
  }

  historyList.className = "list history";
  historyList.innerHTML = stateHistory.map((item) => `
    <article class="history-row ${item.theme || "off"}">
      <span class="state-dot ${item.theme || "off"}"></span>
      <div class="history-main">
        <div class="history-head">
          <strong>${item.state}</strong>
          <time>${formatTime(item.at)}</time>
        </div>
        <div class="history-meta">
          <span>${item.source} ${item.session || "自动"} ${item.event}</span>
          <span>${formatDuration(item.durationMs)}</span>
        </div>
      </div>
    </article>
  `).join("");
}

function renderLog(items) {
  if (!items.length) {
    logList.className = "list empty";
    logList.textContent = "还没有事件";
    return;
  }

  logList.className = "list";
  logList.innerHTML = items.slice(0, 12).map((item) => `
    <article class="log-row">
      <time>${formatTime(item.at)}</time>
      <span class="kind">${localizeLogKind(item.kind)}</span>
      <span class="detail" title="${item.detail}">${item.detail}</span>
      <span class="session-pill">${(item.detail.match(/[a-z0-9]{8}/i) || ["-"])[0]}</span>
    </article>
  `).join("");
}

function renderSessionList() {
  const sessions = realSessions();
  sessionListCount.textContent = `${sessions.length} 个会话`;
  sessionDebug.textContent = [
    `sessions.length = ${sessions.length}`,
    `followMode = ${followMode}`,
    `selectedSessionId = ${selectedFollowSessionId || "-"}`,
    `session ids = ${sessions.map((session) => session.id).join(", ") || "-"}`
  ].join(" | ");

  if (followMode === "test" && sessions.length) {
    sessionListCount.textContent = `${sessions.length} 个会话 · 测试状态`;
  }

  if (!sessions.length) {
    sessionList.className = "session-list empty";
    sessionList.textContent = "暂无可用会话，请确认 Codex Hook 已连接并产生事件。";
    return;
  }

  const active = followedSession();
  sessionList.className = "session-list";
  sessionList.innerHTML = sessions.map((session) => {
    const isFollowing = active?.id === session.id;
    const shortId = session.id.slice(0, 8);
    const ageSeconds = Math.max(0, Math.floor((Date.now() - session.lastUpdate) / 1000));
    const originLabel = session.origin && session.origin !== "unknown"
      ? `<span class="session-origin origin-${escapeHtml(session.origin)}">${escapeHtml(session.origin.toUpperCase())}</span>`
      : "";
    return `
      <article class="session-card ${isFollowing ? "following" : ""}" data-session-id="${escapeHtml(session.id)}">
        <div class="session-card-main">
          <div class="session-card-head">
            <strong>${escapeHtml(localize(session.agent))}</strong>
            ${originLabel}
            <span class="session-card-id">会话 ID：${escapeHtml(shortId)}</span>
          </div>
          <div class="session-card-line">
            <span>路径：</span>
            <span class="session-card-path" title="${escapeHtml(session.cwd || "（未知目录）")}">${escapeHtml(session.cwd || "（未知目录）")}</span>
          </div>
          <div class="session-card-line">
            <span>当前状态：${escapeHtml(localize(session.event || session.effect_id))}</span>
            <span>最近事件：${escapeHtml(localize(session.event))}</span>
          </div>
          <div class="session-card-line">
            <span>最后更新时间：${escapeHtml(formatAgo(ageSeconds))}</span>
            ${isFollowing ? "<span class=\"following-badge\">当前灯光跟随中</span>" : ""}
          </div>
        </div>
        <button type="button" class="follow-session-button ${isFollowing ? "active" : ""}" data-follow-session="${escapeHtml(session.id)}">
          跟随此会话
        </button>
      </article>
    `;
  }).join("");
}

function getActiveSession(payload) {
  const sessions = payload.sessions || [];
  const selected = payload.selected_session_id
    ? sessions.find((session) => session.sid === payload.selected_session_id) || null
    : null;
  const controlling = payload.controlling_session_id
    ? sessions.find((session) => session.sid === payload.controlling_session_id) || null
    : null;
  return selected || controlling || sessions[0] || null;
}

function renderActiveSession(payload) {
  const active = followedSession();
  const sessions = realSessions();
  const manualMode = followMode === "test" || isManualSession(active);
  const bindingMode = followMode === "test"
    ? "测试状态"
    : followMode === "manual"
      ? "指定会话"
      : "自动跟随";
  const modelName = active && selectedAgentScope === "all"
    ? localize(active.agent)
    : selectedModelName();
  const stateName = active ? localize(active.event || active.effect_id) : "等待中";

  updateFollowModeButtons();
  renderSessionList();

  if (!active) {
    activeSessionCard.hidden = true;
    activeSessionCard.classList.remove("manual-session", "real-session");
    activeSessionEmpty.hidden = false;
    activeSessionBindState.textContent = bindingMode;
    activeSessionBindMode.textContent = `当前模式：${bindingMode}`;
    activeSessionModel.textContent = selectedModelName();
    activeSessionModelValue.textContent = selectedModelName();
    activeSessionStatus.textContent = "等待中";
    activeSessionStateValue.textContent = "等待中";
    activeSessionId.textContent = "-";
    activeSessionPath.textContent = "-";
    activeSessionEvent.textContent = "-";
    activeSessionUpdated.textContent = "-";
    activeSessionEmpty.textContent = followMode === "test"
      ? "当前为测试状态，真实 AI 会话不会控制灯光。"
      : "暂无跟随会话，请选择一个会话，或切换为自动跟随。";
    activeSessionNote.hidden = true;
    copySessionPathBtn.hidden = true;
    unbindSessionBtn.disabled = true;
    rebindSessionBtn.disabled = !sessions.length;
    return;
  }

  activeSessionCard.hidden = false;
  activeSessionEmpty.hidden = true;
  activeSessionCard.classList.toggle("manual-session", manualMode);
  activeSessionCard.classList.toggle("real-session", !manualMode);
  activeSessionBindState.textContent = bindingMode;
  activeSessionBindMode.textContent = `当前模式：${bindingMode}`;
  activeSessionModel.textContent = modelName;
  activeSessionModelValue.textContent = modelName;
  activeSessionStatus.textContent = stateName;
  activeSessionStateValue.textContent = stateName;
  activeSessionId.textContent = active.id;
  activeSessionId.title = active.id;
  activeSessionPath.textContent = active.cwd || "（未知目录）";
  activeSessionPath.title = active.cwd || "（未知目录）";
  activeSessionEvent.textContent = localize(active.event);
  activeSessionUpdated.textContent = `${formatAgo(Math.max(0, Math.floor((Date.now() - active.lastUpdate) / 1000)))} 更新`;
  activeSessionNote.hidden = followMode !== "test";
  if (followMode === "test") {
    activeSessionNote.textContent = "当前为测试状态，真实 AI 会话不会控制灯光。";
  } else {
    activeSessionNote.textContent = "";
  }
  copySessionPathBtn.hidden = !active.cwd;
  unbindSessionBtn.disabled = followMode === "auto";
  rebindSessionBtn.disabled = !active || followMode === "manual";

  unbindSessionBtn.onclick = async () => {
    followMode = "auto";
    selectedFollowSessionId = "";
    renderActiveSession(payload);
    if (latestPayload) renderStatus(latestPayload, { keepHistory: true });
  };

  rebindSessionBtn.onclick = async () => {
    followMode = "manual";
    selectedFollowSessionId = active.id;
    renderActiveSession(payload);
    if (latestPayload) renderStatus(latestPayload, { keepHistory: true });
  };

  copySessionPathBtn.onclick = async () => {
    const path = active.cwd || "";
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      copySessionPathBtn.textContent = "已复制";
      setTimeout(() => {
        copySessionPathBtn.textContent = "复制路径";
      }, 1200);
    } catch {
      const temp = document.createElement("textarea");
      temp.value = path;
      document.body.appendChild(temp);
      temp.select();
      document.execCommand("copy");
      temp.remove();
      copySessionPathBtn.textContent = "已复制";
      setTimeout(() => {
        copySessionPathBtn.textContent = "复制路径";
      }, 1200);
    }
  };
}

function syncControlSelection(payload) {
  const theme = payload.display_state || deriveTheme(payload);
  const controlEffectByTheme = {
    idle: "idle_green",
    success: "idle_green",
    thinking: "working_yellow",
    ai: "working_yellow",
    busy: "working_yellow",
    waiting: "wait_user",
    error: "error_red",
    off: "off"
  };
  const activeEffect = controlEffectByTheme[theme] || payload.effect_id;

  document.querySelectorAll("[data-effect]").forEach((button) => {
    button.classList.toggle("active", button.dataset.effect === activeEffect);
  });

  document.querySelectorAll("[data-scope]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scope === selectedAgentScope);
  });
}

function renderStatus(payload, options = {}) {
  if (!options.fromTimer) {
    latestPayload = payload;
  }

  updateFrontendSessions(payload);

  if (!options.keepHistory) {
    syncStatusHistory(historyPayloadFromIncoming(payload));
  }

  const selectedPayload = chooseDisplayPayload(payload, options);
  const theme = selectedPayload.display_state || deriveTheme(selectedPayload);
  const visualPayload = buildVisualPayload(selectedPayload, theme);
  currentDisplayPayload = visualPayload;
  selectedAgentScope = normalizeAgentScope(visualPayload.agent_filter);
  body.dataset.theme = theme;
  connLabel.textContent = "已连接";
  connectionStateValue.textContent = "已连接";
  currentModelLabel.textContent = selectedModelName();
  if (effectLabel) {
    effectLabel.textContent = localize(visualPayload.effect_id) || localize(visualPayload.effect_name);
  }
  eventLabel.textContent = localize(visualPayload.winner_event || visualPayload.effect_id);
  stateLabel.textContent = localize(visualPayload.effect_id) || localize(visualPayload.effect_name);
  agentLabel.textContent = localize(visualPayload.agent);
  sessionLabel.textContent = visualPayload.controlling_session_id
    ? visualPayload.controlling_session_id.slice(0, 8)
    : "自动";
  modeLabel.textContent = followMode === "test"
    ? "测试状态"
    : followMode === "manual"
      ? "指定会话"
      : "自动跟随";
  themeIndicator.textContent = formatThemeLabel(theme);
  statusDescription.textContent = STATUS_DESCRIPTION_MAP[theme] || STATUS_DESCRIPTION_MAP.off;
  countLabel.textContent = String(visualPayload.visible_session_count ?? (visualPayload.sessions || []).length);

  renderLamps(theme);
  renderActiveSession(visualPayload);
  renderLog(visualPayload.log || []);
  renderHistoryInline();
  renderHistoryDrawer();
  syncControlSelection(visualPayload);
  syncConnectionModeDisplay();
  pushDeviceStatus(theme);

  if (!options.fromTimer && theme === "success") {
    scheduleSuccessReset();
  } else if (theme !== "success" && successResetTimer) {
    clearTimeout(successResetTimer);
    successResetTimer = null;
  }
}

function refreshLiveMetrics() {
  uptimeLabel.textContent = formatDuration(Date.now() - APP_STARTED_AT);
  durationLabel.textContent = formatDuration(Date.now() - currentStatusSince);
  historyDurationInline.textContent = `持续时间: ${formatDuration(Date.now() - currentStatusSince)}`;
  latencyValue.textContent = lastLatencyMs == null ? "-- ms" : `${lastLatencyMs} ms`;
}

async function post(path, bodyValue) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: typeof bodyValue === "string" ? bodyValue : JSON.stringify(bodyValue)
  });
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || "request failed");
  }
  return response;
}

async function measureLatency() {
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("status request failed");
    }
    await response.json();
    lastLatencyMs = Math.max(1, Math.round(performance.now() - startedAt));
    connLabel.textContent = "已连接";
    connectionStateValue.textContent = "已连接";
  } catch {
    connLabel.textContent = "重连中";
    connectionStateValue.textContent = "重连中";
  }
  refreshLiveMetrics();
}

function openDrawer() {
  detailDrawer.classList.add("open");
  detailDrawer.setAttribute("aria-hidden", "false");
  drawerBackdrop.hidden = false;
}

function closeDrawer() {
  detailDrawer.classList.remove("open");
  detailDrawer.setAttribute("aria-hidden", "true");
  drawerBackdrop.hidden = true;
}

document.querySelectorAll("[data-event]").forEach((button) => {
  button.addEventListener("click", async () => {
    followMode = "test";
    selectedFollowSessionId = "";
    updateFollowModeButtons();
    await fetch("/event", { method: "POST", body: button.dataset.event });
  });
});

document.querySelectorAll("[data-scope]").forEach((button) => {
  button.addEventListener("click", async () => {
    const scope = normalizeAgentScope(button.dataset.scope);
    selectedAgentScope = scope;
    syncModelDisplay();
    if (latestPayload) {
      renderActiveSession(latestPayload);
    }

    await post("/api/agent-filter", { scope });
  });
});

document.querySelectorAll("[data-connection-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    selectedConnectionMode = button.dataset.connectionMode || "serial";
    syncConnectionModeDisplay();
  });
});

bleConnectButton?.addEventListener("click", async () => {
  if (!bleClient) return;
  bleConnectionState = "连接中";
  updateBleControls("正在请求蓝牙设备访问权限...");
  try {
    await deviceTransport.connectBluetooth();
    bleConnectionState = "已连接 BLE";
    updateBleControls();
    const theme = currentDisplayPayload?.display_state || deriveTheme(currentDisplayPayload || { effect_id: "off", winner_event: "off" });
    await pushDeviceStatus(theme);
  } catch (error) {
    bleConnectionState = "BLE连接失败";
    updateBleControls(error?.message || "连接失败，请重试。");
  }
});

bleReconnectButton?.addEventListener("click", async () => {
  if (!bleClient) return;
  bleConnectionState = "重连中";
  updateBleControls("正在重新连接蓝牙设备...");
  try {
    await deviceTransport.connectBluetooth();
    bleConnectionState = "已连接 BLE";
    updateBleControls();
    const theme = currentDisplayPayload?.display_state || deriveTheme(currentDisplayPayload || { effect_id: "off", winner_event: "off" });
    await pushDeviceStatus(theme);
  } catch (error) {
    bleConnectionState = "BLE重连失败";
    updateBleControls(error?.message || "重连失败，请重新选择设备。");
  }
});

bleDisconnectButton?.addEventListener("click", () => {
  if (!deviceTransport) return;
  deviceTransport.disconnectBluetooth();
  bleConnectionState = "BLE已断开";
  updateBleControls("连接已断开，可重新连接。");
});

document.querySelectorAll("[data-follow-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    followMode = button.dataset.followMode || "auto";
    if (followMode !== "manual") {
      selectedFollowSessionId = "";
    }
    updateFollowModeButtons();
    if (latestPayload) {
      renderStatus(latestPayload, { keepHistory: true });
    } else {
      renderActiveSession({});
    }
  });
});

sessionList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-follow-session]");
  if (!button) return;
  selectedFollowSessionId = button.dataset.followSession || "";
  followMode = "manual";
  updateFollowModeButtons();
  if (latestPayload) {
    renderStatus(latestPayload, { keepHistory: true });
  } else {
    renderActiveSession({});
  }
});

["historyToggleTop", "historyToggleBottom"].forEach((id) => {
  const trigger = document.getElementById(id);
  trigger?.addEventListener("click", openDrawer);
});

drawerClose.addEventListener("click", closeDrawer);
drawerBackdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

const es = new EventSource("/stream");
es.onmessage = (message) => {
  renderStatus(JSON.parse(message.data));
  refreshLiveMetrics();
};
es.onerror = () => {
  connLabel.textContent = "重连中";
  connectionStateValue.textContent = "重连中";
};

const initialLoadStart = performance.now();
fetch("/api/status")
  .then((response) => response.json())
  .then((payload) => {
    lastLatencyMs = Math.max(1, Math.round(performance.now() - initialLoadStart));
    renderStatus(payload);
    refreshLiveMetrics();
  })
  .catch(() => {
    connLabel.textContent = "离线";
    connectionStateValue.textContent = "离线";
  });

setInterval(refreshLiveMetrics, 1000);
setInterval(measureLatency, 15000);
syncModelDisplay();
syncConnectionModeDisplay();
updateFollowModeButtons();
renderSessionList();
