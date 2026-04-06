#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  detection_audit.sh — Manual Anti-Detection Audit (Tier 2)
# ══════════════════════════════════════════════════════════
#
# Launches CloakBrowser with fresh profile, navigates to known detection
# challenge pages, takes screenshots, produces a markdown report.
#
# Usage:
#   bash scripts/detection_audit.sh                          # All targets
#   bash scripts/detection_audit.sh --targets cloudflare,pixelscan    # Specific targets
#   bash scripts/detection_audit.sh --output ./report.md           # Custom output path
#
# Prerequisites:
#   - CloakBrowser installed (pip install cloakbrowser)
#   - playwright installed (playwright install chromium)
#   - Python 3.11+ with aiohttp, Pillow
#
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────

CDP_URL="${CDP_URL:-http://127.0.0.1:19222}"
OUTPUT_FILE=""
TARGETS=("nowsecure" "bot.sannysoft" "arhivach")
TIMEOUT=30
SCREENSHOT_DIR="$(mktemp -d)"
REPORT_TEMP="$(mktemp)"

# ── Parse Arguments ────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output) OUTPUT_FILE="$2"; shift 2 ;;
        --targets) IFS=',' read -ra TARGETS <<< "$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--output FILE] [--targets t1,t2,...] [--timeout SECS]"
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -n "${TARGETS+x}" ]]; then
    TARGETS=("${TARGETS[@]}")
fi

if [[ -z "$OUTPUT_FILE" ]]; then
    OUTPUT_FILE="./detection-report-$(date +%Y%m%d-%H%M%S).md"
fi

# ── Check CDP ──────────────────────────────────────────────────────

echo "=== Detection Audit ==="
echo "Checking CDP at ${CDP_URL}..."

if ! python3 -c "
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
result = s.connect_ex(('127.0.0.1', 19222))
s.close()
sys.exit(1 if result != 0 else 0)
" 2>/dev/null; then
    echo "ERROR: CloakBrowser not available on port 19222"
    echo "Start it first: cloakbrowser-launch or your browser daemon"
    exit 1
fi

echo "CDP available. Starting audit..."
echo ""

# ── Target Definitions ──────────────────────────────────────────

declare -A TARGET_URLS TARGET_NAMES
TARGET_URLS=(
    [nowsecure]="https://nowsecure.nl"
    [bot.sannysoft]="https://bot.sannysoft.com"
    [arhivach]="https://arhivach.to/detect"
)
TARGET_NAMES=(
    [nowsecure]="NowSecure (self-check)"
    [bot.sannysoft]="SannySoft (fingerprint analysis)"
    [arhivach]="Arhivach (common detector)"
)

# Optional: Cloudflare and PixelScan (user-provided URLs)
for t in "${TARGETS[@]}"; do
    if [[ ! -v "TARGET_URLS[$t]" ]] && [[ "$t" == cloudflare ]]; then
        TARGET_URLS[cloudflare]="${CLOUDFLARE_URL:-https://nowsecure.nl}"
        TARGET_NAMES[cloudflare]="Cloudflare Challenge"
    fi
    if [[ ! -v "TARGET_URLS[$t]" ]] && [[ "$t" == pixelscan ]]; then
        TARGET_URLS[pixelscan]="https://pixelscan.net/studio"
        TARGET_NAMES[pixelscan]="PixelScan (fingerprint entropy)"
    fi
done

# ── Screenshot Helper ────────────────────────────────────────────

take_screenshot() {
    local url="$1"
    local name="$2"
    local path="${SCREENSHOT_DIR}/${name}.png"

    python3 -c "
import asyncio, json, sys

async def screenshot(url, path):
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp('${CDP_URL}')
            page = await browser.new_page()
            await page.goto(url, timeout=${TIMEOUT}000, wait_until='domcontentloaded')
            await page.wait_for_timeout(2000)
            await page.screenshot(path=path, full_page=True)
            title = await page.title()
            await browser.close()
            return title
    except Exception as e:
        return f'ERROR: {e}'
" "$url" "$path"
}

# ── Run Audit ────────────────────────────────────────────────────

echo "# Anti-Detection Audit Report" > "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"
echo "**Generated:** $(date -u '+%Y-%m-%d %H:%M UTC')" >> "$REPORT_TEMP"
echo "**CDP URL:** \`${CDP_URL}\`" >> "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"

echo "## Results" >> "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"
echo "| Target | Status | Screenshot | Notes |" >> "$REPORT_TEMP"
echo "|--------|--------|-----------|-------|" >> "$REPORT_TEMP"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

for target in "${TARGETS[@]}"; do
    url="${TARGET_URLS[$target]}"
    name="${TARGET_NAMES[$target]}"
    safe_name=$(echo "$target" | tr '/:' '_')
    echo ""
    echo "--- Auditing: ${name} (${url}) ---"

    title=$(take_screenshot "$url" "$safe_name")
    screenshot_path="${SCREENSHOT_DIR}/${safe_name}.png"

    # Basic heuristics from page content
    status="UNKNOWN"
    notes="Manual review required"

    if [[ "$title" == ERROR* ]]; then
        status="ERROR"
        notes="$title"
        ((FAIL_COUNT++))
    elif echo "$title" | grep -qi "blocked\|detected\|bot\|automated\|unusual"; then
        status="DETECTED"
        notes="Detection indicators found in page title/content"
        ((FAIL_COUNT++))
    elif echo "$title" | grep -qi "human\|pass\|verified\|clean\|ok"; then
        status="PASS"
        notes="No obvious detection signals"
        ((PASS_COUNT++))
    else
        status="WARN"
        notes="Unable to determine — manual review needed"
        ((WARN_COUNT++))
    fi

    echo "| **${name}** | **${status}** | ![${safe_name}](${screenshot_path}) | ${notes} |" >> "$REPORT_TEMP"
    echo "  → ${status}: ${notes}"
done

# ── Summary ──────────────────────────────────────────────────────

echo "" >> "$REPORT_TEMP"
echo "## Summary" >> "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"
echo "- **Pass:** ${PASS_COUNT}" >> "$REPORT_TEMP"
echo "- **Fail:** ${FAIL_COUNT}" >> "$REPORT_TEMP"
echo "- **Warn:** ${WARN_COUNT}" >> "$REPORT_TEMP"
echo "- **Total:** $((PASS_COUNT + FAIL_COUNT + WARN_COUNT))" >> "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"
echo "## Screenshots" >> "$REPORT_TEMP"
echo "" >> "$REPORT_TEMP"

for img in "${SCREENSHOT_DIR}"/*.png; do
    if [[ -f "$img" ]]; then
        name=$(basename "$img" .png)
        echo "### ${name}" >> "$REPORT_TEMP"
        echo "![](${img})" >> "$REPORT_TEMP"
        echo "" >> "$REPORT_TEMP"
    fi
done

# ── Write Final Report ──────────────────────────────────────────

cp "$REPORT_TEMP" "$OUTPUT_FILE"
echo ""
echo "========================================="
echo "Audit complete: ${OUTPUT_FILE}"
echo "  Pass: ${PASS_COUNT} | Fail: ${FAIL_COUNT} | Warn: ${WARN_COUNT}"
echo "  Screenshots saved to: ${SCREENSHOT_DIR}"
echo "========================================="

# Cleanup temp files on success (keep screenshots)
rm -f "$REPORT_TEMP"
