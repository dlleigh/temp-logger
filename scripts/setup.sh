#!/bin/bash
# One-time (idempotent) setup for temp-logger on Raspberry Pi (Raspbian).
#
# Run as the 'pi' user -- NOT with sudo. It calls sudo only for the system-level
# steps so that the repo and venv stay owned by pi.
#
# Re-run this after you change dependencies or the systemd unit. It is safe to
# run repeatedly.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"
SERVICE_SRC="$REPO_DIR/systemd/temp-logger.service"
LOGROTATE_SRC="$REPO_DIR/scripts/logrotate-temp-logger"
CONFIG_PATH="/etc/temp-logger.yml"
RUN_USER="$(id -un)"

# The log path for logrotate comes from the config's `logfile:` if present,
# otherwise defaults under this user's home.
LOGFILE="$HOME/temp-logger.log"
if [ -f "$CONFIG_PATH" ]; then
    cfg_log="$(grep -E '^[[:space:]]*logfile:' "$CONFIG_PATH" | head -1 | sed -E 's/^[^:]*:[[:space:]]*//')"
    [ -n "$cfg_log" ] && LOGFILE="$cfg_log"
fi

echo "==> Installing system packages"
# numpy/scipy/yaml/dateutil are installed via apt: Debian ships prebuilt
# armv6 binaries for these, so there is NO compiling on the Pi Zero (pip would
# otherwise try to build them from source, which can take an hour or OOM).
sudo apt-get update
sudo apt-get install -y git python3-venv python3-numpy python3-scipy \
    python3-yaml python3-dateutil

echo "==> Creating venv (with system site-packages) at $VENV_DIR"
# --system-site-packages lets the venv see the apt-installed numpy/scipy/etc.
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

echo "==> Installing pure-Python deps into the venv (no compilation)"
# influxdb-client and its deps (reactivex, urllib3, certifi) are pure-Python
# wheels -- safe to pip install even on armv6.
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install "influxdb-client==1.48.0"

echo "==> Installing systemd unit (user=$RUN_USER, dir=$REPO_DIR)"
sed -e "s#__REPO_DIR__#$REPO_DIR#g" -e "s#__USER__#$RUN_USER#g" \
    "$SERVICE_SRC" | sudo tee /etc/systemd/system/temp-logger.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable temp-logger.service

echo "==> Installing logrotate rule (logfile=$LOGFILE)"
sed -e "s#__LOGFILE__#$LOGFILE#g" -e "s#__USER__#$RUN_USER#g" \
    "$LOGROTATE_SRC" | sudo tee /etc/logrotate.d/temp-logger >/dev/null

if [ ! -f "$CONFIG_PATH" ]; then
    echo "!! WARNING: $CONFIG_PATH not found -- create it before starting the service."
fi

echo
echo "==> Setup complete. Start it with:"
echo "      sudo systemctl restart temp-logger.service"
echo "    Follow it with:"
echo "      journalctl -u temp-logger -f"
