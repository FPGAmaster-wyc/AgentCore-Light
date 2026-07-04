const fs = require("node:fs");
const path = require("node:path");

const PORT = Number(process.env.AGENT_SIGNAL_LIGHT_PORT || 8787);
const HOOK_URL = `http://127.0.0.1:${PORT}/hook?agent=cursor`;
const QUEUE_DIR = path.join(process.env.HOME || "", ".cursor", "hooks", "queue");
const ATTEMPTS_DIR = path.join(QUEUE_DIR, ".attempts");
const POLL_MS = 50;
const MAX_ATTEMPTS = 3;
const STALE_MS = 60_000;

function ensureDirs() {
  fs.mkdirSync(QUEUE_DIR, { recursive: true });
  fs.mkdirSync(ATTEMPTS_DIR, { recursive: true });
}

function attemptsFor(name) {
  const p = path.join(ATTEMPTS_DIR, `${name}.count`);
  try {
    return Number(fs.readFileSync(p, "utf8")) || 0;
  } catch {
    return 0;
  }
}

function bumpAttempts(name) {
  const p = path.join(ATTEMPTS_DIR, `${name}.count`);
  const next = attemptsFor(name) + 1;
  try {
    fs.writeFileSync(p, String(next), "utf8");
  } catch {}
  return next;
}

function clearAttempts(name) {
  const p = path.join(ATTEMPTS_DIR, `${name}.count`);
  try { fs.unlinkSync(p); } catch {}
}

async function postPayload(raw) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch(HOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: raw,
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`hook post failed: ${response.status}`);
    }
  } finally {
    clearTimeout(timer);
  }
}

async function drainOnce() {
  let names;
  try {
    names = fs.readdirSync(QUEUE_DIR).filter((name) => name.endsWith(".json")).sort();
  } catch {
    return;
  }

  for (const name of names) {
    const filePath = path.join(QUEUE_DIR, name);
    let raw = "";
    try {
      const stat = fs.statSync(filePath);
      if (Date.now() - stat.mtimeMs > STALE_MS) {
        fs.unlinkSync(filePath);
        clearAttempts(name);
        continue;
      }
      raw = fs.readFileSync(filePath, "utf8");
      if (raw.trim()) {
        await postPayload(raw);
      }
      fs.unlinkSync(filePath);
      clearAttempts(name);
    } catch (error) {
      const tries = bumpAttempts(name);
      if (tries >= MAX_ATTEMPTS) {
        try { fs.unlinkSync(filePath); } catch {}
        clearAttempts(name);
        console.error(`[hook-queue] ${name}: dropping after ${tries} attempts (${error.message})`);
      }
    }
  }
}

async function main() {
  ensureDirs();
  console.log(`[hook-queue] draining ${QUEUE_DIR} -> ${HOOK_URL}`);
  for (;;) {
    try {
      await drainOnce();
    } catch (error) {
      console.error(`[hook-queue] ${error.message}`);
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

main();
