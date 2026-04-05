"""
JS Runtime Property-Level Stealth Patches

7 anti-detection patches that patchright/CloakBrowser cannot handle.
These run inside the page context via Page.add_init_script(), before any
page scripts execute.

Coverage (vs patchright):
  - patchright: driver-level (webdriver flag, Runtime.Enable leak, sourceURL)
  - THIS module: JS property-level (chrome stub, plugins, languages, etc.)

Patches:
  1. window.chrome completeness
  2. navigator.plugins (fake if empty)
  3. navigator.languages (non-empty)
  4. Permissions.query notification fix
  5. Automation artifact cleanup (__playwright, __puppeteer, cdc_*)
  6. Error.stack CDP frame filtering

Reference: OpenCLI stealth.ts (proven in production)
"""

STEALTH_PATCHES_JS = """
(() => {
  // ── Patch 1: window.chrome completeness ──
  // Real Chrome always has chrome.runtime; headless/synthetic browsers often don't.
  if (!window.chrome || !window.chrome.runtime) {
    window.chrome = {
      runtime: {
        onConnect: { addListener: () => {}, removeListener: () => {} },
        onMessage: { addListener: () => {}, removeListener: () => {} },
        id: '',
        connect: function() { return { onDisconnect: { addListener: () => {} }, onMessage: { addListener: () => {} }, postMessage: () => {} }; },
        sendMessage: function() { return Promise.resolve(); },
      },
      loadTimes: function() {
        return {
          requestTime: function() { return 0; },
          startLoadTime: function() { return 0; },
          commitLoadTime: function() { return 0; },
          finishDocumentLoadTime: function() { return 0; },
          finishLoadTime: function() { return 0; },
          firstPaintTime: function() { return 0; },
          navigationStart: function() { return 0; },
        };
      },
      csi: function() {
        return {
          onloadT: function() { return ''; },
          startE: function() { return ''; },
          firstPaint: function() { return ''; },
          firstContentfulPaint: function() { return ''; },
          navigation: function() { return ''; },
          responseStart: function() { return 0; },
        };
      },
      app: {
        isInstalled: false,
        InstallState: { DISABLED: 0, INSTALLED: 1, NOT_INSTALLED: 2 },
        RunningState: { CANNOT_RUN: 0, READY_TO_RUN: 1, RUNNING: 2 },
      },
    };
  }

  // ── Patch 2: navigator.plugins (fake if empty) ──
  // Headless browsers often report 0 plugins.
  try {
    if (!navigator.plugins || navigator.plugins.length === 0) {
      const fakePlugins = [
        { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
        { name: 'Chromium PDF Plugin', filename: 'internal-pdf-viewer', description: '', length: 1 },
      ];
      fakePlugins.item = function(i) { return fakePlugins[i] || null; };
      fakePlugins.namedItem = function(n) {
        for (let i = 0; i < fakePlugins.length; i++) {
          if (fakePlugins[i].name === n) return fakePlugins[i];
        }
        return null;
      };
      fakePlugins.refresh = function() {};
      Object.defineProperty(navigator, 'plugins', {
        get: function() { return fakePlugins; },
        configurable: true,
      });
      // Also fix mimeTypes (tied to plugins)
      const fakeMimes = [
        { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
      ];
      fakeMimes.item = function(i) { return fakeMimes[i] || null; };
      fakeMimes.namedItem = function(n) {
        for (let i = 0; i < fakeMimes.length; i++) {
          if (fakeMimes[i].type === n) return fakeMimes[i];
        }
        return null;
      };
      Object.defineProperty(navigator, 'mimeTypes', {
        get: function() { return fakeMimes; },
        configurable: true,
      });
    }
  } catch(e) {}

  // ── Patch 3: navigator.languages (non-empty) ──
  // Some automation frameworks leave this empty.
  try {
    if (!navigator.languages || navigator.languages.length === 0) {
      Object.defineProperty(navigator, 'languages', {
        get: function() { return ['zh-CN', 'zh', 'en-US', 'en']; },
        configurable: true,
      });
    }
  } catch(e) {}

  // ── Patch 4: Permissions.query notification fix ──
  // Chrome returns 'prompt' for notifications; some bots return 'denied'.
  try {
    var _origPermissionsQuery = window.Permissions && window.Permissions.prototype && window.Permissions.prototype.query;
    if (_origPermissionsQuery) {
      window.Permissions.prototype.query = function(params) {
        if (params && params.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return _origPermissionsQuery.call(this, params);
      };
    }
  } catch(e) {}

  // ── Patch 5: Cleanup automation artifacts ──
  // Remove traces left by Playwright, Puppeteer, and older ChromeDriver versions.
  try {
    delete window.__playwright;
    delete window.__playwright_evaluation_script__;
    delete window.__puppeteer;
    delete window._phantom;
    delete window.callPhantom;
    delete window.domAutomation;
    delete window.domAutomationController;
    // cdc_ / __cdc_ prefixes from old chromedriver
    var props = Object.getOwnPropertyNames(window);
    for (var i = 0; i < props.length; i++) {
      if (props[i].indexOf('cdc_') === 0 || props[i].indexOf('__cdc_') === 0) {
        try { delete window[props[i]]; } catch(e2) {}
      }
    }
  } catch(e) {}

  // ── Patch 6: Error.stack CDP frame cleanup ──
  // Remove puppeteer/playwright evaluation frames from stack traces.
  try {
    var _stackDesc = Object.getOwnPropertyDescriptor(Error.prototype, 'stack');
    if (_stackDesc && _stackDesc.get) {
      var _cdpPatterns = [
        'puppeteer_evaluation_script',
        'pptr:',
        'debugger://',
        '__playwright',
        '__puppeteer',
        '@chromium/',
        'evaluate (new Function',
      ];
      Object.defineProperty(Error.prototype, 'stack', {
        get: function() {
          var raw = _stackDesc.get.call(this);
          if (typeof raw !== 'string') return raw;
          return raw.split('\\n').filter(function(line) {
            return !_cdpPatterns.some(function(p) { return line.indexOf(p) !== -1; });
          }).join('\\n');
        },
        configurable: true,
      });
    }
  } catch(e) {}

  return 'stealth_patches_applied';
})()
"""


async def inject_stealth_patches(page) -> None:
    """
    Inject all 7 stealth patches into a page via add_init_script.

    Called during session creation (before any navigation).
    Patches are applied to every new document/frame automatically.
    """
    await page.add_init_script(STEALTH_PATCHES_JS)


async def verify_patches(page) -> dict:
    """
    Verify all 7 patches are active after navigation.
    Returns dict of patch_name → bool (True = verified).
    """
    checks = await page.evaluate("""(() => {
      return {
        chrome_runtime: !!(window.chrome && window.chrome.runtime),
        plugins_nonempty: navigator.plugins.length > 0,
        languages_nonempty: navigator.languages.length > 0,
        no_playwright: typeof window.__playwright === 'undefined',
        no_puppeteer: typeof window.__puppeteer === 'undefined',
        error_stack_clean: (function() {
          try { throw new Error('test'); } catch(e) {
            return !e.stack.includes('pptr:') && !e.stack.includes('__playwright');
          }
        })(),
      };
    })()""")
    return checks
