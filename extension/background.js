/**
 * Agent Browser Bridge — Background Service Worker (MV3)
 *
 * Connects to agent-browser daemon via WebSocket (ws://127.0.0.1:19825/ext).
 * Routes commands from daemon → chrome.debugger API → returns results.
 * Uses chrome.alarms for service worker keepalive (MV3: SW killed after ~30s idle).
 */

// ── Constants ──────────────────────────────────────────────
const WS_URL = 'ws://127.0.0.1:19825/ext';
const HEARTBEAT_INTERVAL = 15000; // 15s — must match daemon's ping interval
const ALARM_NAME = 'ab-keepalive';
const ALARM_INTERVAL_MIN = 0.33;  // ~20s (chrome.alarms minimum)
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_RECONNECT_ATTEMPTS = 10;

// ── State ──────────────────────────────────────────────────
let ws = null;
let debuggeeId = null;
let connected = false;
let reconnectAttempts = 0;
let reconnectTimer = null;
let commandIdCounter = 0;
const pendingCommands = new Map(); // id -> { resolve, reject, timer }
let lastActivity = Date.now();

// ── Debugger module (lazy-loaded) ──────────────────────────
let Debugger = null;

// ── Badge state ────────────────────────────────────────────
function updateBadge(state) {
  const colors = {
    disconnected: '#999999',
    connecting: '#FFA500',
    connected: '#4CAF50',
    error: '#F44336',
  };
  const texts = {
    disconnected: '--',
    connecting: '..',
    connected: 'OK',
    error: 'XX',
  };
  chrome.action.setBadgeText({ text: texts[state] || '--' });
  chrome.action.setBadgeBackgroundColor({ color: colors[state] || '#999' });
}

// ── WebSocket Connection ───────────────────────────────────

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  updateBadge('connecting');
  console.log('[AB] Connecting to', WS_URL);

  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.error('[AB] WebSocket create failed:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[AB] WebSocket connected');
    connected = true;
    reconnectAttempts = 0;
    updateBadge('connected');
    lastActivity = Date.now();
    ensureKeepalive();
  };

  ws.onmessage = async (event) => {
    lastActivity = Date.now();
    try {
      const msg = JSON.parse(event.data);
      await handleMessage(msg);
    } catch (e) {
      console.error('[AB] Message parse error:', e, event.data);
    }
  };

  ws.onclose = (event) => {
    console.log('[AB] WebSocket closed:', event.code, event.reason);
    connected = false;
    cleanupDebugger();
    updateBadge('disconnected');
    rejectAllPending('Connection closed');
    scheduleReconnect();
  };

  ws.onerror = (error) => {
    console.error('[AB] WebSocket error:', error);
    updateBadge('error');
  };
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  rejectAllPending('Disconnected');
  cleanupDebugger();
  if (ws) {
    ws.close(1000, 'Normal disconnect');
    ws = null;
  }
  connected = false;
  updateBadge('disconnected');
}

function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    console.log('[AB] Max reconnect attempts reached, giving up');
    updateBadge('error');
    return;
  }

  const delay = Math.min(
    RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts),
    RECONNECT_MAX_DELAY
  );
  reconnectAttempts++;
  console.log(`[AB] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);

  reconnectTimer = setTimeout(() => {
    connect();
  }, delay);
}

// ── Keepalive (chrome.alarms + activity-based) ─────────────

function ensureKeepalive() {
  chrome.alarms.get(ALARM_NAME, (alarm) => {
    if (!alarm) {
      chrome.alarms.create(ALARM_NAME, {
        delayInMinutes: ALARM_INTERVAL_MIN,
        periodInMinutes: ALARM_INTERVAL_MIN,
      });
      console.log('[AB] Keepalive alarm created');
    }
  });
}

// Alarm fires periodically to prevent SW termination
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== ALARM_NAME) return;

  // If no recent WS activity and WS is dead, try reconnecting
  const idleMs = Date.now() - lastActivity;
  if (idleMs > HEARTBEAT_INTERVAL * 3 && (!ws || ws.readyState !== WebSocket.OPEN)) {
    console.log(`[AB] Keepalive alarm: idle ${idleMs}ms, reconnecting`);
    connect();
  }

  // Send a heartbeat ping if connected
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify({ type: 'pong' }));
    } catch (e) {
      // WS might be closing
    }
  }
});

// Also start keepalarm on install/startup
chrome.runtime.onInstalled.addListener(() => {
  console.log('[AB] Extension installed');
  connect();
});

chrome.runtime.onStartup.addListener(() => {
  console.log('[AB] Browser started (SW restart)');
  connect();
});

// ── Popup Status Query ────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'getStatus') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs && tabs[0];
      sendResponse({
        type: 'statusResponse',
        connected: connected,
        state: connected
          ? 'connected'
          : reconnectAttempts > 0 && reconnectAttempts < MAX_RECONNECT_ATTEMPTS
            ? 'error'
            : 'disconnected',
        wsUrl: WS_URL,
        debuggeeId: debuggeeId ? { tabId: debuggeeId.tabId } : null,
        tabTitle: tab ? tab.title : null,
        tabUrl: tab ? tab.url : null,
        reconnectAttempts: reconnectAttempts,
        lastActivity: lastActivity,
        commandsProcessed: commandCount || 0,
      });
    });
    return true; // Keep channel open for async response
  }
});

// Track command count for stats display (separate from pendingCommands Map)
let commandCount = 0;

// ── Message Handling (from daemon) ──────────────────────────

async function handleMessage(msg) {
  // Count incoming commands for popup stats
  if (msg.id && msg.method) {
    commandCount++;
  }

  // Heartbeat from daemon
  // Heartbeat from daemon
  if (msg.type === 'ping') {
    send({ type: 'pong', ts: Date.now() });
    return;
  }

  // Command from daemon
  if (msg.id && msg.method) {
    await handleCommand(msg);
    return;
  }

  console.warn('[AB] Unknown message type:', msg.type || 'unknown');
}

async function handleCommand(msg) {
  const { id, method, params } = msg;

  // Lazy-load debugger module on first command
  if (!Debugger) {
    Debugger = await importScripts ? null : await import('./debugger.js').catch(() => null);
    // In MV3 service worker, use importScripts or inline
    if (!Debugger) {
      Debugger = self.DebuggerModule || {};
    }
  }

  try {
    // Route command to appropriate handler
    let result;
    switch (method) {
      case 'snapshot':
        result = await handleSnapshot(params);
        break;
      case 'navigate':
      case 'goto':
        result = await DebuggerNavigate(params);
        break;
      case 'evaluate':
        result = await DebuggerEvaluate(params);
        break;
      case 'click':
        result = await DebuggerClick(params);
        break;
      case 'fill':
        result = await DebuggerFill(params);
        break;
      case 'scroll':
        result = await DebuggerScroll(params);
        break;
      case 'hover':
        result = await DebuggerHover(params);
        break;
      case 'select_option':
        result = await DebuggerSelectOption(params);
        break;
      case 'press_key':
      case 'keyboard':
        result = await DebuggerPressKey(params);
        break;
      case 'get_url':
        result = await DebuggerGetUrl();
        break;
      case 'get_title':
        result = await DebuggerGetTitle();
        break;
      default:
        throw new Error(`Unknown method: ${method}`);
    }

    sendResponse(id, { result });
  } catch (err) {
    sendResponse(id, { error: err.message || String(err) });
  }
}

function sendResponse(id, payload) {
  send({ id, ...payload });
}

// ── Send helper ────────────────────────────────────────────

function send(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
    lastActivity = Date.now();
  } else {
    console.warn('[AB] Cannot send: WebSocket not open');
  }
}

// ── Pending command cleanup ─────────────────────────────────

function rejectAllPending(reason) {
  for (const [id, entry] of pendingCommands) {
    clearTimeout(entry.timer);
    entry.reject(new Error(reason));
  }
  pendingCommands.clear();
}

// ── Debugger Lifecycle ─────────────────────────────────────

let _attaching = null; // Promise mutex: prevents concurrent attach races

function cleanupDebugger() {
  if (debuggeeId) {
    try {
      chrome.debugger.detach(debuggeeId, () => {
        if (chrome.runtime.lastError) {
          console.warn('[AB] Detach error:', chrome.runtime.lastError.message);
        }
      });
    } catch (e) {
      console.warn('[AB] Detach exception:', e);
    }
    debuggeeId = null;
  }
}

// Ensure debugger is attached before operations (mutex-serialized)
async function ensureDebuggerAttached() {
  if (debuggeeId) return debuggeeId;

  // If already attaching, wait for that operation to complete
  if (_attaching) return _attaching;

  _attaching = new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        _attaching = null;
        return reject(new Error('No active tab found'));
      }

      const tabId = tabs[0].id;
      const target = { tabId };

      chrome.debugger.attach(target, '1.3', () => {
        if (chrome.runtime.lastError) {
          _attaching = null;
          return reject(new Error(chrome.runtime.lastError.message));
        }
        debuggeeId = target;
        console.log('[AB] Debugger attached to tab', tabId);
        resolve(target);
      });
    });
  });

  try {
    return await _attaching;
  } finally {
    _attaching = null;
  }
}

// ── JS String Escaping (prevents injection via selector/value) ───

function jsEscape(str) {
  // Escape for inclusion inside a JS template literal (backtick string)
  // Handles: backslash, backtick, ${}, ', ", newlines, unicode
  return String(str)
    .replace(/\\/g, '\\\\')
    .replace(/`/g, '\\`')
    .replace(/\$/g, '\\$')
    .replace(/'/g, "\\'")
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\u0000/g, '\\0');
}

function jsEscapeSelector(sel) {
  // Additional CSS-selector-specific escaping
  // Only allow @eN pattern or simple alphanumeric selectors
  const cleaned = String(sel).replace(/[^a-zA-Z0-9_@.\-\[\]#=:]/g, '');
  return jsEscape(cleaned);
}

// ── Exports for debugger.js ────────────────────────────────
// debugger.js functions will be inlined below since MV3 SW can't use ES imports easily
// We'll implement them as self-contained functions

// ══════════════════════════════════════════════════════════
// DEBUGGER OPERATIONS (inline — MV3 compatible)
// ══════════════════════════════════════════════════════════

async function DebuggerNavigate(params) {
  const target = await ensureDebuggerAttached();
  const url = params.url || '';

  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(target, 'Page.navigate', { url }, (result) => {
      if (chrome.runtime.lastError) {
        return reject(new Error(chrome.runtime.lastError.message));
      }
      resolve(result);
    });
  });
}

async function DebuggerEvaluate(params) {
  const target = await ensureDebuggerAttached();
  const expression = params.expression || params.expr || '';

  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(
      target,
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      (result) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        if (result.result && result.result.exceptionDetails) {
          return reject(new Error(result.result.exceptionDetails.text || 'Evaluation error'));
        }
        resolve(result.result ? result.result.value : null);
      }
    );
  });
}

async function DebuggerClick(params) {
  const target = await ensureDebuggerAttached();
  const selector = params.selector || params.ref ||';
  const safeSel = jsEscapeSelector(selector);
  const refPart = jsEscape(selector.replace('@', ''));
  const js = `
    (function() {
      var el = document.querySelector('${safeSel}') ||
               (function(){
                 var refs = document.querySelectorAll('[data-ab-ref]');
                 for (var i=0;i<refs.length;i++){if(refs[i].dataset.abRef==='${refPart}')return refs[i];}
                 return null;
               })();
      if (!el) throw new Error('Element not found: ${safeSel}');
      el.click();
      return true;
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerFill(params) {
  const target = await ensureDebuggerAttached();
  const selector = params.selector || params.ref || '';
  const value = params.value || params.text || '';
  const safeSel = jsEscapeSelector(selector);
  const refPart = jsEscape(selector.replace('@', ''));
  // Use JSON serialize + parse pattern to prevent value injection
  const safeValJson = JSON.stringify(value);
  const js = `
    (function() {
      var el = document.querySelector('${safeSel}') ||
               (function(){
                 var refs = document.querySelectorAll('[data-ab-ref]');
                 for (var i=0;i<refs.length;i++){if(refs[i].dataset.abRef==='${refPart}')return refs[i];}
                 return null;
               })();
      if (!el) throw new Error('Element not found: ${safeSel}');
      var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      nativeInputValueSetter.call(el, JSON.parse(${safeValJson}));
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerScroll(params) {
  const target = await ensureDebuggerAttached();
  const direction = params.direction || params.dir || 'down';
  const amount = params.amount || params.px || 500;
  const deltaY = direction === 'up' ? -amount : amount;

  const js = `
    (function() {
      window.scrollBy({ top: ${deltaY}, left: 0, behavior: 'instant' });
      return window.scrollY;
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerHover(params) {
  const target = await ensureDebuggerAttached();
  const selector = params.selector || params.ref || '';
  const safeSel = jsEscapeSelector(selector);
  const refPart = jsEscape(selector.replace('@', ''));

  const js = `
    (function() {
      var el = document.querySelector('${safeSel}') ||
               (function(){
                 var refs = document.querySelectorAll('[data-ab-ref]');
                 for (var i=0;i<refs.length;i++){if(refs[i].dataset.abRef==='${refPart}')return refs[i];}
                 return null;
               })();
      if (!el) throw new Error('Element not found: ${safeSel}');
      var rect = el.getBoundingClientRect();
      var evt = new MouseEvent('mouseover', {
        view: window, bubbles: true, cancelable: true,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2
      });
      el.dispatchEvent(evt);
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerSelectOption(params) {
  const target = await ensureDebuggerAttached();
  const selector = params.selector || params.ref || '';
  const value = params.value || '';
  const safeSel = jsEscapeSelector(selector);
  const refPart = jsEscape(selector.replace('@', ''));
  const safeValJson = JSON.stringify(value);

  const js = `
    (function() {
      var el = document.querySelector('${safeSel}') ||
               (function(){
                 var refs = document.querySelectorAll('[data-ab-ref]');
                 for (var i=0;i<refs.length;i++){if(refs[i].dataset.abRef==='${refPart}')return refs[i];}
                 return null;
               })();
      if (!el) throw new Error('Element not found: ${safeSel}');
      el.value = JSON.parse(${safeValJson});
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerPressKey(params) {
  const target = await ensureDebuggerAttached();
  const key = params.key || params.code || 'Enter';

  // Map key names to key codes
  const keyMap = {
    'Enter': '\r', 'Tab': '\t', 'Escape': '\u001b',
    'ArrowUp': '', 'ArrowDown': '', 'ArrowLeft': '', 'ArrowRight': '',
    'Backspace': '\b', 'Delete': '\u007f',
  };
  const keyChar = keyMap[key] || key;
  const safeKey = jsEscape(key);
  const safeKeyChar = jsEscape(keyChar);

  const js = `
    (function() {
      var evt = new KeyboardEvent('keydown', {
        key: '${safeKey}', code: '${safeKey}', bubbles: true, cancelable: true
      });
      document.activeElement.dispatchEvent(evt);
      if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') {
        document.activeElement.value += '${safeKeyChar}';
        document.activeElement.dispatchEvent(new Event('input', { bubbles: true }));
      }
      return true;
    })()
  `;

  return DebuggerEvaluate({ expression: js });
}

async function DebuggerGetUrl() {
  const target = await ensureDebuggerAttached();
  return DebuggerEvaluate({ expression: 'window.location.href' });
}

async function DebuggerGetTitle() {
  const target = await ensureDebuggerAttached();
  return DebuggerEvaluate({ expression: 'document.title' });
}

// ══════════════════════════════════════════════════════════
// SNAPSHOT (DOM extraction with @eN refs)
// ══════════════════════════════════════════════════════════

async function handleSnapshot(params) {
  const target = await ensureDebuggerAttached();
  const interactiveOnly = params.interactive_only || params.interactiveOnly || false;

  // The snapshot JS is large, so we evaluate it as an IIFE
  const snapshotJS = getSnapshotScript(interactiveOnly);

  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(
      target,
      'Runtime.evaluate',
      { expression: snapshotJS, returnByValue: true },
      (result) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        if (result.result && result.result.exceptionDetails) {
          return reject(new Error(result.result.exceptionDetails.text || 'Snapshot error'));
        }
        resolve(result.result ? result.result.value : null);
      }
    );
  });
}

function getSnapshotScript(interactiveOnly) {
  // Returns the snapshot extraction script as a string
  // This is the same logic as snapshot.js but inlined for MV3 compatibility
  return `
(function() {
  var interactiveOnly = ${interactiveOnly};

  // Interactive element selectors (same as LocalCDPBackend)
  var interactiveSelectors = [
    'a[href]', 'button', '[role="button"]', 'input', 'textarea', 'select',
    '[role="textbox"]', '[role="combobox"]', '[role="listbox"]',
    '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]',
    '[onclick]', '[onsubmit]', '[role="link"]', '[role="menuitem"]',
    '[role="option"]', '[role="checkbox"]', '[role="radio"]', '[role="switch"]'
  ];

  function isInteractive(el) {
    if (interactiveOnly) {
      for (var i = 0; i < interactiveSelectors.length; i++) {
        if (el.matches(interactiveSelectors[i])) return true;
      }
      return false;
    }
    return true;
  }

  function isVisible(el) {
    var style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    return true;
  }

  function getText(el) {
    // Get visible text content, trimmed
    var text = '';
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      text = el.value || el.placeholder || '';
    } else if (el.tagName === 'SELECT') {
      var sel = el.selectedOptions[0];
      text = sel ? sel.text : '';
    } else {
      // Use textContent but limit length
      text = (el.textContent || '').trim();
      // For elements with too much text, truncate
      if (text.length > 200) text = text.substring(0, 200) + '...';
    }
    return text;
  }

  function getRole(el) {
    var role = el.getAttribute('role');
    if (role) return role;
    var tag = el.tagName.toLowerCase();
    var roleMap = {
      'a': 'link', 'button': 'button', 'input': getInputRole,
      'textarea': 'input', 'select': 'select', 'form': 'form',
      'img': 'image', 'table': 'table', 'nav': 'navigation',
      'main': 'main', 'header': 'banner', 'footer': 'contentinfo'
    };
    var mapped = roleMap[tag];
    return typeof mapped === 'function' ? mapped(el) : (mapped || 'div');
  }

  function getInputRole(el) {
    var type = (el.type || 'text').toLowerCase();
    var typeMap = {
      'text': 'input', 'search': 'input', 'email': 'input', 'url': 'input',
      'tel': 'input', 'password': 'input', 'number': 'input', 'hidden': null,
      'submit': 'button', 'reset': 'button', 'button': 'button',
      'checkbox': 'checkbox', 'radio': 'radio', 'file': 'input', 'date': 'input'
    };
    return typeMap[type] || 'input';
  }

  // Walk DOM tree and collect elements
  var elements = [];
  var refCounter = 0;

  function walk(node, depth) {
    if (depth > 15) return; // Max depth limit
    if (node.nodeType !== 1) return; // Only element nodes

    var el = node;

    // Skip hidden/script/style/meta elements
    var tag = el.tagName.toLowerCase();
    if (['script', 'style', 'noscript', 'meta', 'link', 'svg', 'path', 'defs'].indexOf(tag) !== -1) return;

    if (isVisible(el) && isInteractive(el)) {
      var text = getText(el);
      // Skip elements with empty text unless they are inputs/selects
      if (text || ['input', 'textarea', 'select'].indexOf(tag) !== -1) {
        var ref = '@e' + refCounter++;
        elements.push({
          ref: ref,
          text: text,
          role: getRole(el),
          tag: tag
        });
      }
    }

    // Recurse into children
    var children = el.children;
    for (var i = 0; i < children.length; i++) {
      walk(children[i], depth + 1);
    }
  }

  walk(document.body, 0);

  return {
    url: window.location.href,
    title: document.title,
    elements: elements
  };
})()
`;
}

// ── Start connection on script load ────────────────────────
connect();
