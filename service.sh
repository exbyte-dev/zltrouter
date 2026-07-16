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

ensure_web_extra() {
  if ! "$VENV/bin/python" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    echo "Installing web extra (fastapi, uvicorn) into the venv..."
    "$VENV/bin/pip" install -e "$PROJECT_DIR[web]" >/dev/null
  fi
}

warn_if_no_password() {
  local config="$CONFIG_HOME/zlt/config"
  if [ ! -f "$config" ]; then
    echo "warning: $config not found; dashboard will run unauthenticated." >&2
    echo "         run 'zlt init-config' to set host/username/password." >&2
  elif ! grep -qE '^ZLT_PASSWORD=.+' "$config"; then
    echo "warning: no ZLT_PASSWORD in $config; dashboard shows open keys only." >&2
  fi
}

cmd_install() {
  if [ ! -x "$ZLT_BIN" ]; then
    echo "zlt not found at $ZLT_BIN. Run ./install.sh first." >&2
    exit 1
  fi
  ensure_web_extra
  warn_if_no_password

  mkdir -p "$UNIT_DIR"
  generate_unit > "$UNIT_PATH"
  systemctl --user daemon-reload

  # Linger makes the service truly always-on (survives logout, starts at boot).
  # Enabling it for your own user may need privilege; degrade gracefully.
  local me
  me="$(id -un)"
  if ! loginctl enable-linger "$me" >/dev/null 2>&1; then
    echo "note: could not enable linger (needs privilege)." >&2
    echo "      service will start on login; for boot-without-login run:" >&2
    echo "      sudo loginctl enable-linger $me" >&2
  fi

  systemctl --user enable --now "$SERVICE_NAME"

  local lan_ip
  lan_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo
  echo "Installed and started $SERVICE_NAME."
  echo "  local:  http://127.0.0.1:$PORT"
  [ -n "$lan_ip" ] && echo "  LAN:    http://$lan_ip:$PORT   (phone/other devices)"
  echo
  echo "Control:"
  echo "  ./service.sh suspend    # stop (until resume or reboot)"
  echo "  ./service.sh resume     # start"
  echo "  ./service.sh status     # current state"
  echo "  ./service.sh logs       # follow logs"
  echo "  ./service.sh uninstall  # remove for good"
}

cmd_suspend() {
  systemctl --user stop "$SERVICE_NAME"
  echo "Suspended $SERVICE_NAME (returns on 'resume' or next reboot;"
  echo "use './service.sh uninstall' to keep it off across reboots)."
}

cmd_resume() { systemctl --user start "$SERVICE_NAME"; echo "Resumed $SERVICE_NAME."; }

cmd_status() { systemctl --user status "$SERVICE_NAME" --no-pager; }

cmd_logs() { journalctl --user -u "$SERVICE_NAME" -f; }

cmd_uninstall() {
  systemctl --user disable --now "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload
  echo "Uninstalled $SERVICE_NAME (linger left as-is)."
}

usage() {
  echo "usage: $0 {install|suspend|resume|status|logs|uninstall|print-unit}" >&2
  exit 2
}

case "${1:-install}" in
  install)    cmd_install ;;
  suspend)    cmd_suspend ;;
  resume)     cmd_resume ;;
  status)     cmd_status ;;
  logs)       cmd_logs ;;
  uninstall)  cmd_uninstall ;;
  print-unit) generate_unit ;;
  *)          usage ;;
esac
