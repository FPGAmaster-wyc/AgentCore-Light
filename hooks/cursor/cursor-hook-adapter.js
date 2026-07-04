const path = require("node:path");
const { spawn } = require("node:child_process");

const SCRIPT_DIR = __dirname;

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function mapEvent(input) {
  const raw = String(input.hook_event_name || "").trim();
  if (raw === "stop") {
    const status = String(input.status || "").toLowerCase();
    if (status === "error") return "StopFailure";
    if (status === "completed") return "Stop";
    return "SessionEnd";
  }

  const map = {
    sessionStart: "SessionStart",
    sessionEnd: "SessionEnd",
    beforeSubmitPrompt: "UserPromptSubmit",
    preToolUse: "PreToolUse",
    postToolUse: "PostToolUse",
    postToolUseFailure: "StopFailure",
    subagentStart: "SubagentStart",
    subagentStop: "SubagentStop",
    preCompact: "PreCompact",
    postCompact: "PostCompact",
    afterAgentResponse: "Stop"
  };

  return map[raw] || "";
}

function sessionId(input) {
  return String(input.conversation_id || input.session_id || "").trim();
}

function workspacePath(input) {
  const roots = input.workspace_roots;
  if (Array.isArray(roots) && roots[0]) {
    return String(roots[0]);
  }
  return String(input.cwd || process.env.CURSOR_PROJECT_DIR || "").trim();
}

function forward(payload) {
  const child = spawn("node", [path.join(SCRIPT_DIR, "hook-forwarder.js"), "cursor"], {
    cwd: SCRIPT_DIR,
    detached: true,
    stdio: ["pipe", "ignore", "ignore"],
    env: {
      ...process.env,
      http_proxy: "",
      https_proxy: "",
      HTTP_PROXY: "",
      HTTPS_PROXY: "",
      ALL_PROXY: "",
      all_proxy: ""
    }
  });
  child.stdin.write(JSON.stringify(payload));
  child.stdin.end();
  child.unref();
}

async function main() {
  const raw = await readStdin();
  if (!raw.trim()) {
    return;
  }

  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    return;
  }

  const event = mapEvent(input);
  if (!event) {
    return;
  }

  const sid = sessionId(input);
  if (!sid) {
    return;
  }

  forward({
    hook_event_name: event,
    event,
    session_id: sid,
    conversation_id: input.conversation_id || sid,
    cwd: workspacePath(input) || null,
    agent: "cursor",
    agent_signal_source: "cursor",
    tool_name: input.tool_name || ""
  });
}

main().catch(() => {
  process.exit(0);
});
