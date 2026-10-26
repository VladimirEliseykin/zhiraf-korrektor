#!/bin/bash
# Idle watchdog (2026-10-26): a forgotten or orphaned rented machine destroys itself instead of burning money.
# Busy = a python job, a file transfer (rsync/scp/sftp) or a loaded GPU. 30 idle minutes in a row -> destroy.
# Keep the machine alive on purpose: touch /root/zhiraf/KEEP_ALIVE (checked every minute).
LIMIT=30
idle=0
while true; do
  gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
  if [ -f /root/zhiraf/KEEP_ALIVE ] || pgrep -f "python" >/dev/null || pgrep -f "rsync|scp|sftp-server" >/dev/null \
     || [ "${gpu:-0}" -gt 5 ]; then
    idle=0
  else
    idle=$((idle + 1))
  fi
  if [ $idle -ge $LIMIT ]; then
    echo "$(date) idle for $LIMIT min: destroying instance $CONTAINER_ID"
    $(command -v vastai || echo /opt/instance-tools/bin/vastai) destroy instance "$CONTAINER_ID" --api-key "$CONTAINER_API_KEY"
    exit 0
  fi
  sleep 60
done
