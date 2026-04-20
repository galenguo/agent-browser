/**
 * Stealth Browser Bridge — Snapshot Module
 *
 * Extracts DOM elements with @eN references.
 * Output format matches LocalCDPBackend exactly for seamless ReAct loop compatibility.
 *
 * Usage: Called via chrome.debugger Runtime.evaluate from background.js
 * Can also be tested standalone in browser console.
 */

var StealthBrowserSnapshot = (function() {
  'use strict';

  // ── Interactive element selectors ──────────────────────
  var INTERACTIVE_SELECTORS = [
    'a[href]',
    'button',
    '[role="button"]',
    'input',
    'textarea',
    'select',
    '[role="textbox"]',
    '[role="combobox"]',
    '[role="listbox"]',
    '[tabindex]:not([tabindex="-1"])',
    '[contenteditable="true"]',
    '[onclick]',
    '[onsubmit]',
    '[role="link"]',
    '[role="menuitem"]',
    "[role='option']",
    '[role="checkbox"]',
    '[role="radio"]',
    '[role="switch"]',
  ];

  // Tags to always skip during tree walk
  var SKIP_TAGS = [
    'script', 'style', 'noscript', 'meta', 'link',
    'svg', 'path', 'defs', 'symbol', 'use',
  ];

  // ── Role mapping ───────────────────────────────────────
  function getRole(el) {
    var explicitRole = el.getAttribute('role');
    if (explicitRole) return explicitRole;

    var tag = el.tagName.toLowerCase();
    var roleMap = {
      a: 'link',
      button: 'button',
      img: 'image',
      table: 'table',
      nav: 'navigation',
      main: 'main',
      header: 'banner',
      footer: 'contentinfo',
      aside: 'complementary',
      form: 'form',
      h1: 'heading',
      h2: 'heading',
      h3: 'heading',
      h4: 'heading',
      h5: 'heading',
      h6: 'heading',
    };

    if (tag === 'input' || tag === 'textarea') return getInputRole(el);
    if (tag === 'select') return 'select';

    return roleMap[tag] || 'div';
  }

  function getInputRole(el) {
    var type = (el.type || 'text').toLowerCase();
    var typeMap = {
      text: 'input',
      search: 'input',
      email: 'input',
      url: 'input',
      tel: 'input',
      password: 'input',
      number: 'input',
      date: 'input',
      hidden: null,
      submit: 'button',
      reset: 'button',
      button: 'button',
      checkbox: 'checkbox',
      radio: 'radio',
      file: 'input',
      range: 'slider',
      color: 'input',
    };
    return typeMap[type] || 'input';
  }

  // ── Visibility check ───────────────────────────────────
  function isVisible(el) {
    var style = window.getComputedStyle(el);
    if (style.display === 'none') return false;
    if (style.visibility === 'hidden') return false;
    if (style.opacity === '0') return false;
    var rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    return true;
  }

  // ── Text extraction ─────────────────────────────────────
  function getText(el) {
    var tag = el.tagName.toLowerCase();

    if (tag === 'input' || tag === 'textarea') {
      return el.value || el.placeholder || '';
    }
    if (tag === 'select') {
      var sel = el.selectedOptions[0];
      return sel ? sel.text : '';
    }

    var text = (el.textContent || '').trim();
    if (text.length > 200) {
      text = text.substring(0, 200) + '...';
    }
    return text;
  }

  // ── Interactivity check ────────────────────────────────
  function isInteractive(el) {
    for (var i = 0; i < INTERACTIVE_SELECTORS.length; i++) {
      try {
        if (el.matches(INTERACTIVE_SELECTORS[i])) return true;
      } catch (e) {
        // Some selectors may not be supported in all contexts
      }
    }
    return false;
  }

  // ── DOM walker ──────────────────────────────────────────
  function walk(node, depth, options) {
    if (depth > options.maxDepth) return;
    if (node.nodeType !== 1) return; // Element nodes only

    var el = node;
    var tag = el.tagName.toLowerCase();

    // Skip non-visible/structural tags
    if (SKIP_TAGS.indexOf(tag) !== -1) return;
    if (!isVisible(el)) return;

    var shouldCollect = options.interactiveOnly ? isInteractive(el) : true;

    if (shouldCollect) {
      var text = getText(el);
      var hasContent = text ||
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select';

      if (hasContent) {
        options.elements.push({
          ref: '@e' + options.counter++,
          text: text,
          role: getRole(el),
          tag: tag,
        });
      }
    }

    // Recurse into children
    var children = el.children;
    for (var i = 0; i < children.length; i++) {
      walk(children[i], depth + 1, options);
    }
  }

  // ── Public API ──────────────────────────────────────────

  /**
   * Take a snapshot of the current page.
   *
   * @param {Object} opts - Options
   * @param {boolean} [opts.interactiveOnly=false] - Only collect interactive elements
   * @param {number} [opts.maxDepth=15] - Maximum DOM depth to traverse
   * @returns {Object} Snapshot with url, title, elements[]
   */
  function snapshot(opts) {
    opts = opts || {};
    var options = {
      interactiveOnly: !!opts.interactiveOnly,
      maxDepth: opts.maxDepth || 15,
      elements: [],
      counter: 0,
    };

    if (document.body) {
      walk(document.body, 0, options);
    }

    return {
      url: window.location.href,
      title: document.title,
      elements: options.elements,
    };
  }

  // ── Exports ────────────────────────────────────────────
  return {
    snapshot: snapshot,
    // Expose internals for testing
    _internals: {
      isInteractive: isInteractive,
      isVisible: isVisible,
      getRole: getRole,
      getText: getText,
      INTERACTIVE_SELECTORS: INTERACTIVE_SELECTORS,
      SKIP_TAGS: SKIP_TAGS,
    },
  };
})();

// Auto-export for different environments
if (typeof module !== 'undefined' && module.exports) {
  module.exports = StealthBrowserSnapshot;
}
if (typeof self !== 'undefined') {
  self.StealthBrowserSnapshot = StealthBrowserSnapshot;
}
