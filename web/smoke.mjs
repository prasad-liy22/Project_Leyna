// End-to-end smoke test for the Leyna web UI.
//
// Drives the real page in headless Chrome over the DevTools Protocol using
// Node's built-in WebSocket (no dependencies). `/chat/stream` is stubbed inside
// the page, so no paid API call is made — but the backend must be running so
// `/health` and `/debug/*` respond.
//
//   npm run smoke
//   BASE_URL=http://127.0.0.1:8000 CHROME=chromium npm run smoke

import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:8000";
const CDP_PORT = Number(process.env.CDP_PORT ?? 9222);

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  for (const name of ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]) {
    const found = spawnSync("command", ["-v", name], { shell: true, encoding: "utf8" });
    if (found.status === 0) return found.stdout.trim();
  }
  throw new Error("No Chrome/Chromium found. Set CHROME=/path/to/chrome.");
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function targetList() {
  for (let i = 0; i < 80; i += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`);
      if (response.ok) return response.json();
    } catch {
      /* keep waiting */
    }
    await sleep(250);
  }
  throw new Error("Chrome never exposed a debugging target");
}

/** Everything below runs inside the browser page. */
function pageTest() {
  return (async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const $ = (selector) => document.querySelector(selector);
    const out = {};

    /* 1. Streaming chat, with /chat/stream stubbed so nothing is billed. */
    const LF = String.fromCharCode(10);
    const SEP = LF + LF;
    const realFetch = window.fetch.bind(window);
    window.fetch = (url, options) => {
      if (String(url).includes("/chat/stream")) {
        const frames = [
          'data: {"delta":"Hello "}' + SEP,
          'data: {"delta":"**world** from Leyna"}' + SEP,
          'data: {"done":true,"model":"gemma4:31b-cloud","prompt_tokens":5,"completion_tokens":2}' + SEP,
        ];
        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            let index = 0;
            const push = () => {
              if (index < frames.length) {
                controller.enqueue(encoder.encode(frames[index++]));
                setTimeout(push, 25);
              } else {
                controller.close();
              }
            };
            push();
          },
        });
        return Promise.resolve(
          new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
        );
      }
      return realFetch(url, options);
    };

    const input = $("#composer-input");
    input.value = "ping";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    out.sendEnabledWithText = !$("#send-btn").disabled;

    $("#composer-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await sleep(900);

    out.messageCount = document.querySelectorAll("#messages .bubble").length;
    out.userText = $("#messages .bubble-user")?.textContent ?? null;
    out.assistantText = $("#messages .bubble-assistant")?.textContent ?? null;
    out.assistantRenderedBold = Boolean($("#messages .bubble-assistant strong"));
    out.tokenChip = $("#messages .chip")?.textContent?.trim() ?? null;
    out.emptyStateHidden = $("#empty-state").classList.contains("hidden");
    out.historySaved = Boolean(localStorage.getItem("leyna.history.v1"));

    /* 2. Debug drawer. */
    $("#debug-btn").click();
    await sleep(1500);
    out.drawerOpen = !$("#debug-drawer").classList.contains("translate-x-full");
    out.overlayVisible = !$("#debug-overlay").classList.contains("hidden");
    out.usageCards = $("#usage-totals").querySelectorAll(".card").length;

    $('[data-tab="logs"]').click();
    await sleep(1500);
    out.logsPanelVisible = !$("#panel-logs").classList.contains("hidden");
    out.logLines = $("#logs-console").querySelectorAll(".log-line").length;

    $('[data-tab="api-key"]').click();
    await sleep(1000);
    out.maskedKey = $("#key-masked").textContent.trim();
    out.keySource = $("#key-source").textContent.trim();

    /* 3. Escape closes the drawer; New chat resets the conversation. */
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await sleep(400);
    out.drawerClosed = $("#debug-drawer").classList.contains("translate-x-full");

    $("#new-chat-btn").click();
    await sleep(200);
    out.messagesAfterReset = $("#messages").children.length;
    out.emptyStateBack = !$("#empty-state").classList.contains("hidden");

    window.fetch = realFetch;
    return out;
  })();
}

const EXPECTED = {
  sendEnabledWithText: true,
  messageCount: 2,
  userText: "ping",
  assistantText: "Hello world from Leyna",
  assistantRenderedBold: true,
  tokenChip: "↑ 5 · ↓ 2",
  emptyStateHidden: true,
  historySaved: true,
  drawerOpen: true,
  overlayVisible: true,
  usageCards: 6,
  logsPanelVisible: true,
  drawerClosed: true,
  messagesAfterReset: 0,
  emptyStateBack: true,
};

function check(results) {
  const failures = [];
  for (const [key, want] of Object.entries(EXPECTED)) {
    if (results[key] !== want) failures.push(`${key}: expected ${JSON.stringify(want)}, got ${JSON.stringify(results[key])}`);
  }
  if (!(results.logLines >= 1)) failures.push(`logLines: expected >= 1, got ${results.logLines}`);
  if (results.maskedKey !== "not set" && !results.maskedKey.includes("…")) {
    failures.push(`maskedKey: expected a masked value, got ${JSON.stringify(results.maskedKey)}`);
  }
  if (!["env", "debug-override", "unset"].includes(results.keySource)) {
    failures.push(`keySource: unexpected ${JSON.stringify(results.keySource)}`);
  }
  return failures;
}

async function main() {
  const chromePath = findChrome();
  const profile = mkdtempSync(join(tmpdir(), "leyna-smoke-"));
  const chrome = spawn(
    chromePath,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--no-first-run",
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );

  try {
    const list = await targetList();
    const page = list.find((target) => target.type === "page");
    if (!page) throw new Error("No page target found");

    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener("open", resolve, { once: true });
      ws.addEventListener("error", reject, { once: true });
    });

    let nextId = 0;
    const pending = new Map();
    ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        pending.get(message.id)(message);
        pending.delete(message.id);
      }
    });
    const cmd = (method, params = {}) =>
      new Promise((resolve) => {
        const id = (nextId += 1);
        pending.set(id, resolve);
        ws.send(JSON.stringify({ id, method, params }));
      });

    const evaluate = async (expression) => {
      const message = await cmd("Runtime.evaluate", {
        expression,
        returnByValue: true,
        awaitPromise: true,
      });
      const payload = message.result ?? {};
      if (payload.exceptionDetails) throw new Error(JSON.stringify(payload.exceptionDetails));
      return payload.result?.value;
    };

    await cmd("Runtime.enable");
    await cmd("Page.enable");
    await cmd("Page.navigate", { url: BASE });

    let ready = false;
    for (let i = 0; i < 60 && !ready; i += 1) {
      await sleep(250);
      try {
        ready = (await evaluate("!!document.querySelector('#composer-input')")) === true;
      } catch {
        /* execution context may not exist yet */
      }
    }
    if (!ready) throw new Error(`Web UI never became ready at ${BASE} — is the backend running?`);

    await sleep(1200); // let the first /health call land

    const results = await evaluate(`(${pageTest.toString()})()`);
    const failures = check(results);

    console.log(JSON.stringify(results, null, 2));
    if (failures.length) {
      console.error(`\n✗ ${failures.length} check(s) failed:`);
      for (const failure of failures) console.error(`  - ${failure}`);
      process.exitCode = 1;
    } else {
      console.log(`\n✓ all ${Object.keys(EXPECTED).length + 2} checks passed`);
    }
    ws.close();
  } finally {
    chrome.kill("SIGKILL");
  }
}

try {
  await main();
} catch (error) {
  console.error("smoke test error:", error.message);
  process.exitCode = 1;
}
