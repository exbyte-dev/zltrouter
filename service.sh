#!/usr/bin/env bash
# Manage the zlt web dashboard as a systemd --user service.
# User-scoped, no root. Mirrors install.sh.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_DIR/.venv"
ZLT_BIN="$VENV/bin/zlt"

SERVICE_NAME="zlt-web"
BIND_HOST="0.0.0.0"
PORT="8464"

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="$CONFIG_HOME/systemd/user"
UNIT_PATH="$UNIT_DIR/${SERVICE_NAME}.service"

# Emit the systemd unit text. Both `install` and `print-unit` use this, so the
# generated unit can be asserted on in a test without touching systemd.
# NOTE: %h is a systemd specifier and must stay literal. This heredoc is
# unquoted so $ZLT_BIN/$BIND_HOST/$PORT expand while %h does not.
generate_unit() {
  cat <<EOF
[Unit]
Description=zlt router dashboard (local web UI)

[Service]
ExecStart=$ZLT_BIN serve --host $BIND_HOST --port $PORT
WorkingDirectory=%h
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=default.target
EOF
}

usage() {
  echo "usage: $0 {install|suspend|resume|status|logs|uninstall|print-unit}" >&2
  exit 2
}

case "${1:-install}" in
  print-unit) generate_unit ;;
  *) usage ;;
esac
