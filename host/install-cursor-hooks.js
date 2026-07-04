#!/usr/bin/env node
/**
 * Install Cursor hooks for AgentCore-Light (async queue → host/server.js).
 * Usage: node host/install-cursor-hooks.js
 */
const fs = require("node:fs");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..");
const cursorDir = path.join(process.env.HOME || "", ".cursor");
const cursorHooksPath = path.join(cursorDir, "hooks.json");
const cursorHookDir = path.join(cursorDir, "hooks");
const cursorHookScript = path.join(cursorHookDir, "agentcore-light.sh");
const sourceHook = path.join(repoRoot, "hooks", "cursor", "cursor-hook-fast.sh");

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function readJson(filePath, fallback) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function installCursorHookScript() {
  ensureDir(cursorHookDir);
  ensureDir(path.join(cursorHookDir, "queue"));
  const hookBody = fs.readFileSync(sourceHook, "utf8");
  fs.writeFileSync(cursorHookScript, hookBody, { mode: 0o755 });
  console.log(`wrote Cursor hook script -> ${cursorHookScript}`);
}

function cursorHookCommand() {
  return `sh "${cursorHookScript}"`;
}

function buildCursorHooksConfig() {
  const command = cursorHookCommand();
  const entry = { command, timeout: 5 };
  const events = [
    "sessionStart",
    "sessionEnd",
    "beforeSubmitPrompt",
    "preToolUse",
    "postToolUse",
    "postToolUseFailure",
    "subagentStart",
    "subagentStop",
    "preCompact",
    "afterAgentResponse",
    "stop",
  ];
  const hooks = {};
  for (const eventName of events) {
    hooks[eventName] = [entry];
  }
  return { version: 1, hooks };
}

function installCursorHooks() {
  installCursorHookScript();
  ensureDir(cursorDir);
  const current = readJson(cursorHooksPath, { version: 1, hooks: {} });
  const next = typeof current === "object" && current !== null ? current : {};
  const hooksRoot = typeof next.hooks === "object" && next.hooks !== null ? next.hooks : {};
  const ours = buildCursorHooksConfig().hooks;

  for (const [eventName, groups] of Object.entries(ours)) {
    const existing = Array.isArray(hooksRoot[eventName]) ? hooksRoot[eventName] : [];
    const kept = existing.filter((entry) => {
      try {
        const command = String(entry.command || "");
        return (
          !command.includes("agentcore-light.sh") &&
          !command.includes("cursor-hook") &&
          !command.includes("agent-signal-light-web")
        );
      } catch {
        return true;
      }
    });
    hooksRoot[eventName] = [...kept, ...groups];
  }

  next.version = 1;
  next.hooks = hooksRoot;
  writeJson(cursorHooksPath, next);
  console.log(`merged Cursor hooks -> ${cursorHooksPath}`);
}

if (!fs.existsSync(sourceHook)) {
  console.error(`missing hook source: ${sourceHook}`);
  process.exit(1);
}

installCursorHooks();
console.log("Done. Start host/server.js and host/hook-queue-worker.js, then use Cursor Agent.");
