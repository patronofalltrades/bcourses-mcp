#!/usr/bin/env bash
#
# One-time setup for the bCourses student MCP server.
#
# Stores your Canvas access token in the macOS Keychain, builds the server,
# and prints the command to register it with your MCP client.
#
# The token is never written to a file, never passed as a command argument
# (which would expose it in `ps`), and never printed. macOS prompts for it.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="$REPO_DIR/server"
SERVICE="${BCOURSES_KEYCHAIN_SERVICE:-bcourses-student-mcp}"
ACCOUNT="${USER:-$(id -un)}"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
warn() { printf "\033[33m%s\033[0m\n" "$1"; }
die()  { printf "\033[31mError: %s\033[0m\n" "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Preconditions
# ---------------------------------------------------------------------------

[[ "$(uname -s)" == "Darwin" ]] || die "This script uses the macOS Keychain. On Linux or Windows, set BCOURSES_ACCESS_TOKEN in your MCP client's env config instead — but never in a file you might commit."

command -v node >/dev/null || die "Node.js not found. Install Node 20 or newer, then re-run."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
(( NODE_MAJOR >= 20 )) || die "Node $NODE_MAJOR found; this server needs Node 20 or newer."

command -v npm >/dev/null || die "npm not found. It ships with Node."

bold "bCourses student MCP — setup"
echo "Repo:    $REPO_DIR"
echo "Node:    $(node -v)"
echo "Keychain service: $SERVICE"
echo

# ---------------------------------------------------------------------------
# 2. Refuse to co-exist with a .env holding a token
# ---------------------------------------------------------------------------

if [[ -f "$SERVER_DIR/.env" ]] && grep -q "BCOURSES_ACCESS_TOKEN=..*" "$SERVER_DIR/.env" 2>/dev/null; then
  warn "Found a token in $SERVER_DIR/.env"
  echo "A Canvas token in a file is one 'git add .' away from being public, and"
  echo "the token has no permission scoping — it can read your grades and submit"
  echo "your work. Delete that line, then re-run this script."
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. Token into the Keychain
# ---------------------------------------------------------------------------

if security find-generic-password -a "$ACCOUNT" -s "$SERVICE" -w >/dev/null 2>&1; then
  bold "A token is already stored for '$SERVICE'."
  read -r -p "Replace it? [y/N] " REPLACE
  [[ "$REPLACE" =~ ^[Yy]$ ]] || SKIP_TOKEN=1
fi

if [[ -z "${SKIP_TOKEN:-}" ]]; then
  cat <<'EOF'

Get a token from bCourses:
  Account → Settings → Approved Integrations → + New Access Token

  Purpose:  bcourses-mcp
  Expires:  set a date — end of term is a good default.

  An access token acts as you, with no permission scoping. Expiry is the only
  limit available, so please set one. Copy the token now; bCourses shows it
  exactly once.

macOS will prompt for the token below. Nothing is echoed or logged.

EOF
  read -r -p "Press Return when you have the token on your clipboard... " _
  security add-generic-password -U -a "$ACCOUNT" -s "$SERVICE" -w \
    || die "Keychain write failed. Nothing was stored."
  bold "Stored in Keychain."
fi

# ---------------------------------------------------------------------------
# 4. Build
# ---------------------------------------------------------------------------

echo
bold "Installing dependencies and building..."
cd "$SERVER_DIR"
npm install --silent
npm run build --silent
[[ -f "$SERVER_DIR/dist/src/stdio.js" ]] || die "Build produced no dist/src/stdio.js."

# ---------------------------------------------------------------------------
# 5. Verify the token actually works
# ---------------------------------------------------------------------------

echo
bold "Checking the token against bCourses..."
BASE_URL="${BCOURSES_BASE_URL:-https://bcourses.berkeley.edu}"
TOKEN="$(security find-generic-password -a "$ACCOUNT" -s "$SERVICE" -w)"
HTTP_CODE="$(curl -s -o /tmp/bcourses-whoami.$$ -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/v1/users/self/profile" || echo 000)"
unset TOKEN

case "$HTTP_CODE" in
  200)
    NAME="$(node -e 'const d=require("/tmp/bcourses-whoami."+process.argv[1]);console.log(d.name||"(no name)")' "$$" 2>/dev/null || echo "your account")"
    bold "Connected as $NAME."
    ;;
  401) rm -f "/tmp/bcourses-whoami.$$"; die "bCourses rejected the token (401). It may be mistyped or already expired. Re-run to replace it." ;;
  000) rm -f "/tmp/bcourses-whoami.$$"; die "Could not reach $BASE_URL. Check your network." ;;
  *)   rm -f "/tmp/bcourses-whoami.$$"; die "bCourses returned HTTP $HTTP_CODE." ;;
esac
rm -f "/tmp/bcourses-whoami.$$"

# ---------------------------------------------------------------------------
# 6. How to register it
# ---------------------------------------------------------------------------

LAUNCHER="$SERVER_DIR/bin/start-bcourses-mcp"
chmod +x "$LAUNCHER"

cat <<EOF

$(bold "Done. Register the server with your client:")

Claude Code
  claude mcp add bcourses -- "$LAUNCHER"

Claude Desktop — edit
  ~/Library/Application Support/Claude/claude_desktop_config.json

  {
    "mcpServers": {
      "bcourses": { "command": "$LAUNCHER" }
    }
  }

  Paths must be absolute; this file is plain JSON and does not expand ~ or
  \$HOME. Quit Claude Desktop with Cmd-Q and reopen — closing the window is
  not enough.

The launcher reads the token from your Keychain and passes it only to the
server process. macOS may ask permission the first time.

Skills for Claude live in ./skills — see the README.
EOF
