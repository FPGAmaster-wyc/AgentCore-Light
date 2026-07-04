const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { URL } = require("node:url");

const PORT = Number(process.env.PORT || 8787);
const HOST = "127.0.0.1";
const APP_DIR = __dirname;
const STATIC_DIR = path.join(APP_DIR, "static");
const DATA_DIR = path.join(APP_DIR, "data");
const DEFAULT_CONFIG_PATH = path.join(APP_DIR, "config.default.json");
const CONFIG_PATH = path.join(DATA_DIR, "config.json");
const MANUAL_SID = "__manual__";
// v1.2：TTL 改为 10 分钟（之前 3 分钟太短，会和 DEGRADE_THINKING_MS=180s 抢）
// 设计：
//   - 0-30s: busy (PreToolUse) / 0-3min: thinking (PostToolUse/UerPromptSubmit)
//   - 超过上述阈值但 < TTL: degraded=true，状态显示 unknown（三色慢闪）
//   - 超过 TTL（10min）: 真正删除（认为是窗口被强关）
const SESSION_TTL_MS = 10 * 60 * 1000;
const MAX_LOG_ITEMS = 60;

const LED_MODES = { off: 0, on: 1, breathe: 2 };
const MODE_NAMES = ["off", "on", "breathe"];
const AGENT_SCOPES = new Set(["all", "claude", "codex", "cursor"]);
const CODEX_ONLY_EVENTS = new Set(["PermissionRequest", "PreCompact", "PostCompact", "SubagentStart", "SubagentStop"]);
const CLAUDE_ONLY_EVENTS = new Set(["Elicitation", "StopFailure"]);
// 优先级（高 → 低）：error > 等你确认 > 调工具 > 思考 > unknown > 完成 > 空闲 > 关
// 设计要点（v1.2）：
//   - success 优先级低于 busy/thinking/unknown，保证「一个 Agent 干完了」的绿灯
//     不会盖过「另一个 Agent 正在干活」的跑马灯/黄灯闪/三色慢闪。
//   - success 也会很快过期（见 isStaleSuccessSession），自然回到呼吸灯。
//   - unknown 是新加的「不确定」状态，三色慢闪，比 idle 优先级高但不抢 busy/thinking。
const DEVICE_STATUS_PRIORITY = {
  error: 70,
  wait_confirm: 60,
  busy: 55,
  thinking: 40,
  ai: 35,
  unknown: 25,
  success: 20,
  idle: 10,
  off: 0
};
const CLAUDE_EVENT_TO_STATUS = {
  SessionStart: "idle",
  UserPromptSubmit: "thinking",
  PreToolUse: "busy",
  PostToolUse: "ai",
  PostToolUseFailure: "error",
  PreCompact: "ai",
  SubagentStart: "ai",
  SubagentStop: "ai",
  PermissionRequest: "wait_confirm",
  Notification: "wait_confirm",
  Stop: "success",
  SessionEnd: "off"
};

function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(CONFIG_PATH)) {
    fs.copyFileSync(DEFAULT_CONFIG_PATH, CONFIG_PATH);
  }
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function baseEventKey(event) {
  if (typeof event !== "string") return "";
  if (event.startsWith("claude/")) return event.slice("claude/".length);
  if (event.startsWith("codex/")) return event.slice("codex/".length);
  return event;
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > 1024 * 1024) {
        reject(new Error("body_too_large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

class ConfigStore {
  constructor() {
    this.data = readJson(CONFIG_PATH);
    this.mergeBuiltinEffects(this.data);
    this.validate(this.data);
  }

  reload() {
    this.data = readJson(CONFIG_PATH);
    this.mergeBuiltinEffects(this.data);
    this.validate(this.data);
  }

  // v1.5: 自动补 builtin effects（老用户 config.json 缺失时）
  // 设计：用户自定义的 effect 不动，但 builtin=true 的 effect 必须存在且与 default 一致
  // 这样升级 default（加 success effect）时，老用户也能享受新 effect，不会破坏自定义
  mergeBuiltinEffects(config) {
    if (!config || !Array.isArray(config.effects)) return;
    try {
      const defaultConfig = readJson(DEFAULT_CONFIG_PATH);
      const existingIds = new Set(config.effects.map((e) => e && e.id));
      for (const defEffect of defaultConfig.effects) {
        if (defEffect.builtin && !existingIds.has(defEffect.id)) {
          config.effects.push(defEffect);
        }
      }
      // 同步 default 的 event_bindings 中关键事件的绑定（v1.5: Stop → success 修正）
      // 不覆盖用户自定义，只补缺失或修正历史 bug
      if (defaultConfig.event_bindings) {
        for (const [event, effectId] of Object.entries(defaultConfig.event_bindings)) {
          if (existingIds.has(effectId) || config.effects.some((e) => e && e.id === effectId)) {
            // default 是 Stop → success，但老 config 可能是 Stop → idle_green（v1.5 前的 bug）
            // 只有当 effectId 存在且 binding 不同时才覆盖
            if (event === "Stop" && config.event_bindings[event] === "idle_green" && effectId === "success") {
              config.event_bindings[event] = effectId;
            }
          }
        }
      }
    } catch {
      // default config 读取失败时静默跳过（不阻塞启动）
    }
  }

  save(nextData) {
    this.validate(nextData);
    writeJson(CONFIG_PATH, nextData);
    this.data = nextData;
    return this.data;
  }

  validate(config) {
    if (!config || typeof config !== "object") throw new Error("config must be an object");
    if (!Array.isArray(config.effects)) throw new Error("config.effects must be an array");
    if (!config.event_bindings || typeof config.event_bindings !== "object") throw new Error("config.event_bindings must be an object");
    if (!Array.isArray(config.event_priority)) throw new Error("config.event_priority must be an array");

    const effectIds = new Set();
    for (const effect of config.effects) {
      if (!effect || typeof effect.id !== "string" || !effect.id) throw new Error("every effect needs a non-empty id");
      if (effectIds.has(effect.id)) throw new Error(`duplicate effect id: ${effect.id}`);
      effectIds.add(effect.id);
      if (!Array.isArray(effect.frames) || effect.frames.length === 0) throw new Error(`effect ${effect.id} must have at least one frame`);
      for (const frame of effect.frames) {
        if (!Array.isArray(frame.leds) || frame.leds.length !== 3) throw new Error(`effect ${effect.id} has invalid frame leds`);
        for (const led of frame.leds) {
          if (!(led in LED_MODES)) throw new Error(`effect ${effect.id} uses unknown LED mode: ${led}`);
        }
        if (frame.ms !== null && (!Number.isInteger(frame.ms) || frame.ms < 10 || frame.ms > 60000)) {
          throw new Error(`effect ${effect.id} frame duration must be null or 10..60000`);
        }
      }
    }

    for (const [event, effectId] of Object.entries(config.event_bindings)) {
      if (!effectIds.has(effectId)) throw new Error(`event ${event} refers to unknown effect ${effectId}`);
    }

    for (const event of config.event_priority) {
      if (!config.event_bindings[event]) throw new Error(`event priority includes unbound event ${event}`);
    }
  }

  effectForEvent(event) {
    return this.data.event_bindings[event] || null;
  }

  getEffect(effectId) {
    return this.data.effects.find((effect) => effect.id === effectId) || null;
  }

  priorityIndex(event, agent) {
    const agentPriority = this.data.agent_priority && this.data.agent_priority[agent];
    const base = baseEventKey(event);
    if (Array.isArray(agentPriority)) {
      const idx = agentPriority.findIndex((item) => baseEventKey(item) === base);
      if (idx >= 0) return idx;
    }
    const exactIdx = this.data.event_priority.indexOf(event);
    if (exactIdx >= 0) return exactIdx;
    const baseIdx = this.data.event_priority.findIndex((item) => baseEventKey(item) === base);
    return baseIdx >= 0 ? baseIdx : Number.MAX_SAFE_INTEGER;
  }
}

class SessionStore {
  constructor(configStore) {
    this.configStore = configStore;
    this.sessions = new Map();
    this.log = [];
  }

  set(sid, event, cwd, agent, source, toolName) {
    // 新设计（v1.2）：事件驱动 + 降级而非删除
    //
    // 核心原则：会话只在收到 Stop / SessionEnd 时才真正结束。
    // 长时间无事件 → 不删会话，把状态降级为 "unknown"（三色慢闪）。
    // 这样保证：
    //   - 绿灯（success）= Agent 真的干完了（收到 Stop completed）
    //   - 黄灯常亮（wait_confirm）= Agent 真的在等你
    //   - 跑马灯（thinking）= Agent 真的在思考
    //   - 三色慢闪（unknown）= server 不确定，长任务期间可能误显，但不误导
    //
    // 旧 success/error 清理：任何新事件都清掉旧的 Stop / StopFailure 残留
    // （StopFailure 对应 error_red，旧代码只清 Stop，导致 error 状态会卡住）
    const now = Date.now();
    for (const [key, entry] of this.sessions.entries()) {
      if ((entry.event === "Stop" || entry.event === "StopFailure") &&
          event !== "Stop" && event !== "StopFailure") {
        this.sessions.delete(key);
        continue;
      }
    }
    this.sessions.set(sid, {
      sid,
      event,
      cwd: cwd || null,
      agent: agent || "unknown",
      source: source || null,
      toolName: toolName || null,
      lastSeen: now,
      // 记录原始事件（用于僵尸降级后还能识别「曾经是什么状态」）
      originalEvent: event,
      // 标记是否已经被降级为 unknown（用于 statusPayload 显示）
      degraded: false
    });
  }

  remove(sid) {
    return this.sessions.delete(sid);
  }

  addLog(kind, detail) {
    this.log.unshift({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      at: new Date().toISOString(),
      kind,
      detail
    });
    this.log = this.log.slice(0, MAX_LOG_ITEMS);
  }

  sweep() {
    const cutoff = Date.now() - SESSION_TTL_MS;
    let changed = false;
    for (const [sid, entry] of this.sessions.entries()) {
      if (entry.lastSeen < cutoff) {
        this.sessions.delete(sid);
        changed = true;
      }
    }
    return changed;
  }

  snapshot() {
    this.sweep();
    return [...this.sessions.values()]
      .sort((a, b) => b.lastSeen - a.lastSeen)
      .map((entry) => ({
        sid: entry.sid,
        agent: entry.agent,
        event: entry.event,
        source: entry.source || null,
        toolName: entry.toolName || null,
        degraded: entry.degraded || false,
        effect_id: this.configStore.effectForEvent(entry.event) || "off",
        device_status: deriveDeviceStatus(entry.event, this.configStore.effectForEvent(entry.event) || "off", entry.agent, entry.toolName, entry.degraded),
        cwd: entry.cwd,
        age_s: Math.floor((Date.now() - entry.lastSeen) / 1000)
      }));
  }

  winner(agentFilter = "all") {
    const visible = this.snapshot().filter((entry) => agentFilter === "all" || entry.agent === agentFilter);
    if (visible.length === 0) return null;
    return visible.reduce((best, current) => {
      if (!best) return current;
      const bestPriority = this.configStore.priorityIndex(best.event, best.agent);
      const currentPriority = this.configStore.priorityIndex(current.event, current.agent);
      if (currentPriority < bestPriority) return current;
      if (currentPriority === bestPriority && current.age_s < best.age_s) return current;
      return best;
    }, null);
  }

  aggregate(agentFilter = "all") {
    const winner = this.winner(agentFilter);
    if (!winner) {
      return {
        effect_id: "off",
        effect_name: "Off",
        leds: ["off", "off", "off"],
        agent: "none",
        winner_event: "off"
      };
    }
    const effectId = this.configStore.effectForEvent(winner.event) || "off";
    const effect = this.configStore.getEffect(effectId);
    const firstFrame = effect?.frames?.[0] || { leds: ["off", "off", "off"] };
    return {
      effect_id: effectId,
      effect_name: effect?.name || effectId,
      leds: firstFrame.leds,
      agent: winner.agent,
      winner_event: winner.event
    };
  }
}

class SseHub {
  constructor() {
    this.clients = new Set();
  }

  add(res) {
    this.clients.add(res);
  }

  remove(res) {
    this.clients.delete(res);
  }

  send(payload) {
    const data = `data: ${JSON.stringify(payload)}\n\n`;
    for (const res of this.clients) {
      res.write(data);
    }
  }
}

ensureDataDir();
const configStore = new ConfigStore();
const sessionStore = new SessionStore(configStore);
const sseHub = new SseHub();
let agentFilter = "all";
let selectedSessionId = "";

function detectAgent(data, event, urlObj) {
  const queryAgent = (urlObj.searchParams.get("agent") || "").toLowerCase();
  const candidates = [
    queryAgent,
    data.agent_signal_source,
    data.agent,
    data.client,
    data.app,
    data.source_agent
  ];
  for (const raw of candidates) {
    const text = String(raw || "").toLowerCase();
    if (text.includes("codex")) return "codex";
    if (text.includes("claude")) return "claude";
    if (text.includes("cursor")) return "cursor";
  }
  if (CODEX_ONLY_EVENTS.has(event)) return "codex";
  if (CLAUDE_ONLY_EVENTS.has(event)) return "claude";
  return "unknown";
}

function hookEventName(data) {
  const candidates = [
    data.hook_event_name,
    data.event,
    data.event_name,
    data.hook,
    data.type
  ];
  for (const value of candidates) {
    const text = String(value || "").trim();
    if (!text) continue;
    const event = normalizeEventName(text);
    if (event === "Stop") {
      const status = String(data.status || "").toLowerCase();
      if (status === "error") return "StopFailure";
      if (status === "aborted") return "SessionEnd";
    }
    return event;
  }
  return "";
}

function normalizeEventName(name) {
  const text = String(name || "").trim();
  if (!text) return "";
  const map = {
    sessionstart: "SessionStart",
    sessionend: "SessionEnd",
    beforesubmitprompt: "UserPromptSubmit",
    userpromptsubmit: "UserPromptSubmit",
    pretooluse: "PreToolUse",
    posttooluse: "PostToolUse",
    posttoolusefailure: "StopFailure",
    subagentstart: "SubagentStart",
    subagentstop: "SubagentStop",
    precompact: "PreCompact",
    postcompact: "PostCompact",
    stop: "Stop",
    afteragentresponse: "Stop"
  };
  return map[text.toLowerCase()] || text;
}

function hookSessionId(data, agent) {
  const candidates = [
    data.conversation_id,
    data.conversationId,
    data.session_id,
    data.sessionId,
    data.sid,
    data.chat_id,
    data.generation_id,
    data.generationId
  ];
  for (const value of candidates) {
    const text = String(value || "").trim();
    if (text) return text;
  }
  const cwd = String(data.cwd || data.workspace || "").trim();
  if (cwd) return `${agent}:cwd:${cwd}`;
  return "";
}

function deriveDeviceStatus(event, effectId, agent, toolName, degraded) {
  // 如果是被降级的会话（长时间无事件），直接返回 unknown
  if (degraded) {
    return "unknown";
  }

  const eventText = normalizeEventName(event);
  const effectText = String(effectId || "").trim();
  const normalized = `${eventText} ${effectText}`.toLowerCase();
  const toolText = String(toolName || "").toLowerCase();

  // AskUserQuestion 工具：Agent 在问用户问题，必须 wait_confirm（黄灯常亮）
  // 这是用户核心诉求：「黄灯常亮 = Agent 等我反馈」必须严格双向无歧义
  if (toolText === "askuserquestion" && (eventText === "PreToolUse" || eventText === "PostToolUse")) {
    return "wait_confirm";
  }

  if (agent === "claude" && CLAUDE_EVENT_TO_STATUS[eventText]) {
    return CLAUDE_EVENT_TO_STATUS[eventText];
  }

  if (eventText === "StopFailure" || effectText === "error_red" || normalized.includes("posttoolusefailure")) {
    return "error";
  }
  if (
    eventText === "PermissionRequest" ||
    eventText === "Notification" ||
    eventText === "Elicitation" ||
    effectText === "wait_user" ||
    normalized.includes("wait_confirm") ||
    normalized.includes("waiting") ||
    normalized.includes("confirm")
  ) {
    return "wait_confirm";
  }
  if (eventText === "Stop" || effectText === "success") {
    return "success";
  }
  if (eventText === "PreToolUse") {
    return "busy";
  }
  if (eventText === "PostToolUse") {
    return "thinking";
  }
  if (eventText === "busy") {
    return "busy";
  }
  if (
    eventText === "SubagentStart" ||
    eventText === "SubagentStop" ||
    eventText === "PreCompact" ||
    eventText === "PostCompact"
  ) {
    return "thinking";
  }
  if (
    eventText === "SessionStart" ||
    effectText === "idle_green"
  ) {
    return "idle";
  }
  if (
    eventText === "UserPromptSubmit" ||
    eventText === "thinking" ||
    effectText === "working_yellow"
  ) {
    return "thinking";
  }
  return effectText === "off" || eventText === "SessionEnd" ? "off" : "off";
}

function effectIdForDeviceStatus(deviceStatus) {
  switch (deviceStatus) {
    case "idle":
      return "idle_green";
    case "thinking":
    case "ai":
    case "busy":
      return "working_yellow";
    case "wait_confirm":
      return "wait_user";
    case "error":
      return "error_red";
    case "unknown":
      return "unknown_tricolor";  // 三色慢闪
    case "success":
      return "success";
    default:
      return "off";
  }
}

function shouldTrackEvent(event, agent) {
  const deviceStatus = deriveDeviceStatus(event, "", agent);
  return deviceStatus !== "off" || event === "SessionEnd" || event === "Stop" || event === "SessionStart";
}

function bindingKeyFor(data, event, agent) {
  const tool = String(data.tool_name || "").trim();
  const matcherValue =
    event === "PreToolUse" || event === "PostToolUse" || event === "PermissionRequest"
      ? tool
      : "";

  const candidates = [];
  if (matcherValue) {
    if (agent === "claude" || agent === "codex" || agent === "cursor") candidates.push(`${agent}/${event}:${matcherValue}`);
    candidates.push(`${event}:${matcherValue}`);
  }
  if (agent === "claude" || agent === "codex" || agent === "cursor") candidates.push(`${agent}/${event}`);
  candidates.push(event);

  return candidates.find((key) => configStore.effectForEvent(key)) || null;
}

function isStaleIdleSession(session) {
  // v1.4: SessionStart idle 不再 60s 短灭，跟 unknown 一样走 TTL 兜底。
  // 设计哲学：绿灯呼吸 = 「agent 干完了」是强确定状态，应当持续显示给用户确认，
  // 不应该 60s 就消失。如果有新对话/工具调用，会被新事件自然覆盖；
  // 如果用户真的离开了，10min TTL 后灯灭（off）也是合理语义。
  // 旧设计（60s 短灭）违反双向对应：把「确定空闲」擅自变成「确定无 agent」。
  return false;  // 不主动删，靠 SESSION_TTL_MS 兜底
}

function isStaleSuccessSession(session) {
  // success 不再「删除」——success 6s 后由 sweep 转为 idle（保留 session）。
  // 设计哲学：绿灯常亮 5s 后应当转绿灯呼吸（idle），而非直接让灯灭（off）。
  // 见 sweep() line 700 注释。
  return false;
}

// v1.2: 不再用 stale 过滤删会话，改成「降级」。
// 这些 isStaleXxx 函数现在只用于 statusPayload 的「展示过滤」(snapshot)，
// 真正的清理在 sweep + degraded 标记里。
// 但 idle/success 仍然要删（idle 是 SessionStart 90s 后基本算窗口关了；
// success 6s 后必须删让位）。
function shouldDeleteSession(session) {
  if (isStaleIdleSession(session)) return true;
  if (isStaleSuccessSession(session)) return true;
  return false;
}

// 降级阈值：超过这个时间无事件，会话状态降级为 unknown（不删）
// 设计哲学：unknown 三色慢闪 = server「不确定」，是诚实状态。
//   - 一旦显示 unknown，必须等「新事件」「用户主动确认」「10min TTL」之一
//   - 绝不自动变 idle（违反「绿灯 ↔ 干完了」双向对应）
//   - 绝不自动变 off（违反「unknown ↔ 不确定」双向对应）
const DEGRADE_PRE_TOOL_MS = 30_000;    // PreToolUse（busy）30s 无 PostToolUse → 降级
const DEGRADE_THINKING_MS = 180_000;   // PostToolUse/UserPromptSubmit 3 分钟无新事件 → 降级

function shouldDegradeSession(session) {
  if (session.degraded) return false;  // 已经降级
  if (session.event === "PreToolUse" && session.age_s * 1000 > DEGRADE_PRE_TOOL_MS) return true;
  if ((session.event === "PostToolUse" || session.event === "UserPromptSubmit") && session.age_s * 1000 > DEGRADE_THINKING_MS) return true;
  return false;
}

function statusPayload() {
  const sessions = sessionStore.snapshot();
  // v1.2: 只删 idle/success 超期的（应该让位的）；busy/thinking 不删，靠降级
  const visibleSessions = sessions
    .filter((session) => agentFilter === "all" || session.agent === agentFilter)
    .filter((session) => !shouldDeleteSession(session));
  const selectedSession =
    selectedSessionId
      ? visibleSessions.find((session) => session.sid === selectedSessionId) || null
      : null;
  const aggregate = selectedSession
    ? {
        effect_id: effectIdForDeviceStatus(selectedSession.device_status),
        effect_name: effectIdForDeviceStatus(selectedSession.device_status),
        leds: (configStore.getEffect(effectIdForDeviceStatus(selectedSession.device_status))?.frames?.[0]?.leds) || ["off", "off", "off"],
        agent: selectedSession.agent,
        winner_event: selectedSession.event,
        device_status: selectedSession.device_status
      }
    : (() => {
        const winner = visibleSessions.reduce((best, current) => {
          if (!best) return current;
          const bestPriority = DEVICE_STATUS_PRIORITY[best.device_status] ?? -1;
          const currentPriority = DEVICE_STATUS_PRIORITY[current.device_status] ?? -1;
          if (currentPriority > bestPriority) return current;
          if (currentPriority < bestPriority) return best;
          return current.age_s < best.age_s ? current : best;
        }, null);

        if (!winner) {
          return {
            effect_id: "off",
            effect_name: "Off",
            leds: ["off", "off", "off"],
            agent: "none",
            winner_event: "off",
            device_status: "off"
          };
        }

        const effectId = effectIdForDeviceStatus(winner.device_status);
        return {
          effect_id: effectId,
          effect_name: effectId,
          leds: (configStore.getEffect(effectId)?.frames?.[0]?.leds) || ["off", "off", "off"],
          agent: winner.agent,
          winner_event: winner.event,
          device_status: winner.device_status
        };
      })();
  const agentCounts = sessions.reduce((acc, session) => {
    if (session.agent === "codex" || session.agent === "claude" || session.agent === "cursor") {
      acc[session.agent] += 1;
    }
    return acc;
  }, { codex: 0, claude: 0, cursor: 0 });
  return {
    ok: true,
    agent_filter: agentFilter,
    selected_session_id: selectedSessionId || "",
    controlling_session_id: selectedSession ? selectedSession.sid : "",
    selected_session_missing: Boolean(selectedSessionId) && !selectedSession,
    ...aggregate,
    led_codes: aggregate.leds.map((mode) => LED_MODES[mode]),
    display_state: aggregate.device_status === "wait_confirm" ? "waiting" : aggregate.device_status,
    sessions,
    visible_session_count: visibleSessions.length,
    agent_counts: agentCounts,
    log: sessionStore.log,
    config: configStore.data
  };
}

function broadcast() {
  sseHub.send(statusPayload());
}

setInterval(() => {
  const changed = sessionStore.sweep();
  if (changed) {
    if (selectedSessionId && !sessionStore.sessions.has(selectedSessionId)) {
      selectedSessionId = "";
    }
    broadcast();
  }
}, 1000);

// 周期性扫描（每秒）：
//   - 标记降级：长时间无事件的 busy/thinking 标记 degraded=true，状态显示为 unknown（三色慢闪）
//   - 删除 success 超期（6s）：让位
//   - 删除整个会话超期（TTL 3 分钟兜底）：窗口被强关但没发 SessionEnd 的情况
//   - 真正的清理还靠 Stop / SessionEnd 事件触发
const DEGRADE_PRE_TOOL_MS_SWEEP = 30_000;
const DEGRADE_THINKING_MS_SWEEP = 180_000;
const SESSION_TTL_SWEEP_MS = SESSION_TTL_MS;  // 与 sweep() 里的 TTL 同步，10 分钟
setInterval(() => {
  const now = Date.now();
  let changed = false;
  for (const [sid, entry] of sessionStore.sessions.entries()) {
    const ageMs = now - (entry.lastSeen || 0);

    // 1. success 6s 后转 idle（让位但保留 session 显示绿灯呼吸）
    //    设计哲学：success 是「瞬时反馈」绿灯常亮 5s 已足够；之后 agent 仍在但空闲，
    //    应当显示 idle（绿灯呼吸）而非直接 off（违反双向对应：把「agent 干完了」
    //    变成「没有 agent」）。idle 走 10min TTL 兜底，期间可被新事件自然覆盖。
    //    历史背景：原设计直接 delete(sid) 让 server 进 off，长期被 bridge 的
    //    off→idle bug 掩盖；bridge 修复（2026-07-04）后才暴露。
    if (entry.event === "Stop" && ageMs > 6_000) {
      entry.event = "SessionStart";
      entry.device_status = "idle";
      entry.lastSeen = now;
      entry.degraded = false;
      changed = true;
      continue;
    }
    // 1b. StopFailure（error_red）**不主动清** —— 红灯是用户必看的重要状态
    //     只能被新事件覆盖（line 192）或 10min TTL 兜底
    // 2. SessionStart idle **不主动清**（v1.4）—— 跟 unknown 一样靠 10min TTL
    //    绿灯呼吸 = agent 干完了，应当持续显示，不应 60s 短灭
    //    （旧设计 60s 灭灯违反双向对应，把「确定空闲」变成「确定无 agent」）
    // 3. 降级（先尝试降级，标记 degraded=true，显示为 unknown）
    if (!entry.degraded) {
      if (entry.event === "PreToolUse" && ageMs > DEGRADE_PRE_TOOL_MS_SWEEP) {
        entry.degraded = true;
        changed = true;
      } else if ((entry.event === "PostToolUse" || entry.event === "UserPromptSubmit") && ageMs > DEGRADE_THINKING_MS_SWEEP) {
        entry.degraded = true;
        changed = true;
      }
    }
    // 4. TTL 兜底：超过 SESSION_TTL_MS（10 分钟）无事件，无论什么状态，删
    //    10 分钟 > 3 分钟（DEGRADE_THINKING_MS），所以降级先发生
    if (ageMs > SESSION_TTL_SWEEP_MS) {
      sessionStore.sessions.delete(sid);
      changed = true;
      continue;
    }
  }
  if (changed) broadcast();
}, 1000);

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(JSON.stringify(payload));
}

function sendText(res, statusCode, body, contentType) {
  res.writeHead(statusCode, {
    "Content-Type": contentType,
    "Cache-Control": "no-store"
  });
  res.end(body);
}

function serveFile(res, filePath, contentType) {
  try {
    const body = fs.readFileSync(filePath);
    sendText(res, 200, body, contentType);
  } catch {
    sendText(res, 404, "Not Found", "text/plain; charset=utf-8");
  }
}

async function handleHook(req, res, urlObj) {
  const raw = await parseBody(req);
  let data;
  try {
    data = JSON.parse(raw.toString("utf8"));
  } catch {
    sendJson(res, 400, { ok: false, error: "bad json" });
    return;
  }

  const sid = String(data.session_id || "").trim();
  const event = hookEventName(data);
  const cwd = data.cwd ? String(data.cwd) : null;
  const agent = detectAgent(data, event, urlObj);
  const source = data.source ? String(data.source).slice(0, 32) : null;
  const toolName = data.tool_name ? String(data.tool_name).slice(0, 64) : null;
  const resolvedSid = hookSessionId(data, agent);
  if (!resolvedSid || !event) {
    sendJson(res, 400, { ok: false, error: "missing session id or event name" });
    return;
  }

  if (event === "SessionEnd") {
    sessionStore.remove(resolvedSid);
    sessionStore.addLog("session-end", `${agent}:${resolvedSid.slice(0, 8)}`);
    broadcast();
    sendJson(res, 200, { ok: true });
    return;
  }

  if (!shouldTrackEvent(event, agent)) {
    sendJson(res, 200, { ok: true, ignored: true });
    return;
  }

  sessionStore.set(resolvedSid, event, cwd, agent, source, toolName);
  sessionStore.addLog("hook", `${agent} ${event} ${resolvedSid.slice(0, 8)}`);
  broadcast();
  sendJson(res, 200, { ok: true, event, agent });
}

async function handleManualEvent(req, res) {
  const raw = (await parseBody(req)).toString("utf8").trim().toUpperCase();
  const map = {
    G: "SessionStart",
    Y: "UserPromptSubmit",
    W: "PermissionRequest",
    R: "StopFailure",
    O: "SessionEnd"
  };
  const event = map[raw];
  if (!event) {
    sendJson(res, 400, { ok: false, error: "use G/Y/W/R/O" });
    return;
  }
  if (event === "SessionEnd") {
    sessionStore.remove(MANUAL_SID);
    if (selectedSessionId === MANUAL_SID) {
      selectedSessionId = "";
    }
    sessionStore.addLog("manual", "manual off");
  } else {
    sessionStore.set(MANUAL_SID, event, "(manual)", "manual");
    selectedSessionId = MANUAL_SID;
    sessionStore.addLog("manual", `manual ${event}`);
  }
  broadcast();
  sendJson(res, 200, { ok: true, event });
}

async function handleConfigSave(req, res) {
  const raw = await parseBody(req);
  let nextConfig;
  try {
    nextConfig = JSON.parse(raw.toString("utf8"));
    configStore.save(nextConfig);
  } catch (error) {
    sendJson(res, 400, { ok: false, error: error.message || "invalid config" });
    return;
  }
  sessionStore.addLog("config", "config updated");
  broadcast();
  sendJson(res, 200, { ok: true, config: configStore.data });
}

async function handleAgentFilter(req, res) {
  const raw = await parseBody(req);
  let nextScope = "";
  try {
    const data = JSON.parse(raw.toString("utf8") || "{}");
    nextScope = String(data.scope || data.agent_filter || "").toLowerCase();
  } catch {
    sendJson(res, 400, { ok: false, error: "bad json" });
    return;
  }
  if (!AGENT_SCOPES.has(nextScope)) {
    sendJson(res, 400, { ok: false, error: "scope must be all, claude, codex, or cursor" });
    return;
  }
  agentFilter = nextScope;
  broadcast();
  sendJson(res, 200, { ok: true, agent_filter: agentFilter });
}

async function handleSessionSelect(req, res) {
  const raw = await parseBody(req);
  let nextSid = "";
  try {
    const data = JSON.parse(raw.toString("utf8") || "{}");
    nextSid = String(data.sid || data.session_id || "").trim();
  } catch {
    sendJson(res, 400, { ok: false, error: "bad json" });
    return;
  }

  if (nextSid) {
    const exists = sessionStore.snapshot().some((session) => session.sid === nextSid);
    if (!exists) {
      sendJson(res, 404, { ok: false, error: "session not found" });
      return;
    }
  }

  selectedSessionId = nextSid;
  broadcast();
  sendJson(res, 200, {
    ok: true,
    selected_session_id: selectedSessionId
  });
}

const server = http.createServer(async (req, res) => {
  const urlObj = new URL(req.url, `http://${req.headers.host || `${HOST}:${PORT}`}`);

  try {
    if (req.method === "GET" && urlObj.pathname === "/") {
      serveFile(res, path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8");
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/app.js") {
      serveFile(res, path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8");
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/ble-client.js") {
      serveFile(res, path.join(STATIC_DIR, "ble-client.js"), "application/javascript; charset=utf-8");
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/device-transport.js") {
      serveFile(res, path.join(STATIC_DIR, "device-transport.js"), "application/javascript; charset=utf-8");
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/styles.css") {
      serveFile(res, path.join(STATIC_DIR, "styles.css"), "text/css; charset=utf-8");
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/api/status") {
      sendJson(res, 200, statusPayload());
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/api/config") {
      sendJson(res, 200, { ok: true, config: configStore.data });
      return;
    }
    if (req.method === "GET" && urlObj.pathname === "/stream") {
      res.writeHead(200, {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive"
      });
      res.write(`data: ${JSON.stringify(statusPayload())}\n\n`);
      sseHub.add(res);
      req.on("close", () => sseHub.remove(res));
      return;
    }
    if (req.method === "POST" && urlObj.pathname === "/hook") {
      await handleHook(req, res, urlObj);
      return;
    }
    if (req.method === "POST" && urlObj.pathname === "/event") {
      await handleManualEvent(req, res);
      return;
    }
    if (req.method === "POST" && urlObj.pathname === "/api/config") {
      await handleConfigSave(req, res);
      return;
    }
    if (req.method === "POST" && urlObj.pathname === "/api/agent-filter") {
      await handleAgentFilter(req, res);
      return;
    }
    if (req.method === "POST" && urlObj.pathname === "/api/session-select") {
      await handleSessionSelect(req, res);
      return;
    }

    sendText(res, 404, "Not Found", "text/plain; charset=utf-8");
  } catch (error) {
    sendJson(res, 500, { ok: false, error: error.message || "server error" });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Agent Signal Light Web MVP -> http://${HOST}:${PORT}`);
});
