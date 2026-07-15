#!/usr/bin/env bash
# Install zlt into a local venv and expose it on PATH via ~/.local/bin.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_DIR/.venv"
BIN_DIR="${HOME}/.local/bin"

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -e "$PROJECT_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/zlt" "$BIN_DIR/zlt"

echo "Installed. 'zlt' -> $VENV/bin/zlt"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "PATH ok. Run: zlt --help" ;;
  *) echo "Add to PATH:  export PATH=\"$BIN_DIR:\$PATH\"  (in ~/.zshrc)" ;;
esac
echo "Next: zlt init-config"
