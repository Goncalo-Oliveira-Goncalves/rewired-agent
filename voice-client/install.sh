#!/bin/bash
set -e

REPO_URL="https://github.com/Goncalo-Oliveira-Goncalves/rewired-agent"
BRANCH="agent-swarm-comms"
BIN_DIR="${REWIRED_BIN_DIR:-$HOME/.local/bin}"

# Check for Rust
if ! command -v cargo &>/dev/null; then
  echo "Rust is required. Install it first:"
  echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi

echo "Cloning rewired-agent..."
TMP_DIR=$(mktemp -d)
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP_DIR" 2>/dev/null

cd "$TMP_DIR/voice-client"
echo "Building rewired-voice-client..."
cargo build --release 2>&1 | tail -3

mkdir -p "$BIN_DIR"
cp target/release/rewired-voice-client "$BIN_DIR/rewired-voice-client"
chmod +x "$BIN_DIR/rewired-voice-client"

rm -rf "$TMP_DIR"
echo "Installed to $BIN_DIR/rewired-voice-client"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Warning: $BIN_DIR is not on your PATH. Add it or move the binary." ;;
esac
