/**
 * Agent Browser Bridge -- Popup Controller
 *
 * Queries background service worker for connection status, tab info,
 * and session stats. Renders a live status panel with auto-refresh.
 */

(function () {
  'use strict';

  const REFRESH_INTERVAL = 2000; // 2 seconds
  let timer = null;

  // ── DOM references ──────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);

  function setText(id, text) {
    const el = $(id);
    if (el) el.textContent = text;
  }

  function showEl(id) {
    const el = $(id);
    if (el) el.style.display = '';
  }

  function hideEl(id) {
    const el = $(id);
    if (el) el.style.display = 'none';
  }

  // ── Status rendering ───────────────────────────────────
  const STATUS_CONFIG = {
    connected: { dot: 'connected', label: 'Connected', color: '#4CAF50' },
    connecting: { dot: 'connecting', label: 'Connecting...', color: '#FFA500' },
    disconnected: { dot: 'disconnected', label: 'Disconnected', color: '#999' },
    error: { dot: 'error', label: 'Error', color: '#F44336' },
  };

  function renderStatus(data) {
    const cfg = STATUS_CONFIG[data.state] || STATUS_CONFIG.disconnected;

    // Status dot
    const dot = $('#status-dot');
    if (dot) {
      dot.className = 'status-dot ' + cfg.dot;
    }

    // Status text
    setText('#status-text', cfg.label);

    // Detail line
    let detail = '';
    if (data.wsUrl) detail += data.wsUrl;
    if (data.reconnectAttempts > 0) detail += ` (attempt #${data.reconnectAttempts})`;
    if (data.lastActivity) {
      const ago = Math.round((Date.now() - data.lastActivity) / 1000);
      detail += ` | last activity ${ago}s ago`;
    }
    setText('#status-detail', detail);

    // Tab info
    if (data.tabTitle || data.tabUrl) {
      showEl('#tab-info');
      hideEl('#no-tab');
      setText('#tab-title', data.tabTitle || '--');
      setText('#tab-url', data.tabUrl || '--');
      setText('#tab-debugger', data.debuggeeId ? 'Yes' : 'No');
    } else {
      hideEl('#tab-info');
      showEl('#no-tab');
    }

    // Stats
    setText('#stat-commands', data.commandsProcessed || 0);
    setText('#stat-reconnects', data.reconnectAttempts || 0);
  }

  // ── Main query loop ──────────────────────────────────
  async function queryStatus() {
    try {
      const response = await chrome.runtime.sendMessage({ type: 'getStatus' });
      if (response && response.type === 'statusResponse') {
        renderStatus(response);
      } else {
        // Background might be asleep or not responding
        renderStatus({ state: 'error', reconnectAttempts: 0 });
      }
    } catch (err) {
      // Extension context invalidated (e.g., SW restarted)
      renderStatus({ state: 'error', reconnectAttempts: 0 });
    }
  }

  // ── Auto-refresh ────────────────────────────────────
  function startRefresh() {
    stopRefresh();
    queryStatus(); // Immediate first query
    timer = setInterval(queryStatus, REFRESH_INTERVAL);
  }

  function stopRefresh() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  // ── Troubleshoot toggle ─────────────────────────────
  $('#troubleshoot-toggle').addEventListener('click', () => {
    const panel = $('#troubleshoot-panel');
    if (panel) {
      panel.classList.toggle('open');
      const toggle = $('#troubleshoot-toggle');
      if (toggle) {
        toggle.textContent = panel.classList.contains('open')
          ? 'Troubleshoot &#9660;'
          : 'Troubleshoot &#9662;';
      }
    }
  });

  // ── Copy-to-clipboard for troubleshoot commands ─────
  document.addEventListener('click', (e) => {
    if (e.target.classList.contains('troubleshoot-a')) {
      const cmd = e.target.getAttribute('data-cmd') || '';
      navigator.clipboard.writeText(cmd).then(() => {
        const orig = e.target.textContent;
        e.target.textContent = 'Copied!';
        setTimeout(() => { e.target.textContent = orig; }, 1200);
      });
    }
  });

  // ── Init ─────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    startRefresh();

    // Stop refresh when popup is hidden (saves resources)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopRefresh();
      } else {
        startRefresh();
      }
    });
  });
})();
