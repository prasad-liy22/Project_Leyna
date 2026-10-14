// End-to-end smoke test for the Leyna web UI.
//
// Drives the real page in headless Chrome over the DevTools Protocol using
// Node's built-in WebSocket (no dependencies). `/chat/stream` is stubbed inside
// the page, so no paid API call is made — but the backend must be running so
// `/health`, `/conversations` and `/debug/*` respond.
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
    const realFetch = window.fetch.bind(window);
    const out = { leynaBooted: window.__leynaReady === true };

    /* 0. Theme toggle: OS default (headless Chrome is light), then explicit choice. */
    const themeBtn = $("#theme-btn");
    const theme = () =>
      document.documentElement.classList.contains("dark") ? "dark" : "light";
    const bodyBg = () => getComputedStyle(document.body).backgroundColor;
    const inkColor = () => getComputedStyle($("header h1")).color;

    out.themeDefault = theme();
    out.themeDefaultBg = bodyBg();
    out.themeDefaultInk = inkColor();

    themeBtn.click();
    await sleep(350);
    out.themeToggled = theme();
    out.themeToggledBg = bodyBg();
    out.themeToggledInk = inkColor();
    out.themePersisted = localStorage.getItem("leyna.theme");
    out.themeAriaPressed = themeBtn.getAttribute("aria-pressed");

    themeBtn.click();
    await sleep(350);
    out.themeRestored = theme();

    /* 0b. Server capabilities (short-term memory may be switched off). */
    try {
      out.memoryEnabled = Boolean((await (await realFetch("/health")).json()).memory_enabled);
    } catch {
      out.memoryEnabled = null;
    }

    /* 1. Streaming chat, with /chat/stream stubbed so nothing is billed. */
    const LF = String.fromCharCode(10);
    const SEP = LF + LF;
    window.fetch = (url, options) => {
      if (String(url).includes("/chat/stream")) {
        if (!out.streamPayload) {
          try {
            out.streamPayload = JSON.parse(options.body);
          } catch {
            out.streamPayload = null;
          }
        }

        const conversationId = localStorage.getItem("leyna.conversation.v1");
        const done = {
          done: true,
          model: "gemma4:31b-cloud",
          prompt_tokens: 5,
          completion_tokens: 2,
        };
        if (conversationId) {
          done.conversation_id = conversationId;
          done.memory = {
            enabled: true,
            stored_messages: 2,
            window_messages: 2,
            estimated_tokens: 7,
            trimmed: false,
            keep_first: false,
          };
        }

        const frames = [
          'data: {"delta":"Hello "}' + SEP,
          'data: {"delta":"**world** from Leyna"}' + SEP,
          "data: " + JSON.stringify(done) + SEP,
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
    await sleep(1200);

    out.messageCount = document.querySelectorAll("#messages .bubble").length;
    out.userText = $("#messages .bubble-user")?.textContent ?? null;
    out.assistantText = $("#messages .bubble-assistant")?.textContent ?? null;
    out.assistantRenderedBold = Boolean($("#messages .bubble-assistant strong"));
    out.tokenChip = $("#messages .chip")?.textContent?.trim() ?? null;
    out.emptyStateHidden = $("#empty-state").classList.contains("hidden");
    out.historySaved = Boolean(localStorage.getItem("leyna.history.v1"));

    /* 1b. The chat picked up a conversation_id and sent only the new turn. */
    out.conversationId = localStorage.getItem("leyna.conversation.v1");
    out.sentConversationId = out.streamPayload?.conversation_id ?? null;
    out.sentMessageCount = out.streamPayload?.messages?.length ?? null;
    out.sentOnlyNewTurn = out.streamPayload?.messages?.[0]?.content === "ping";

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

    /* 2b. Memory tab: settings, the live chat, and the stored conversations. */
    $('[data-tab="memory"]').click();
    await sleep(1200);
    out.memoryPanelVisible = !$("#panel-memory").classList.contains("hidden");
    out.memoryCards = $("#memory-settings").querySelectorAll(".card").length;
    out.memoryRows = $("#memory-table-body").querySelectorAll("tr").length;
    out.memoryConversationMatches =
      $("#memory-conversation").textContent.trim() === out.conversationId;
    out.memoryWindowShown = /stored/.test($("#memory-window").textContent);

    /* 3. Escape closes the drawer; New chat replaces the conversation. */
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await sleep(400);
    out.drawerClosed = $("#debug-drawer").classList.contains("translate-x-full");

    $("#new-chat-btn").click();
    await sleep(1000);
    out.messagesAfterReset = $("#messages").children.length;
    out.emptyStateBack = !$("#empty-state").classList.contains("hidden");
    const replaced = localStorage.getItem("leyna.conversation.v1");
    out.conversationReplaced = Boolean(replaced) && replaced !== out.conversationId;

    /* 3b. Leave a transcript behind for the reload pass (see restoreTest). */
    $("#composer-input").value = "again";
    $("#composer-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await sleep(1000);
    out.afterThirdSend = document.querySelectorAll("#messages .bubble").length;

    window.fetch = realFetch;
    return out;
  })();
}

/**
 * Runs after a reload, with a conversation the server has been made to forget.
 * The client should rebuild the transcript from local storage and then re-seed
 * the server by resending the whole history under the same id.
 */
function restoreTest() {
  return (async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const $ = (selector) => document.querySelector(selector);
    const realFetch = window.fetch.bind(window);
    const out = {};

    out.storedConversationId = localStorage.getItem("leyna.conversation.v1");
    out.restoredBubbles = document.querySelectorAll("#messages .bubble").length;
    out.restoredUserText = $("#messages .bubble-user")?.textContent ?? null;
    out.restoredAssistantText = $("#messages .bubble-assistant")?.textContent ?? null;

    const LF = String.fromCharCode(10);
    const SEP = LF + LF;
    window.fetch = (url, options) => {
      if (String(url).includes("/chat/stream")) {
        try {
          out.reseedPayload = JSON.parse(options.body);
        } catch {
          out.reseedPayload = null;
        }
        const done = {
          done: true,
          model: "gemma4:31b-cloud",
          conversation_id: out.storedConversationId,
        };
        const frames = ['data: {"delta":"ok"}' + SEP, "data: " + JSON.stringify(done) + SEP];
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

    $("#composer-input").value = "next";
    $("#composer-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await sleep(1200);

    out.reseedConversationId = out.reseedPayload?.conversation_id ?? null;
    out.reseedMessageCount = out.reseedPayload?.messages?.length ?? null;
    out.afterResendBubbles = document.querySelectorAll("#messages .bubble").length;

    window.fetch = realFetch;
    return out;
  })();
}

const EXPECTED = {
  leynaBooted: true,
  themeDefault: "light",
  themeDefaultBg: "rgb(246, 247, 251)",
  themeToggled: "dark",
  themeToggledBg: "rgb(2, 6, 23)",
  themePersisted: "dark",
  themeAriaPressed: "true",
  themeRestored: "light",
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
  let checked = 0;

  const equal = (label, actual, want) => {
    checked += 1;
    if (actual !== want) {
      failures.push(`${label}: expected ${JSON.stringify(want)}, got ${JSON.stringify(actual)}`);
    }
  };
  const truthy = (label, actual) => {
    checked += 1;
    if (!actual) failures.push(`${label}: expected a truthy value, got ${JSON.stringify(actual)}`);
  };

  for (const [key, want] of Object.entries(EXPECTED)) equal(key, results[key], want);

  truthy("logLines", results.logLines >= 1);
  equal("themeInkChanged", results.themeDefaultInk !== results.themeToggledInk, true);
  truthy(
    "maskedKey",
    results.maskedKey === "not set" || String(results.maskedKey).includes("…"),
  );
  truthy("keySource", ["env", "debug-override", "unset"].includes(results.keySource));

  // The memory panel always renders, even when server-side memory is off.
  equal("memoryPanelVisible", results.memoryPanelVisible, true);
  equal("memoryCards", results.memoryCards, 6);
  truthy("memoryWindowShown", results.memoryWindowShown);

  if (results.memoryEnabled === true) {
    truthy(
      "conversationId",
      typeof results.conversationId === "string" && results.conversationId.length > 0,
    );
    equal("sentConversationId", results.sentConversationId, results.conversationId);
    equal("sentOnlyNewTurn", results.sentOnlyNewTurn, true);
    equal("memoryConversationMatches", results.memoryConversationMatches, true);
    truthy("memoryRows", results.memoryRows >= 1);
    equal("conversationReplaced", results.conversationReplaced, true);

    // Second pass, after a reload with a conversation the server forgot.
    equal("restoredBubbles", results.restoredBubbles, 2);
    equal("restoredUserText", results.restoredUserText, "again");
    equal("restoredAssistantText", results.restoredAssistantText, "Hello world from Leyna");
    equal("reseedConversationId", results.reseedConversationId, results.storedConversationId);
    equal("reseedMessageCount", results.reseedMessageCount, 3);
    equal("afterResendBubbles", results.afterResendBubbles, 4);
  }

  return { failures, checked };
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

    // The shipped UI points at the deployed backend; aim this run at the local
    // one before any page script executes.
    await cmd("Page.addScriptToEvaluateOnNewDocument", {
      source: "window.__LEXYNA_API_BASE__ = '';",
    });

    const waitForReady = async () => {
      let ready = false;
      for (let i = 0; i < 60 && !ready; i += 1) {
        await sleep(250);
        try {
          ready = (await evaluate("window.__leynaReady === true")) === true;
        } catch {
          /* execution context may not exist yet */
        }
      }
      if (!ready) throw new Error(`Web UI never became ready at ${BASE} — is the backend running?`);
    };

    await cmd("Page.navigate", { url: BASE });
    await waitForReady();
    await sleep(1200); // let the first /health call land

    const results = await evaluate(`(${pageTest.toString()})()`);

    // Second pass: make the server forget the conversation, reload, and check
    // that the client rebuilds the transcript and re-seeds the server.
    const forgotten = await evaluate("localStorage.getItem('leyna.conversation.v1')");
    if (forgotten) {
      await fetch(`${BASE}/conversations/${forgotten}`, { method: "DELETE" });
    }
    await cmd("Page.navigate", { url: BASE });
    await waitForReady();
    await sleep(800);
    Object.assign(results, await evaluate(`(${restoreTest.toString()})()`));

    if (forgotten) {
      await fetch(`${BASE}/conversations/${forgotten}`, { method: "DELETE" }).catch(() => {});
    }

    const { failures, checked } = check(results);

    console.log(JSON.stringify(results, null, 2));
    if (failures.length) {
      console.error(`\n✗ ${failures.length} of ${checked} checks failed:`);
      for (const failure of failures) console.error(`  - ${failure}`);
      process.exitCode = 1;
    } else {
      console.log(`\n✓ all ${checked} checks passed`);
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
