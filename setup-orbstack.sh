#!/usr/bin/env bash
# =============================================================================
# AscenAI — OrbStack Setup Script for macOS
# =============================================================================
# Usage: bash setup-orbstack.sh
# =============================================================================
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }
step()    { echo -e "\n${BOLD}▸ $*${RESET}"; }

# ── Ensure we're on macOS ─────────────────────────────────────────────────────
[[ "$(uname -s)" == "Darwin" ]] || error "This script is for macOS only."

echo -e "${BOLD}"
echo "  ╔═══════════════════════════════════════╗"
echo "  ║       AscenAI × OrbStack Setup        ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Homebrew
# ─────────────────────────────────────────────────────────────────────────────
step "Checking Homebrew"
if ! command -v brew &>/dev/null; then
  info "Homebrew not found — installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Add brew to PATH for Apple Silicon
  if [[ -f "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
  success "Homebrew installed"
else
  success "Homebrew already installed ($(brew --version | head -1))"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. OrbStack
# ─────────────────────────────────────────────────────────────────────────────
step "Checking OrbStack"
if ! command -v orb &>/dev/null && [[ ! -d "/Applications/OrbStack.app" ]]; then
  info "OrbStack not found — installing via Homebrew..."
  brew install --cask orbstack
  success "OrbStack installed"
else
  success "OrbStack already installed"
fi

# Launch OrbStack if not running
if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
  info "Starting OrbStack..."
  open -a OrbStack
  echo -n "  Waiting for Docker engine"
  for i in $(seq 1 30); do
    if docker info &>/dev/null 2>&1; then
      echo ""
      success "Docker engine is ready"
      break
    fi
    echo -n "."
    sleep 2
    if [[ $i -eq 30 ]]; then
      echo ""
      error "Docker engine did not start in 60 s. Open OrbStack manually and re-run this script."
    fi
  done
else
  success "Docker engine is already running ($(docker --version))"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Environment file
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

step "Configuring environment"
if [[ ! -f ".env" ]]; then
  cp .env.example .env
  info "Created .env from .env.example"
fi

# Generate a strong SECRET_KEY if the placeholder is still there
CURRENT_KEY=$(grep -E '^SECRET_KEY=' .env | cut -d= -f2-)
PLACEHOLDER="change-this-to-a-random-32-char-string-in-production"
if [[ "$CURRENT_KEY" == "$PLACEHOLDER" || -z "$CURRENT_KEY" ]]; then
  NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  # Replace in-place (works on both Intel and Apple Silicon macOS)
  sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_KEY}|" .env
  success "Generated and saved a new SECRET_KEY"
else
  success "SECRET_KEY is already set"
fi

# Check for LLM provider key
LLM_PROVIDER=$(grep -E '^LLM_PROVIDER=' .env | cut -d= -f2- | tr -d '[:space:]')
LLM_PROVIDER="${LLM_PROVIDER:-gemini}"

check_key() {
  local var="$1"
  local val
  val=$(grep -E "^${var}=" .env | cut -d= -f2- | tr -d '[:space:]')
  [[ -n "$val" ]]
}

case "$LLM_PROVIDER" in
  gemini)
    if ! check_key "GEMINI_API_KEY"; then
      warn "GEMINI_API_KEY is not set in .env"
      echo "  Get a free key at: https://aistudio.google.com/app/apikey"
      echo "  Then run:  nano .env   (set GEMINI_API_KEY=<your-key>)"
      echo ""
      read -rp "  Paste your Gemini API key now (or press Enter to skip): " api_key
      if [[ -n "$api_key" ]]; then
        sed -i '' "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${api_key}|" .env
        success "GEMINI_API_KEY saved"
      else
        warn "No key entered. The AI will not respond until you add one."
      fi
    else
      success "GEMINI_API_KEY is set"
    fi
    ;;
  openai)
    if ! check_key "OPENAI_API_KEY"; then
      warn "OPENAI_API_KEY is not set in .env"
      echo "  Get a key at: https://platform.openai.com/api-keys"
      read -rp "  Paste your OpenAI API key now (or press Enter to skip): " api_key
      if [[ -n "$api_key" ]]; then
        sed -i '' "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${api_key}|" .env
        success "OPENAI_API_KEY saved"
      else
        warn "No key entered. The AI will not respond until you add one."
      fi
    else
      success "OPENAI_API_KEY is set"
    fi
    ;;
  vertex)
    info "Using Vertex AI — make sure you have run: gcloud auth application-default login"
    ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
# 4. Build & start
# ─────────────────────────────────────────────────────────────────────────────
step "Building and starting services"
info "This takes 3–5 minutes on first run (image downloads + builds)..."
echo ""

docker compose up --build -d

# ─────────────────────────────────────────────────────────────────────────────
# 5. Wait for health checks
# ─────────────────────────────────────────────────────────────────────────────
step "Waiting for services to become healthy"

wait_healthy() {
  local name="$1"
  local url="$2"
  local max=30   # 30 × 5 s = 2.5 min per service
  echo -n "  ${name}"
  for i in $(seq 1 $max); do
    if curl -sf "$url" &>/dev/null; then
      echo -e " ${GREEN}✓${RESET}"
      return 0
    fi
    echo -n "."
    sleep 5
  done
  echo -e " ${RED}✗ (timed out)${RESET}"
  warn "${name} did not become healthy. Check logs: docker compose logs ${name}"
  return 1
}

wait_healthy "api-gateway    " "http://localhost:8000/health"
wait_healthy "mcp-server     " "http://localhost:8001/health"
wait_healthy "ai-orchestrator" "http://localhost:8002/health"
wait_healthy "voice-pipeline " "http://localhost:8003/health"
wait_healthy "frontend       " "http://localhost:3000"

# ─────────────────────────────────────────────────────────────────────────────
# 6. Done
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  AscenAI is running!${RESET}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${RESET}"
echo ""
echo -e "  Dashboard      →  ${BOLD}http://localhost:3000${RESET}"
echo -e "  API Gateway    →  ${BOLD}http://localhost:8000/docs${RESET}"
echo -e "  Orchestrator   →  ${BOLD}http://localhost:8002/docs${RESET}"
echo -e "  MCP Server     →  ${BOLD}http://localhost:8001/docs${RESET}"
echo -e "  Voice Pipeline →  ${BOLD}http://localhost:8003/docs${RESET}"
echo ""
echo -e "  OrbStack dashboard →  ${BOLD}http://local.orbstack.dev${RESET}"
echo ""
echo -e "  Useful commands:"
echo -e "    docker compose logs -f          # stream all logs"
echo -e "    docker compose logs -f <svc>    # stream one service"
echo -e "    docker compose down             # stop (keeps data)"
echo -e "    docker compose down -v          # stop + wipe volumes"
echo ""
