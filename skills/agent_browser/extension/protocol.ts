/**
 * Protocol types for Agent Browser Extension ↔ Daemon communication.
 *
 * Message format: JSON over WebSocket
 * - Daemon → Extension: Command { id, method, params }
 * - Extension → Daemon: Result { id, data?, error? }
 */

export interface Command {
  /** Unique request ID for request/response matching */
  id: string;
  /** Method name */
  method:
    | "navigate"
    | "evaluate"
    | "screenshot"
    | "getTabs"
    | "switchTab"
    | "setFileInput"
    | "getCookies"
    | "getUrl"
    | "getTitle"
    | "ping";
  /** Method-specific parameters */
  params?: Record<string, unknown>;
}

export interface Result {
  /** Matching request ID */
  id: string;
  /** Response data (on success) */
  data?: unknown;
  /** Error message (on failure) */
  error?: string;
}

/** Tab info returned by getTabs */
export interface TabInfo {
  id: number;
  url: string;
  title: string;
  active: boolean;
}

/** Screenshot result */
export interface ScreenshotResult {
  /** Base64-encoded PNG */
  data: string;
  /** Image dimensions */
  width: number;
  height: number;
}
