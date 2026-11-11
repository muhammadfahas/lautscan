#!/usr/bin/env bash
# ==============================================================================
# LAUT SCAN: WSL2 / Linux Developer Environment Setup
# ==============================================================================
# Automates and documents the WSL2/Linux prerequisites required by Expo Exact
# and LAUT SCAN frontend verification (PRD v1.2 Sections 6.1, 6.6, 13):
#   1. Base Linux build tools (curl, git, unzip, build-essential, pkg-config)
#   2. Bun 1.4.2 (pinned runtime for Expo Exact CLI & headless web test driver)
#   3. Rustup + stable Rust toolchain (Exact native/Taffy runner & contract CLI)
#   4. Chromium / Google Chrome check (Exact Web Host & scripts/agent.mjs)
#   5. Sibling checkout & setup of https://github.com/expo/exact at ../exact
#
# Usage:
#   bash infra/scripts/setup-wsl.sh [--strict]
#
# Environment overrides:
#   EXACT_DIR=/path/to/exact   Custom checkout path (default: <repo-parent>/exact)
#   EXACT_REF=<commit-or-tag>  Optional pinned commit SHA / tag for expo/exact
#   CHROME_BIN=/path/to/chrome Optional explicit Chrome/Chromium binary path
# ==============================================================================

set -euo pipefail

STRICT=false
for arg in "$@"; do
  case "$arg" in
    --strict)
      STRICT=true
      ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

BUN_TARGET_VERSION="1.4.2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUTSCAN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
EXACT_DIR="${EXACT_DIR:-$(dirname "$LAUTSCAN_ROOT")/exact}"
EXACT_REPO="${EXACT_REPO:-https://github.com/expo/exact.git}"
EXACT_REF="${EXACT_REF:-}"

log()  { printf '[setup-wsl] %s\n' "$*"; }
warn() { printf '[setup-wsl][WARN] %s\n' "$*" >&2; }
err()  { printf '[setup-wsl][ERROR] %s\n' "$*" >&2; }

# ==============================================================================
# 1. Verify Linux / WSL2 host
# ==============================================================================
OS_NAME="$(uname -s)"
if [[ "$OS_NAME" != "Linux" ]]; then
  warn "Detected OS '$OS_NAME'. This script targets Linux / WSL2 (Ubuntu/Debian)."
fi

if grep -qi microsoft /proc/version 2>/dev/null; then
  log "Running inside WSL2 Linux environment."
fi

# ==============================================================================
# 2. Ensure base OS utilities (Debian / Ubuntu)
# ==============================================================================
REQUIRED_CMDS=(curl git unzip pkg-config cc)
MISSING_BASE=false
for cmd in "${REQUIRED_CMDS[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    MISSING_BASE=true
    break
  fi
done

if [[ "$MISSING_BASE" == "true" ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing base build prerequisites via apt-get..."
    SUDO=""
    if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
      SUDO="sudo"
    fi
    $SUDO apt-get update -y
    $SUDO apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      unzip \
      build-essential \
      pkg-config
  else
    err "Missing required tools (${REQUIRED_CMDS[*]}) and apt-get is unavailable."
    exit 1
  fi
else
  log "Base build tools present (curl, git, unzip, pkg-config, cc)."
fi

# ==============================================================================
# 3. Install or verify Bun 1.4.2
# ==============================================================================
export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
export PATH="$BUN_INSTALL/bin:$PATH"

CURRENT_BUN_VERSION=""
if command -v bun >/dev/null 2>&1; then
  CURRENT_BUN_VERSION="$(bun --version 2>/dev/null || true)"
fi

if [[ "$CURRENT_BUN_VERSION" == "$BUN_TARGET_VERSION" ]]; then
  log "Bun $CURRENT_BUN_VERSION is already installed."
else
  log "Installing Bun v${BUN_TARGET_VERSION} (found: '${CURRENT_BUN_VERSION:-none}')..."
  curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_TARGET_VERSION}"
  export PATH="$BUN_INSTALL/bin:$PATH"
  log "Installed Bun: $(bun --version)"
fi

# ==============================================================================
# 4. Install or verify Rustup + stable toolchain
# ==============================================================================
if [[ -f "$HOME/.cargo/env" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
fi

if ! command -v rustup >/dev/null 2>&1; then
  log "Installing rustup (stable toolchain)..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env"
else
  log "rustup detected: $(rustup --version | head -n 1)"
  if ! command -v rustc >/dev/null 2>&1; then
    rustup toolchain install stable
    rustup default stable
  fi
fi

log "Rust toolchain: $(rustc --version) | $(cargo --version)"

# ==============================================================================
# 5. Chromium / Google Chrome check (for Expo Exact Web Host & scripts/agent.mjs)
# ==============================================================================
find_chrome() {
  if [[ -n "${CHROME_BIN:-}" ]] && [[ -x "${CHROME_BIN}" ]]; then
    echo "$CHROME_BIN"
    return 0
  fi

  local candidates=(
    google-chrome
    google-chrome-stable
    chromium
    chromium-browser
    /usr/bin/google-chrome
    /usr/bin/chromium
    /usr/bin/chromium-browser
  )

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    elif [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  # Fallback: check Playwright-installed Chromium cache in WSL
  local pw_chrome
  pw_chrome="$(find "$HOME/.cache/ms-playwright" -maxdepth 4 -type f -name chrome 2>/dev/null | head -n 1 || true)"
  if [[ -n "$pw_chrome" ]] && [[ -x "$pw_chrome" ]]; then
    echo "$pw_chrome"
    return 0
  fi

  return 1
}

CHROME_FOUND="$(find_chrome || true)"
if [[ -n "$CHROME_FOUND" ]]; then
  log "Chrome/Chromium binary detected: $CHROME_FOUND"
else
  warn "Chrome/Chromium was not found in WSL2."
  warn "Expo Exact Web Host and scripts/agent.mjs require Chromium/Chrome inside Linux/WSL2."
  warn "Install options on Ubuntu/WSL2:"
  warn "  Option A (Chromium snap/apt): sudo apt-get update && sudo apt-get install -y chromium-browser"
  warn "  Option B (Playwright Chromium): bunx playwright install chromium --with-deps"
  warn "  Option C (Google Chrome): wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && sudo apt install -y ./google-chrome-stable_current_amd64.deb"
  if [[ "$STRICT" == "true" ]]; then
    err "Exiting due to --strict mode because Chrome/Chromium is missing."
    exit 1
  fi
fi

# ==============================================================================
# 6. Clone & configure expo/exact sibling checkout
# ==============================================================================
if [[ ! -d "$EXACT_DIR/.git" ]]; then
  log "Cloning expo/exact into sibling directory: $EXACT_DIR"
  mkdir -p "$(dirname "$EXACT_DIR")"
  git clone "$EXACT_REPO" "$EXACT_DIR"
else
  log "Existing expo/exact checkout found at: $EXACT_DIR"
fi

if [[ -n "$EXACT_REF" ]]; then
  log "Checking out pinned expo/exact ref: $EXACT_REF"
  git -C "$EXACT_DIR" fetch --all --tags
  git -C "$EXACT_DIR" checkout "$EXACT_REF"
fi

EXACT_SHA="$(git -C "$EXACT_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
log "expo/exact HEAD: $EXACT_SHA"

if [[ -f "$EXACT_DIR/package.json" ]]; then
  log "Installing expo/exact workspace dependencies via bun..."
  (cd "$EXACT_DIR" && bun install)
fi

if [[ -f "$EXACT_DIR/scripts/exact.mjs" ]]; then
  log "Running expo/exact toolchain setup (bun scripts/exact.mjs setup)..."
  (cd "$EXACT_DIR" && bun scripts/exact.mjs setup)
else
  warn "scripts/exact.mjs not found in $EXACT_DIR; skipping automated Exact setup."
fi

# ==============================================================================
# 7. Summary
# ==============================================================================
log "======================================================================"
log "WSL2 / Linux setup check complete:"
log "  LAUT SCAN root : $LAUTSCAN_ROOT"
log "  expo/exact dir : $EXACT_DIR (commit: $EXACT_SHA)"
log "  Bun            : $(bun --version)"
log "  Rust           : $(rustc --version)"
log "  Chrome/Chromium: ${CHROME_FOUND:-NOT INSTALLED (see warnings above)}"
log ""
log "Next steps:"
log "  1. Ensure ~/.bun/bin and ~/.cargo/bin are on PATH in ~/.bashrc"
log "  2. Copy infra/.env.example -> infra/.env and start backend services:"
log "     docker compose -f infra/docker-compose.yml up -d --build"
log "======================================================================"
