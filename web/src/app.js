/* Nimna web UI — a dependency-free client for the FastAPI backend.
 *
 * Handles: streaming chat over SSE, a persisted conversation, a health probe,
 * the debug drawer (token usage, live server logs, runtime API-key swap), and
 * the short-term memory the backend keeps per conversation_id.
 */

// Tailwind scans this file for class names. Dynamic class strings must appear
// literally somewhere in the source, so keep this safelist comment:
// log-debug log-info log-warning log-error bubble-user bubble-assistant
// bubble-error animate-bounce-dot animate-blink animate-fade-up animate-slide-in
// bg-emerald-500 dark:bg-emerald-400 bg-amber-500 dark:bg-amber-400
// bg-rose-500 dark:bg-rose-400 bg-ink-faint text-ink bg-elevated
// text-rose-600 dark:text-rose-300 text-emerald-600 dark:text-emerald-300
// text-violet-500 dark:text-violet-300

// The API base comes from localStorage override, or window/meta, or same-origin.
// Override via localStorage (set from Debug > Backend) takes precedence.
const API_BASE_KEY = "leyna.apiBase.v1";
const DEFAULT_API_BASE_META = (
  document.querySelector('meta[name="leyna-api-base"]')?.content ??
  "https://project-leyna.vercel.app"
)
  .trim()
  .replace(/\/+$/, "");

function getApiBase() {
  try {
    const saved = localStorage.getItem(API_BASE_KEY);
    if (saved !== null) {
      return saved.trim().replace(/\/+$/, "");
    }
  } catch {
    /* storage unavailable */
  }
  const win = window.__LEXYNA_API_BASE__;
  if (win) {
    return String(win).trim().replace(/\/+$/, "");
  }
  const meta = document.querySelector('meta[name="leyna-api-base"]')?.content ?? "";
  return meta.trim().replace(/\/+$/, "");
}

function setApiBase(url) {
  const value = (url ?? "").trim().replace(/\/+$/, "");
  try {
    if (value) {
      localStorage.setItem(API_BASE_KEY, value);
    } else {
      localStorage.removeItem(API_BASE_KEY);
    }
  } catch {
    /* storage unavailable */
  }
}

function resetApiBase() {
  try {
    localStorage.removeItem(API_BASE_KEY);
  } catch {
    /* storage unavailable */
  }
}

function formatApiBaseForDisplay(base) {
  if (!base) return "(same origin)";
  return base;
}

const HISTORY_KEY = "nimna.history.v1";
const CONVERSATION_KEY = "nimna.conversation.v1";
const ADMIN_KEY = "nimna.adminToken";
const AUTH_KEY = "nimna.auth";
const POLL_MS = 2000;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const canStream = typeof ReadableStream === "function" && "body" in Response.prototype;

const dom = {
  scroll: $("#chat-scroll"),
  messages: $("#messages"),
  empty: $("#empty-state"),
  form: $("#composer-form"),
  input: $("#composer-input"),
  send: $("#send-btn"),
  stop: $("#stop-btn"),
  newChat: $("#new-chat-btn"),
  debugBtn: $("#debug-btn"),
  themeBtn: $("#theme-btn"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
  drawer: $("#debug-drawer"),
  overlay: $("#debug-overlay"),
  debugClose: $("#debug-close"),
  debugStatus: $("#debug-status"),
  toasts: $("#toasts"),
  panelUsage: $("#panel-usage"),
  panelLogs: $("#panel-logs"),
  panelKey: $("#panel-api-key"),
  panelMemory: $("#panel-memory"),
  panelDb: $("#panel-db"),
  panelBackend: $("#panel-backend"),
  dbLogs: $("#db-logs"),
  dbEmpty: $("#db-empty"),
  dbRefresh: $("#db-refresh"),
  dbClear: $("#db-clear"),
  panelBackend: $("#panel-backend"),
  usageTotals: $("#usage-totals"),
  usageBody: $("#usage-table-body"),
  usageEmpty: $("#usage-empty"),
  usageClear: $("#usage-clear"),
  logsConsole: $("#logs-console"),
  logsEmpty: $("#logs-empty"),
  logsLevel: $("#logs-level"),
  logsAutoscroll: $("#logs-autoscroll"),
  logsClear: $("#logs-clear"),
  keyMasked: $("#key-masked"),
  keySource: $("#key-source"),
  keyForm: $("#key-form"),
  keyInput: $("#key-input"),
  keyPersist: $("#key-persist"),
  keyApply: $("#key-apply"),
  keyRevert: $("#key-revert"),
  keyFeedback: $("#key-feedback"),
  adminToken: $("#admin-token"),
  memorySettings: $("#memory-settings"),
  memoryConversation: $("#memory-conversation"),
  memoryWindow: $("#memory-window"),
  memoryBody: $("#memory-table-body"),
  memoryEmpty: $("#memory-empty"),
  memoryClear: $("#memory-clear"),
  memoryForget: $("#memory-forget"),
  backendCurrent: $("#backend-current"),
  backendForm: $("#backend-form"),
  backendInput: $("#backend-input"),
  backendTest: $("#backend-test"),
  backendApply: $("#backend-apply"),
  backendReset: $("#backend-reset"),
  backendFeedback: $("#backend-feedback"),
  backendPresetLocal: $("#backend-preset-local"),
  backendPresetRemote: $("#backend-preset-remote"),
  backendPresetSame: $("#backend-preset-same"),
  backendCurrent: $("#backend-current"),
  backendForm: $("#backend-form"),
  backendInput: $("#backend-input"),
  backendTest: $("#backend-test"),
  backendApply: $("#backend-apply"),
  backendReset: $("#backend-reset"),
  backendPresetLocal: $("#backend-preset-local"),
  backendPresetRemote: $("#backend-preset-remote"),
  backendPresetSame: $("#backend-preset-same"),
  backendFeedback: $("#backend-feedback"),
};

const state = {
  messages: [],
  busy: false,
  controller: null,
  debugOpen: false,
  activeTab: "usage",
  lastLogId: 0,
  timer: null,
  conversationId: null,
  // "unknown" until proven otherwise; "known" once the server holds it; "local"
  // when the server has forgotten it but we still have the transcript.
  conversationState: "unknown",
  lastMemory: null,
  health: { online: false, configured: false, model: "", memoryEnabled: null },
};

let nextId = 1;

/* -------------------------------------------------------------------------- */
/* Small helpers                                                              */
/* -------------------------------------------------------------------------- */
const el = (tag, className = "") => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char],
  );

const fmt = (value) => (value === null || value === undefined ? "—" : value.toLocaleString());

const clockTime = (iso) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString();
};

/** A deliberately small Markdown subset, escaped before any markup is added. */
function renderMarkdown(source) {
  if (!source) return "";

  const blocks = [];
  let text = escapeHtml(source).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<pre><code data-lang="${lang}">${code.replace(/\n$/, "")}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });

  text = text
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    );

  return text
    .split(/\n{2,}/)
    .map((paragraph) => {
      const trimmed = paragraph.trim();
      if (!trimmed) return "";
      if (/^\u0000\d+\u0000$/.test(trimmed)) return trimmed;
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    })
    .join("")
    .replace(/\u0000(\d+)\u0000/g, (_, index) => blocks[Number(index)]);
}

/* -------------------------------------------------------------------------- */
/* Toasts                                                                     */
/* -------------------------------------------------------------------------- */
function toast(message, kind = "info") {
  const node = el(
    "div",
    `card pointer-events-auto animate-slide-in px-4 py-2 text-sm ${
      kind === "error"
        ? "border-rose-500/40 text-rose-600 dark:text-rose-200"
        : "text-ink"
    }`,
  );
  node.textContent = message;
  dom.toasts.appendChild(node);
  setTimeout(() => {
    node.classList.add("opacity-0", "transition-opacity");
    setTimeout(() => node.remove(), 300);
  }, 4000);
}

/* -------------------------------------------------------------------------- */
/* HTTP                                                                       */
/* -------------------------------------------------------------------------- */
function getCurrentApiBase() {
  return getApiBase();
}

async function readError(response) {
  try {
    const data = await response.json();
    if (data && typeof data.detail === "string") return data.detail;
    if (data && data.detail) return JSON.stringify(data.detail);
  } catch {
    /* fall through to the status line */
  }
  return `${response.status} ${response.statusText}`.trim();
}

function adminHeaders() {
  const token = localStorage.getItem(ADMIN_KEY);
  return token ? { "X-Admin-Token": token } : {};
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${getApiBase()}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

function debugRequest(path, options = {}) {
  return apiRequest(`/debug${path}`, {
    ...options,
    headers: { ...adminHeaders(), ...(options.headers ?? {}) },
  });
}

/* -------------------------------------------------------------------------- */
/* Health                                                                     */
/* -------------------------------------------------------------------------- */
async function refreshHealth() {
  try {
    const response = await fetch(`${getApiBase()}/health`);
    if (!response.ok) throw new Error();
    const data = await response.json();
    state.health = {
      online: true,
      configured: Boolean(data.configured),
      model: data.model,
      memoryEnabled: Boolean(data.memory_enabled),
    };
  } catch {
    state.health = { online: false, configured: false, model: "", memoryEnabled: null };
  }

  const { online, configured, model } = state.health;
  let dot = "bg-ink-faint";
  let label = "Backend offline";
  if (online && configured) {
    dot = "bg-emerald-500 dark:bg-emerald-400";
    label = model || "Ready";
  } else if (online) {
    dot = "bg-amber-500 dark:bg-amber-400";
    label = "No API key";
  }
  dom.statusDot.className = `h-2 w-2 rounded-full ${dot}`;
  dom.statusText.textContent = label;
}

/* -------------------------------------------------------------------------- */
/* Messages                                                                   */
/* -------------------------------------------------------------------------- */
const typingIndicator = () => `
  <span class="inline-flex items-center gap-1 py-1">
    <span class="h-1.5 w-1.5 rounded-full bg-ink-faint animate-bounce-dot"></span>
    <span class="h-1.5 w-1.5 rounded-full bg-ink-faint animate-bounce-dot [animation-delay:150ms]"></span>
    <span class="h-1.5 w-1.5 rounded-full bg-ink-faint animate-bounce-dot [animation-delay:300ms]"></span>
  </span>`;

const cursor = () =>
  '<span class="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-violet-400 animate-blink"></span>';

function createMessageNode(message) {
  const row = el("div", "flex flex-col gap-1");
  if (message.role === "user") row.classList.add("items-end");

  const bubble = el("div", "bubble");
  const content = el("div", "markdown");
  bubble.appendChild(content);

  const meta = el("div", "flex items-center gap-2 px-1 text-[0.68rem] text-ink-faint");

  row.append(bubble, meta);
  message.node = { row, bubble, content, meta };
  paintMessage(message);
  return row;
}

function paintMessage(message) {
  const { bubble, content, meta } = message.node;

  bubble.classList.toggle("bubble-user", message.role === "user");
  bubble.classList.toggle("bubble-assistant", message.role === "assistant" && !message.error);
  bubble.classList.toggle("bubble-error", Boolean(message.error));

  if (message.pending && !message.content) {
    content.innerHTML = typingIndicator();
  } else {
    content.innerHTML =
      renderMarkdown(message.content || "") + (message.pending ? cursor() : "");
  }

  const chips = [];
  if (message.error)
    chips.push(`<span class="text-rose-600 dark:text-rose-400">⚠ ${escapeHtml(message.error)}</span>`);
  if (message.trimmed) {
    chips.push(
      '<span class="chip !py-0.5" title="Older messages were dropped to fit the memory token budget">✂ trimmed</span>',
    );
  }
  if (message.tokens) {
    chips.push(
      `<span class="chip !py-0.5" title="prompt / completion tokens">↑ ${fmt(
        message.tokens.prompt,
      )} · ↓ ${fmt(message.tokens.completion)}</span>`,
    );
  }
  if (message.model) chips.push(`<span class="text-ink-faint">${escapeHtml(message.model)}</span>`);
  if (message.role === "assistant" && message.content && !message.pending) {
    chips.push(
      `<button type="button" data-copy="${message.id}" class="cursor-pointer transition hover:text-ink">Copy</button>`,
    );
  }
  meta.innerHTML = chips.join("");
  meta.classList.toggle("hidden", chips.length === 0);
}

function schedulePaint(message) {
  if (message._raf) return;
  message._raf = requestAnimationFrame(() => {
    message._raf = null;
    paintMessage(message);
    if (nearBottom()) scrollToBottom();
  });
}

function mountMessage(message) {
  dom.messages.appendChild(createMessageNode(message));
}

function addMessage(partial) {
  const message = {
    id: nextId++,
    role: "assistant",
    content: "",
    tokens: null,
    model: null,
    error: null,
    trimmed: false,
    pending: false,
    ...partial,
  };
  state.messages.push(message);
  mountMessage(message);
  syncEmptyState();
  scrollToBottom(true);
  return message;
}

function syncEmptyState() {
  dom.empty.classList.toggle("hidden", state.messages.length > 0);
}

function nearBottom() {
  return dom.scroll.scrollHeight - dom.scroll.scrollTop - dom.scroll.clientHeight < 140;
}

function scrollToBottom(force = false) {
  if (force || nearBottom()) dom.scroll.scrollTop = dom.scroll.scrollHeight;
}

/* -------------------------------------------------------------------------- */
/* Persistence                                                                */
/* -------------------------------------------------------------------------- */
function saveHistory() {
  try {
    const payload = state.messages
      .filter((message) => message.content || message.error)
      .map(({ role, content, tokens, model, error, trimmed }) => ({
        role,
        content,
        tokens,
        model,
        error,
        trimmed,
      }));
    localStorage.setItem(HISTORY_KEY, JSON.stringify(payload));
  } catch {
    /* storage is best-effort */
  }
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return;
    state.messages = parsed
      .filter((message) => message && typeof message.content === "string" && message.content)
      .map((message) => ({
        id: nextId++,
        role: message.role === "user" ? "user" : "assistant",
        content: message.content,
        tokens: message.tokens ?? null,
        model: message.model ?? null,
        error: message.error ?? null,
        trimmed: Boolean(message.trimmed),
        pending: false,
      }));
  } catch {
    state.messages = [];
  }
}

function saveConversationId() {
  try {
    if (state.conversationId) localStorage.setItem(CONVERSATION_KEY, state.conversationId);
    else localStorage.removeItem(CONVERSATION_KEY);
  } catch {
    /* storage is best-effort */
  }
}

/**
 * Rebuild the transcript from the server when it still knows the conversation.
 * Returns false (and leaves the local history in place) when it does not.
 */
async function restoreConversation() {
  let stored = null;
  try {
    stored = localStorage.getItem(CONVERSATION_KEY);
  } catch {
    return false;
  }
  if (!stored) return false;

  state.conversationId = stored;
  try {
    const response = await fetch(`${getApiBase()}/conversations/${encodeURIComponent(stored)}`);
    if (!response.ok) {
      // Forgotten by the server (restart or TTL). Keep the transcript and let
      // the next request re-seed it.
      state.conversationState = "local";
      return false;
    }
    const data = await response.json();
    state.messages = (data.messages ?? [])
      .filter((message) => message.role === "user" || message.role === "assistant")
      .map((message) => ({
        id: nextId++,
        role: message.role,
        content: message.content,
        tokens: null,
        model: null,
        error: null,
        trimmed: false,
        pending: false,
      }));
    // An empty transcript means there is nothing to restore from the server, so
    // mark the conversation as needing a re-seed from local history.
    state.conversationState = state.messages.length > 0 ? "known" : "local";
    return state.messages.length > 0;
  } catch {
    state.conversationState = "local";
    return false;
  }
}

/* -------------------------------------------------------------------------- */
/* Memory                                                                     */
/* -------------------------------------------------------------------------- */
async function memoryEnabled() {
  if (state.health.memoryEnabled === null) await refreshHealth();
  return state.health.memoryEnabled === true;
}

/**
 * The conversation_id to send with the next turn, creating one if needed.
 * Returns null when the backend has short-term memory switched off.
 */
async function ensureConversation() {
  if (state.conversationId && state.conversationState === "known") return state.conversationId;
  if (!(await memoryEnabled())) {
    state.conversationId = null;
    state.conversationState = "unknown";
    saveConversationId();
    return null;
  }
  // The server forgot this conversation but we still have its transcript: reuse
  // the id and send the whole history once, so the server can re-seed itself.
  if (state.conversationState === "local" && state.conversationId) return state.conversationId;

  try {
    const data = await apiRequest("/conversations", { method: "POST" });
    state.conversationId = data.conversation_id;
    state.conversationState = "known";
    saveConversationId();
    return state.conversationId;
  } catch {
    return null;
  }
}

/* -------------------------------------------------------------------------- */
/* Chat                                                                       */
/* -------------------------------------------------------------------------- */
function applyDone(message, event) {
  message.model = event.model ?? message.model;
  message.tokens = {
    prompt: event.prompt_tokens ?? null,
    completion: event.completion_tokens ?? null,
  };
  message.trimmed = Boolean(event.memory?.trimmed);
  if (event.conversation_id) {
    state.conversationId = event.conversation_id;
    state.conversationState = "known";
    saveConversationId();
  }
  if (event.memory) state.lastMemory = event.memory;
}

async function streamReply(payload, message, signal) {
  if (!canStream) {
    const response = await fetch(`${getApiBase()}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok) throw new Error(await readError(response));
    const data = await response.json();
    message.content = data.message?.content ?? "";
    applyDone(message, data);
    paintMessage(message);
    return;
  }

  const response = await fetch(`${getApiBase()}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (!raw) continue;

        let event;
        try {
          event = JSON.parse(raw);
        } catch {
          continue;
        }

        if (event.error) throw new Error(event.error);
        if (typeof event.delta === "string" && event.delta) {
          message.content += event.delta;
          schedulePaint(message);
        }
        if (event.done) applyDone(message, event);
      }
    }
  }
}

async function sendMessage(rawText) {
  const content = rawText.trim();
  if (!content || state.busy) return;

  // Snapshot the transcript *before* this turn so it can re-seed a server that
  // has forgotten the conversation.
  const priorHistory = state.messages
    .filter((message) => message.content)
    .map(({ role, content: text }) => ({ role, content: text }));

  addMessage({ role: "user", content });
  dom.input.value = "";
  autoGrow();

  const reply = addMessage({ role: "assistant", pending: true });
  const controller = new AbortController();
  state.controller = controller;
  setBusy(true);

  const conversationId = await ensureConversation();
  // With server-side memory the server owns the transcript, so send only the new
  // turn. Otherwise (or when re-seeding a forgotten conversation) send it all.
  const messages =
    conversationId && state.conversationState === "known"
      ? [{ role: "user", content }]
      : [...priorHistory, { role: "user", content }];
  const payload = conversationId ? { conversation_id: conversationId, messages } : { messages };

  try {
    await streamReply(payload, reply, controller.signal);
  } catch (error) {
    if (error.name === "AbortError") {
      if (!reply.content) reply.content = "_Generation stopped._";
    } else {
      reply.error = error.message;
      toast(error.message, "error");
    }
  } finally {
    reply.pending = false;
    reply._raf = null;
    state.controller = null;
    paintMessage(reply);
    setBusy(false);
    saveHistory();
    scrollToBottom();
    if (state.debugOpen && state.activeTab === "memory") void refreshDebug();
  }
}

function setBusy(busy) {
  state.busy = busy;
  dom.stop.classList.toggle("hidden", !busy);
  dom.send.classList.toggle("hidden", busy);
  updateSendState();
}

function updateSendState() {
  dom.send.disabled = state.busy || dom.input.value.trim().length === 0;
}

function autoGrow() {
  dom.input.style.height = "auto";
  dom.input.style.height = `${Math.min(dom.input.scrollHeight, 160)}px`;
}

async function resetConversation() {
  if (state.busy) state.controller?.abort();

  const previous = state.conversationId;
  state.messages = [];
  state.lastLogId = 0;
  state.lastMemory = null;
  state.conversationId = null;
  state.conversationState = "unknown";
  dom.messages.innerHTML = "";
  syncEmptyState();
  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch {
    /* ignore */
  }
  saveConversationId();

  if (previous) {
    try {
      await apiRequest(`/conversations/${encodeURIComponent(previous)}`, { method: "DELETE" });
    } catch {
      /* already gone — nothing to do */
    }
  }
  await ensureConversation();
  if (state.debugOpen && state.activeTab === "memory") void refreshDebug();
  dom.input.focus();
}

/* -------------------------------------------------------------------------- */
/* Debug drawer                                                               */
/* -------------------------------------------------------------------------- */
function setFeedback(text, tone = "text-ink-soft") {
  dom.keyFeedback.className = `min-h-4 text-xs ${tone}`;
  dom.keyFeedback.textContent = text;
}

function selectTab(tab) {
  state.activeTab = tab;
  const tabs = $$("[data-tab]");
  tabs.forEach((button) => button.classList.toggle("tab-active", button.dataset.tab === tab));
  dom.panelUsage.classList.toggle("hidden", tab !== "usage");
  dom.panelLogs.classList.toggle("hidden", tab !== "logs");
  dom.panelKey.classList.toggle("hidden", tab !== "api-key");
  dom.panelMemory.classList.toggle("hidden", tab !== "memory");
  if (dom.panelDb) {
    dom.panelDb.classList.toggle("hidden", tab !== "db");
  }
  if (dom.panelBackend) {
    dom.panelBackend.classList.toggle("hidden", tab !== "backend");
  }
  if (tab === "backend") {
    refreshBackendPanel();
  }
  if (tab === "db") {
    void refreshDbLogs();
  }
  void refreshDebug();
}

function openDebug() {
  state.debugOpen = true;
  dom.drawer.classList.remove("translate-x-full");
  dom.drawer.setAttribute("aria-hidden", "false");
  dom.overlay.classList.remove("hidden");
  dom.debugBtn.setAttribute("aria-expanded", "true");
  void refreshDebug();
  clearInterval(state.timer);
  state.timer = setInterval(() => void refreshDebug(), POLL_MS);
}

function closeDebug() {
  state.debugOpen = false;
  dom.drawer.classList.add("translate-x-full");
  dom.drawer.setAttribute("aria-hidden", "true");
  dom.overlay.classList.add("hidden");
  dom.debugBtn.setAttribute("aria-expanded", "false");
  clearInterval(state.timer);
  state.timer = null;
}

async function refreshDebug() {
  try {
    if (state.activeTab === "usage") await renderUsage();
    else if (state.activeTab === "logs") await renderLogs();
    else if (state.activeTab === "memory") await renderMemory();
    else await renderKeyState();
    dom.debugStatus.textContent = "";
  } catch (error) {
    dom.debugStatus.textContent = "unavailable";
    if (!dom.debugOpen) return;
    if (state.activeTab === "logs") {
      dom.logsEmpty.textContent = `Debug API unavailable — ${error.message}`;
      dom.logsEmpty.classList.remove("hidden");
    } else if (state.activeTab === "memory") {
      dom.memoryEmpty.textContent = `Debug API unavailable — ${error.message}`;
      dom.memoryEmpty.classList.remove("hidden");
    }
  }
}

const statCard = (label, value, tone = "text-ink") => `
  <div class="card p-3">
    <p class="text-[0.62rem] font-semibold tracking-wide text-ink-faint uppercase">${label}</p>
    <p class="mt-1 text-lg font-semibold ${tone}">${value}</p>
  </div>`;

function usageRow(record) {
  const dot = record.ok
    ? '<span class="h-1.5 w-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400"></span>'
    : '<span class="h-1.5 w-1.5 rounded-full bg-rose-500 dark:bg-rose-400"></span>';
  return `<tr class="text-ink-soft" title="${escapeHtml(record.error || record.model)}">
      <td class="px-3 py-2 font-mono text-[0.68rem] whitespace-nowrap text-ink-faint">${clockTime(record.time)}</td>
      <td class="px-3 py-2">
        <span class="inline-flex items-center gap-1.5 whitespace-nowrap">${dot}${escapeHtml(record.endpoint)}</span>
      </td>
      <td class="px-3 py-2 text-right font-mono">${fmt(record.prompt_tokens)}</td>
      <td class="px-3 py-2 text-right font-mono">${fmt(record.completion_tokens)}</td>
      <td class="px-3 py-2 text-right font-mono text-ink-faint">${Math.round(record.latency_ms)}</td>
    </tr>`;
}

async function renderUsage() {
  const data = await debugRequest("/usage?limit=50");
  const totals = data.totals;
  dom.usageTotals.innerHTML = [
    statCard("Requests", fmt(totals.requests)),
    statCard("Prompt tokens", fmt(totals.prompt_tokens)),
    statCard("Reply tokens", fmt(totals.completion_tokens)),
    statCard("Total tokens", fmt(totals.total_tokens)),
    statCard("Errors", fmt(totals.errors), totals.errors ? "text-rose-600 dark:text-rose-300" : "text-ink"),
    statCard(
      "Success rate",
      totals.requests ? `${Math.round((totals.ok / totals.requests) * 100)}%` : "—",
      totals.requests && totals.errors === 0 ? "text-emerald-600 dark:text-emerald-300" : "text-ink",
    ),
  ].join("");
  dom.usageBody.innerHTML = data.records.map(usageRow).join("");
  dom.usageEmpty.classList.toggle("hidden", data.records.length > 0);
}

function logLine(record) {
  const level = (record.level || "INFO").toUpperCase();
  const node = el("div", `log-line log-${level.toLowerCase()}`);
  node.innerHTML = `
    <span class="shrink-0 text-ink-faint">${clockTime(record.time)}</span>
    <span class="w-16 shrink-0">${escapeHtml(level)}</span>
    <span class="min-w-0 flex-1 break-words whitespace-pre-wrap">${escapeHtml(record.message)}</span>`;
  return node;
}

async function renderLogs() {
  const level = dom.logsLevel.value;
  const data = await debugRequest(`/logs?after=${state.lastLogId}&level=${level}&limit=500`);
  if (!data.records.length) return;

  dom.logsEmpty.classList.add("hidden");
  for (const record of data.records) {
    dom.logsConsole.appendChild(logLine(record));
    state.lastLogId = Math.max(state.lastLogId, record.id);
  }

  const lines = dom.logsConsole.querySelectorAll(".log-line");
  for (let index = 0; index < lines.length - 800; index += 1) lines[index].remove();

  if (dom.logsAutoscroll.checked) dom.logsConsole.scrollTop = dom.logsConsole.scrollHeight;
}

async function renderKeyState() {
  const data = await debugRequest("/state");
  dom.keyMasked.textContent = data.api_key.masked || "not set";
  dom.keySource.textContent = data.api_key.source;
}

function setBackendFeedback(text, tone = "text-ink-faint") {
  if (!dom.backendFeedback) return;
  dom.backendFeedback.className = `min-h-4 text-xs ${tone}`;
  dom.backendFeedback.textContent = text;
}

function refreshBackendPanel() {
  if (!dom.backendCurrent) return;
  const base = getCurrentApiBase();
  dom.backendCurrent.textContent = base ? base : "(same origin)";
  if (dom.backendInput) {
    let saved = "";
    try {
      saved = localStorage.getItem(API_BASE_KEY) || "";
    } catch {
      saved = "";
    }
    dom.backendInput.value = saved;
  }
  setBackendFeedback("");
}

async function testBackendConnection() {
  if (!dom.backendInput) return;
  const val = dom.backendInput.value.trim();
  const candidate = val ? val.replace(/\/+$/, "") : "";
  setBackendFeedback("Testing…", "text-ink-faint");
  try {
    const res = await fetch(`${candidate}/health`, { method: "GET" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    setBackendFeedback(
      `OK — ${data.model || "connected"}${data.configured ? "" : " (no API key configured)"}`,
      "text-emerald-600 dark:text-emerald-300",
    );
  } catch (error) {
    setBackendFeedback(`Failed: ${error.message}`, "text-rose-600 dark:text-rose-300");
  }
}

function memoryRow(item) {
  const current = item.conversation_id === state.conversationId;
  const marker = current
    ? ' <span class="text-violet-500 dark:text-violet-300" title="This chat">←</span>'
    : "";
  return `<tr class="text-ink-soft ${current ? "bg-elevated" : ""}">
      <td class="px-3 py-2 font-mono text-[0.68rem] break-all">${escapeHtml(item.conversation_id)}${marker}</td>
      <td class="px-3 py-2 text-right font-mono">${fmt(item.messages)}</td>
      <td class="px-3 py-2 text-right whitespace-nowrap text-ink-faint">${clockTime(item.updated_at)}</td>
    </tr>`;
}

async function renderMemory() {
  const data = await debugRequest("/memory");
  const settings = data.settings;

  dom.memorySettings.innerHTML = [
    statCard(
      "Memory",
      settings.enabled ? "on" : "off",
      settings.enabled ? "text-emerald-600 dark:text-emerald-300" : "text-ink",
    ),
    statCard("Token budget", fmt(settings.token_budget)),
    statCard("Max messages", fmt(settings.max_messages)),
    statCard("Max chats", fmt(settings.max_conversations)),
    statCard("TTL (min)", fmt(settings.ttl_minutes)),
    statCard("Keep first", settings.keep_first ? "yes" : "no"),
  ].join("");

  dom.memoryConversation.textContent = state.conversationId ?? "none — requests are stateless";
  const window_ = state.lastMemory;
  const stored = data.items.find((item) => item.conversation_id === state.conversationId);
  if (window_) {
    dom.memoryWindow.textContent =
      `${window_.stored_messages} message(s) stored → ${window_.window_messages} sent · ` +
      `~${window_.estimated_tokens} tokens${window_.trimmed ? " · trimmed to fit" : ""}`;
  } else if (stored) {
    dom.memoryWindow.textContent = `${stored.messages} message(s) stored on the server.`;
  } else {
    dom.memoryWindow.textContent = "No server-side history for this chat yet.";
  }
  dom.memoryForget.disabled = !state.conversationId;

  dom.memoryBody.innerHTML = data.items.map(memoryRow).join("");
  dom.memoryEmpty.classList.toggle("hidden", data.items.length > 0);
}

function setBackendFeedback(text, tone = "text-ink-soft") {
  if (!dom.backendFeedback) return;
  dom.backendFeedback.className = `min-h-4 text-xs ${tone}`;
  dom.backendFeedback.textContent = text || "";
}

function refreshBackendPanel() {
  if (!dom.backendCurrent) return;
  dom.backendCurrent.textContent = formatApiBaseForDisplay(getApiBase());
  if (dom.backendInput) {
    dom.backendInput.value = getApiBase();
  }
  setBackendFeedback("");
}

async function testBackendConnection(base) {
  const candidate = (base ?? "").trim().replace(/\/+$/, "");
  try {
    const response = await fetch(`${candidate}/health`, { method: "GET" });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    const data = await response.json();
    return {
      ok: true,
      model: data.model || "",
      configured: Boolean(data.configured),
      memoryEnabled: Boolean(data.memory_enabled),
    };
  } catch (error) {
    throw error;
  }
}

async function refreshDbLogs() {
  if (!dom.dbLogs) return;
  try {
    const data = await debugRequest("/db-logs?limit=50");
    const convs = data.conversations || [];
    dom.dbLogs.innerHTML = "";
    if (!convs.length) {
      if (dom.dbEmpty) dom.dbEmpty.classList.remove("hidden");
      return;
    }
    if (dom.dbEmpty) dom.dbEmpty.classList.add("hidden");
    for (const c of convs) {
      const card = el("div", "card p-3 space-y-2");
      const header = el("div", "flex items-center gap-2");
      const id = el("p", "flex-1 font-mono text-[0.68rem] break-all text-ink");
      id.textContent = c.conversation_id;
      const count = el("span", "chip !py-0.5");
      count.textContent = `${c.message_count} msg`;
      header.append(id, count);
      card.appendChild(header);
      const list = el("div", "space-y-1");
      for (const m of c.messages || []) {
        const row = el("div", "text-xs");
        const role = el("span", "text-ink-faint");
        role.textContent = m.role + ": ";
        const content = el("span", "text-ink-soft break-words");
        content.textContent = m.content || "";
        row.append(role, content);
        list.appendChild(row);
      }
      card.appendChild(list);
      dom.dbLogs.appendChild(card);
    }
  } catch (error) {
    if (dom.dbEmpty) {
      dom.dbEmpty.textContent = `Failed: ${error.message}`;
      dom.dbEmpty.classList.remove("hidden");
    }
  }
}

/* -------------------------------------------------------------------------- */
/* Wiring                                                                     */
/* -------------------------------------------------------------------------- */
dom.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void sendMessage(dom.input.value);
});

dom.input.addEventListener("input", () => {
  autoGrow();
  updateSendState();
});

dom.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void sendMessage(dom.input.value);
  }
});

dom.stop.addEventListener("click", () => state.controller?.abort());
dom.newChat.addEventListener("click", () => void resetConversation());

dom.messages.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const message = state.messages.find((item) => item.id === Number(button.dataset.copy));
  if (!message) return;
  try {
    await navigator.clipboard.writeText(message.content);
    toast("Copied to clipboard.");
  } catch {
    toast("Could not copy.", "error");
  }
});

$$("[data-suggestion]").forEach((button) => {
  button.addEventListener("click", () => {
    dom.input.value = button.dataset.suggestion ?? "";
    autoGrow();
    updateSendState();
    dom.input.focus();
  });
});

dom.debugBtn.addEventListener("click", () => (state.debugOpen ? closeDebug() : openDebug()));
dom.debugClose.addEventListener("click", closeDebug);
dom.overlay.addEventListener("click", closeDebug);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.debugOpen) closeDebug();
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (button && button.closest("#debug-drawer")) {
    selectTab(button.dataset.tab);
  }
});

if (dom.backendPresetLocal && dom.backendInput) {
  dom.backendPresetLocal.addEventListener("click", () => {
    dom.backendInput.value = "http://localhost:8000";
  });
}
if (dom.backendPresetRemote && dom.backendInput) {
  dom.backendPresetRemote.addEventListener("click", () => {
    dom.backendInput.value = "https://project-leyna.vercel.app";
  });
}
if (dom.backendPresetSame && dom.backendInput) {
  dom.backendPresetSame.addEventListener("click", () => {
    dom.backendInput.value = "";
  });
}

if (dom.backendTest) {
  dom.backendTest.addEventListener("click", (e) => {
    e.preventDefault();
    void testBackendConnection();
  });
}

if (dom.backendForm && dom.backendInput) {
  dom.backendForm.addEventListener("submit", (e) => {
    e.preventDefault();
    setApiBase(dom.backendInput.value);
    toast("Backend updated. Reloading…");
    setTimeout(() => {
      window.location.reload();
    }, 400);
  });
}

if (dom.backendReset) {
  dom.backendReset.addEventListener("click", (e) => {
    e.preventDefault();
    resetApiBase();
    if (dom.backendInput) dom.backendInput.value = "";
    setBackendFeedback("Reset to default. Reloading…", "text-ink-faint");
    toast("Reset to default. Reloading…");
    setTimeout(() => {
      window.location.reload();
    }, 400);
  });
}

dom.usageClear.addEventListener("click", async () => {
  await debugRequest("/usage", { method: "DELETE" });
  await renderUsage();
});

dom.logsClear.addEventListener("click", async () => {
  await debugRequest("/logs", { method: "DELETE" });
  dom.logsConsole.querySelectorAll(".log-line").forEach((line) => line.remove());
  state.lastLogId = 0;
  dom.logsEmpty.textContent = "Waiting for log output…";
  dom.logsEmpty.classList.remove("hidden");
});

dom.logsLevel.addEventListener("change", () => {
  state.lastLogId = 0;
  dom.logsConsole.querySelectorAll(".log-line").forEach((line) => line.remove());
  dom.logsEmpty.classList.remove("hidden");
  void refreshDebug();
});

dom.logsAutoscroll.addEventListener("change", () => {
  if (dom.logsAutoscroll.checked) dom.logsConsole.scrollTop = dom.logsConsole.scrollHeight;
});

dom.memoryClear.addEventListener("click", async () => {
  await debugRequest("/memory", { method: "DELETE" });
  state.lastMemory = null;
  if (state.conversationState === "known") state.conversationState = "local";
  await renderMemory();
  toast("Forgot every stored conversation.");
});

dom.memoryForget.addEventListener("click", async () => {
  const id = state.conversationId;
  if (!id) return;
  try {
    await apiRequest(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  // Keep the visible transcript; the next turn re-seeds the same id.
  state.conversationState = "local";
  state.lastMemory = null;
  await renderMemory();
  toast("This chat was forgotten on the server.");
});

dom.keyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  dom.keyApply.disabled = true;
  setFeedback("Applying…");
  try {
    await debugRequest("/api-key", {
      method: "POST",
      body: JSON.stringify({ api_key: dom.keyInput.value.trim(), persist: dom.keyPersist.checked }),
    });
    dom.keyInput.value = "";
    dom.keyPersist.checked = false;
    await renderKeyState();
    await refreshHealth();
    setFeedback("API key updated.", "text-emerald-600 dark:text-emerald-300");
    toast("API key updated.");
  } catch (error) {
    setFeedback(error.message, "text-rose-600 dark:text-rose-300");
  } finally {
    dom.keyApply.disabled = false;
  }
});

dom.keyRevert.addEventListener("click", async () => {
  dom.keyRevert.disabled = true;
  try {
    await debugRequest("/api-key", { method: "DELETE" });
    await renderKeyState();
    await refreshHealth();
    setFeedback("Reverted to the .env key.", "text-emerald-600 dark:text-emerald-300");
  } catch (error) {
    setFeedback(error.message, "text-rose-600 dark:text-rose-300");
  } finally {
    dom.keyRevert.disabled = false;
  }
});

dom.adminToken.addEventListener("input", () => {
  const token = dom.adminToken.value.trim();
  if (token) localStorage.setItem(ADMIN_KEY, token);
  else localStorage.removeItem(ADMIN_KEY);
  void refreshDebug();
});

if (dom.dbRefresh) {
  dom.dbRefresh.addEventListener("click", () => void refreshDbLogs());
}
if (dom.dbClear) {
  dom.dbClear.addEventListener("click", async () => {
    try {
      await debugRequest("/db-logs", { method: "DELETE" });
      toast("DB logs cleared");
      await refreshDbLogs();
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

if (dom.backendPresetLocal) {
  dom.backendPresetLocal.addEventListener("click", () => {
    if (dom.backendInput) dom.backendInput.value = "http://localhost:8000";
    setBackendFeedback("Set to http://localhost:8000");
  });
}
if (dom.backendPresetRemote) {
  dom.backendPresetRemote.addEventListener("click", () => {
    if (dom.backendInput) dom.backendInput.value = DEFAULT_API_BASE_META;
    setBackendFeedback("Set to remote default");
  });
}
if (dom.backendPresetSame) {
  dom.backendPresetSame.addEventListener("click", () => {
    if (dom.backendInput) dom.backendInput.value = "";
    setBackendFeedback("Set to same origin");
  });
}
if (dom.backendTest) {
  dom.backendTest.addEventListener("click", async () => {
    const base = dom.backendInput ? dom.backendInput.value : getApiBase();
    dom.backendTest.disabled = true;
    setBackendFeedback("Testing…");
    try {
      const result = await testBackendConnection(base);
      const status = result.configured ? "ready" : "no API key";
      setBackendFeedback(
        `OK — ${result.model || "unknown model"} (${status})`,
        "text-emerald-600 dark:text-emerald-300",
      );
    } catch (error) {
      setBackendFeedback(`Failed: ${error.message}`, "text-rose-600 dark:text-rose-300");
    } finally {
      dom.backendTest.disabled = false;
    }
  });
}
if (dom.backendReset) {
  dom.backendReset.addEventListener("click", () => {
    resetApiBase();
    toast("Backend reset to default");
    setTimeout(() => location.reload(), 200);
  });
}
if (dom.backendForm) {
  dom.backendForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const base = dom.backendInput ? dom.backendInput.value : "";
    setApiBase(base);
    toast("Backend updated. Reloading…");
    setTimeout(() => location.reload(), 250);
  });
}

/* -------------------------------------------------------------------------- */
/* Theme                                                                      */
/* -------------------------------------------------------------------------- */
// The initial theme class is applied by an inline script in <head>, before the
// first paint, to avoid a flash of the wrong colours. From here we only keep
// the toggle in sync and persist explicit choices.
const THEME_KEY = "leyna.theme";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  try {
    return localStorage.getItem(THEME_KEY);
  } catch (error) {
    return null;
  }
}

function isDark() {
  return document.documentElement.classList.contains("dark");
}

function applyTheme(theme, { persist = false } = {}) {
  document.documentElement.classList.toggle("dark", theme === "dark");
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (error) {
      /* storage unavailable — the choice just won't survive a reload */
    }
  }
  syncThemeButton();
}

function syncThemeButton() {
  const dark = isDark();
  const label = dark ? "Switch to light mode" : "Switch to dark mode";
  dom.themeBtn.setAttribute("aria-pressed", String(dark));
  dom.themeBtn.title = label;
  dom.themeBtn.setAttribute("aria-label", label);
}

function initTheme() {
  syncThemeButton();

  dom.themeBtn.addEventListener("click", () => {
    applyTheme(isDark() ? "light" : "dark", { persist: true });
  });

  // Follow the OS only while the user hasn't made an explicit choice.
  darkQuery.addEventListener("change", (event) => {
    if (!savedTheme()) applyTheme(event.matches ? "dark" : "light");
  });
}

/* -------------------------------------------------------------------------- */
/* Boot                                                                       */
/* -------------------------------------------------------------------------- */
function checkAuth() {
  try {
    if (localStorage.getItem(AUTH_KEY) === "true") {
      if (dom.loginOverlay) dom.loginOverlay.classList.add("hidden");
      return true;
    }
  } catch {}
  if (dom.loginOverlay) dom.loginOverlay.classList.remove("hidden");
  return false;
}

function initAuth() {
  if (dom.loginForm) {
    dom.loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const user = dom.loginUser?.value || "";
      const pass = dom.loginPass?.value || "";
      if (user === "me" && pass === "123") {
        try { localStorage.setItem(AUTH_KEY, "true"); } catch {}
        if (dom.loginOverlay) dom.loginOverlay.classList.add("hidden");
        if (dom.loginError) {
          dom.loginError.classList.add("hidden");
          dom.loginError.textContent = "";
        }
      } else {
        if (dom.loginError) {
          dom.loginError.textContent = "Invalid username or password";
          dom.loginError.classList.remove("hidden");
        }
      }
    });
  }
  checkAuth();
}

async function init() {
  initTheme();
  initAuth();

  // Prefer the server's copy of the conversation; fall back to the local one.
  const restored = await restoreConversation();
  if (!restored) loadHistory();
  state.messages.forEach(mountMessage);
  syncEmptyState();
  scrollToBottom(true);

  dom.adminToken.value = localStorage.getItem(ADMIN_KEY) ?? "";
  refreshBackendPanel();
  autoGrow();
  updateSendState();
  dom.input.focus();

  void refreshHealth();
  setInterval(() => void refreshHealth(), 15000);

  // Lets the smoke test (and anyone else) wait for a fully wired page instead
  // of guessing from the static HTML.
  window.__leynaReady = true;
}

void init();
