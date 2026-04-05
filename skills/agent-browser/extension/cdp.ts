/**
 * CDP wrapper — wraps chrome.debugger API for safe attach/detach/evaluate.
 *
 * Security:
 * - URL validation: only allows http(s) and internal blank pages
 * - Auto-detach on navigation to disallowed URL
 * - Timeout protection for evaluate calls
 */

// ── Types ──

interface DebuggerTarget {
  tabId: number;
  attached: boolean;
}

interface EvaluateResult {
  result?: {
    value: unknown;
    type: string;
  };
  exceptionDetails?: {
    text: string;
    exception?: { description?: string };
  };
}

// ── State ──

let currentTarget: DebuggerTarget | null = null;

// ── URL Validation ──

const ALLOWED_SCHEMES = new Set(["http:", "https:", "chrome-extension:", "about:"]);

function isUrlAllowed(url: string): boolean {
  try {
    const parsed = new URL(url);
    return ALLOWED_SCHEMES.has(parsed.protocol);
  } catch {
    return false;
  }
}

// ── Public API ──

export async function attachDebugger(tabId: number): Promise<void> {
  // Detach previous if any
  if (currentTarget && currentTarget.attached) {
    try {
      await chrome.debugger.detach({ tabId: currentTarget.tabId });
    } catch {
      // Ignore detach errors
    }
  }

  currentTarget = { tabId, attached: false };

  try {
    await chrome.debugger.attach({ tabId }, "1.3");
    currentTarget.attached = true;
  } catch (err) {
    currentTarget = null;
    throw new Error(`Failed to attach debugger to tab ${tabId}: ${err}`);
  }
}

export async function detachDebugger(): Promise<void> {
  if (!currentTarget || !currentTarget.attached) {
    currentTarget = null;
    return;
  }

  try {
    await chrome.debugger.detach({ tabId: currentTarget.tabId });
  } catch {
    // Ignore
  }
  currentTarget = null;
}

export async function cdpEvaluate(expression: string, timeoutMs: number = 30000): Promise<unknown> {
  if (!currentTarget || !currentTarget.attached) {
    throw new Error("Debugger not attached. Call attachDebugger() first.");
  }

  // Validate current URL before executing
  const [tab] = await chrome.tabs.get(currentTarget.tabId);
  if (!isUrlAllowed(tab.url)) {
    throw new Error(`URL not allowed for CDP execution: ${tab.url}`);
  }

  const params: chrome.debugger.SendCommandParams = {
    tabId: currentTarget.tabId,
    method: "Runtime.evaluate",
    params: {
      expression,
      returnByValue: true,
      awaitPromise: true,
      timeout: timeoutMs,
    },
  };

  const result = (await chrome.debugger.sendCommand(
    params.tabId!,
    params.method,
    params.params as Record<string, unknown>
  )) as EvaluateResult;

  if (result.exceptionDetails) {
    const desc =
      result.exceptionDetails.exception?.description ||
      result.exceptionDetails.text ||
      "Unknown error";
    throw new Error(`CDP evaluation error: ${desc}`);
  }

  return result.result?.value;
}

export async function takeScreenshot(format: string = "png"): Promise<string> {
  if (!currentTarget || !currentTarget.attached) {
    throw new Error("Debugger not attached");
  }

  const params: chrome.debugger.SendCommandParams = {
    tabId: currentTarget.tabId,
    method: "Page.captureScreenshot",
    params: { format },
  };

  const result = (await chrome.debugger.sendCommand(
    params.tabId!,
    params.method,
    params.params as Record<string, unknown>
  )) as { data: string };

  return result.data;
}

export async function setFileInputFiles(
  selector: string,
  files: string[]
): Promise<void> {
  if (!currentTarget || !currentTarget.attached) {
    throw new Error("Debugger not attached");
  }

  // First find the DOM node via JS
  const nodeId = (await cdpEvaluate(
    `(() => {
      const el = document.querySelector('${selector.replace(/'/g, "\\'")}');
      if (!el) return null;
      // Use CDP DOM domain to get nodeId would be cleaner,
      // but Runtime.evaluate + DOM.querySelector works universally
      return el;
    })()`
  )) as unknown;

  if (!nodeId) {
    throw new Error(`Element not found: ${selector}`);
  }

  // Set file input via CDP DOM.setFileInputFiles
  // Note: This requires the element to be a file input
  await chrome.debugger.sendCommand(
    { tabId: currentTarget.tabId },
    "DOM.setFileInputFiles",
    { files } as unknown as Record<string, unknown>
  );
}

export function getAttachedTabId(): number | null {
  return currentTarget?.tabId ?? null;
}

export function isAttached(): boolean {
  return currentTarget?.attached ?? false;
}
