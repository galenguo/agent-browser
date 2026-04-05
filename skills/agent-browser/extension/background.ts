/**
 * Agent Browser Extension — Service Worker
 *
 * Lifecycle:
 * 1. User installs extension → icon appears in toolbar
 * 2. Daemon starts → opens WS port for extension to connect
 * 3. Extension connects via WebSocket → ready to receive commands
 * 4. Daemon sends Command → Extension executes via chrome.debugger → returns Result
 *
 * Security model (from OpenCLI, proven):
 * - Origin check: only connect to localhost/127.0.0.1
 * - Heartbeat: 15s ping/pong, terminate after 2 missed pongs
 * - URL validation: CDP execution only on http(s) pages
 * - Automation window: dedicated Chrome window per session, auto-close on idle
 */

import { attachDebugger, detachDebugger, cdpEvaluate, takeScreenshot, getAttachedTabId, isAttached } from "./cdp";
import type { Command, Result, TabInfo } from "./protocol";

// ── Configuration ──

const DAEMON_WS_URL = "ws://127.0.0.1:19825/ext"; // Match daemon port
const HEARTBEAT_INTERVAL = 15_000; // 15 seconds
const MAX_MISSED_PONGS = 2;
const IDLE_CLOSE_MS = 30_000; // Close automation window after 30s idle

// ── State ──

let ws: WebSocket | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let missedPongs = 0;
let commandIdCounter = 0;
let pendingCommands = new Map<number, { resolve: (value: Result) => void; reject: (err: Error) => void }>();
let automationWindowId: number | null = null;
let idleCloseTimer: ReturnType<typeof setTimeout> | null = null;

// ── WebSocket Connection ──

function connect(): void {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  console.log("[Agent Browser] Connecting to daemon:", DAEMON_WS_URL);

  ws = new WebSocket(DAEMON_WS_URL);

  ws.onopen = () => {
    console.log("[Agent Browser] Connected to daemon");
    missedPongs = 0;
    startHeartbeat();
    sendReady();
  };

  ws.onmessage = async (event) => {
    try {
      const command: Command = JSON.parse(event.data as string);
      const result = await handleCommand(command);
      sendResult(result);
    } catch (err) {
      console.error("[Agent Browser] Message handling error:", err);
      sendResult({
        id: "error",
        error: `Internal error: ${err}`,
      });
    }
  };

  ws.onclose = () => {
    console.log("[Agent Browser] Disconnected from daemon");
    stopHeartbeat();
    ws = null;
    // Auto-reconnect after 3 seconds
    setTimeout(connect, 3000);
  };

  ws.onerror = (err) => {
    console.error("[Agent Browser] WebSocket error:", err);
  };
}

function disconnect(): void {
  stopHeartbeat();
  if (ws) {
    ws.close();
    ws = null;
  }
  detachDebugger();
}

// ── Heartbeat ──

function startHeartbeat(): void {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    try {
      ws.send(JSON.stringify({ type: "ping" }));
      missedPongs++;
      if (missedPongs >= MAX_MISSED_PONGS) {
        console.warn("[Agent Browser] Too many missed heartbeats, reconnecting");
        disconnect();
        setTimeout(connect, 1000);
      }
    } catch {
      // Socket likely closed
    }
  }, HEARTBEAT_INTERVAL);
}

function stopHeartbeat(): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function handlePong(): void {
  missedPongs = 0;
}

// ── Message I/O ──

function sendResult(result: Result): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(result));
  }
}

function sendReady(): void {
  sendResult({
    id: "ready",
    data: {
      version: "0.1.0",
      extensionId: chrome.runtime.id,
    },
  });
}

// ── Command Handler ──

async function handleCommand(command: Command): Promise<Result> {
  const { id, method, params = {} } = command;
  resetIdleTimer();

  try {
    switch (method) {
      case "ping":
        handlePong();
        return { id, data: { pong: true } };

      case "navigate": {
        const url = params.url as string;
        if (!url || typeof url !== "string") {
          return { id, error: "Missing or invalid 'url' parameter" };
        }

        // Ensure we have an automation window/tab
        const tabId = await ensureAutomationTab();
        await attachDebugger(tabId);

        // Navigate via CDP Page.navigate
        await chrome.debugger.sendCommand(
          { tabId },
          "Page.navigate",
          { url } as unknown as Record<string, unknown>
        );

        // Wait for navigation to complete
        await waitForLoad(tabId, params.timeout as number ?? 15000);

        return { id, data: { success: true, tabId } };
      }

      case "evaluate": {
        const expression = params.expression as string;
        if (!expression || typeof expression !== "string") {
          return { id, error: "Missing or invalid 'expression' parameter" };
        }

        const tabId = getAttachedTabId();
        if (!tabId) {
          return { id, error: "No debugger attached. Navigate first." };
        }

        const result = await cdpEvaluate(expression, params.timeout as number ?? 30000);
        return { id, data: result };
      }

      case "screenshot": {
        const tabId = getAttachedTabId();
        if (!tabId) {
          return { id, error: "No debugger attached" };
        }

        const data = await takeScreenshot(params.format as string ?? "png");
        return { id, data: { data, width: 0, height: 0 } }; // dimensions need separate call
      }

      case "getTabs": {
        const tabs = await chrome.tabs.query({});
        const tabInfos: TabInfo[] = tabs.map((t) => ({
          id: t.id!,
          url: t.url || "",
          title: t.title || "",
          active: t.active,
        }));
        return { id, data: tabInfos };
      }

      case "switchTab": {
        const targetTabId = params.tabId as number;
        if (!targetTabId) {
          return { id, error: "Missing 'tabId' parameter" };
        }

        await attachDebugger(targetTabId);
        return { id, data: { switched: true, tabId: targetTabId } };
      }

      case "setFileInput": {
        const selector = params.selector as string;
        const files = params.files as string[];
        if (!selector || !files?.length) {
          return { id, error: "Missing 'selector' or 'files' parameter" };
        }

        await setFileInputFiles(selector, files);
        return { id, data: { success: true } };
      }

      case "getCookies": {
        const url = params.url as string;
        const cookies = await chrome.cookies.getAll(url ? { url } : {});
        return { id, data: cookies };
      }

      case "getUrl":
      case "getTitle": {
        const tabId = getAttachedTabId() ?? (await getCurrentTabId());
        if (!tabId) {
          return { id, error: "No tab available" };
        }
        const tab = await chrome.tabs.get(tabId);
        return { id, data: method === "getUrl" ? tab.url : tab.title };
      }

      default:
        return { id, error: `Unknown method: ${method}` };
    }
  } catch (err) {
    return { id, error: String(err) };
  }
}

// ── Tab Management ──

async function ensureAutomationTab(): Promise<number> {
  // Reuse existing automation window's active tab if available
  if (automationWindowId) {
    try {
      const tabs = await chrome.tabs.query({ windowId: automationWindowId });
      if (tabs.length > 0) {
        await chrome.tabs.update(tabs[0].id!, { active: true });
        return tabs[0].id!;
      }
    } catch {
      // Window may have been closed
      automationWindowId = null;
    }
  }

  // Create new automation window
  const win = await chrome.windows.create({
    url: "about:blank",
    focused: false,
    state: "normal",
  });
  automationWindowId = win.id!;
  return win.tabs![0].id!;
}

async function getCurrentTabId(): Promise<number | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id;
}

async function waitForLoad(tabId: number, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.debugger.onEvent.removeListener(listener);
      resolve(); // Don't fail on timeout, just proceed
    }, timeoutMs);

    function listener(
      source: chrome.debugger.Debuggee,
      method: string,
      params?: Record<string, unknown>
    ) {
      if (source.tabId === tabId && method === "Page.loadEventFired") {
        clearTimeout(timer);
        chrome.debugger.onEvent.removeListener(listener);
        // Small delay for DOM to settle
        setTimeout(resolve, 500);
      }
    }

    chrome.debugger.onEvent.addListener(listener);
  });
}

// ── Idle Management ──

function resetIdleTimer(): void {
  if (idleCloseTimer) {
    clearTimeout(idleCloseTimer);
  }
  idleCloseTimer = setTimeout(async () => {
    if (automationWindowId) {
      try {
        await chrome.windows.remove(automationWindowId);
        console.log("[Agent Browser] Closed idle automation window");
      } catch {
        // Window already closed
      }
      automationWindowId = null;
    }
    detachDebugger();
  }, IDLE_CLOSE_MS);
}

// ── Lifecycle ──

// Start connecting when service worker wakes up
connect();

// Handle extension install/update
chrome.runtime.onInstalled.addListener((details) => {
  console.log(`[Agent Browser] Installed: ${details.reason}`);
  if (details.reason === "install") {
    // Could open a welcome page here
  }
});

// Keep service worker alive periodically
setInterval(() => {
  // No-op, just keep SW alive while connected
}, 20_000);
