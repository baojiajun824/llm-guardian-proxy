#!/bin/sh
set -eu

: "${UPSTREAM_BASE_URL:?UPSTREAM_BASE_URL is required}"

exec mitmdump \
  --listen-host 0.0.0.0 \
  --listen-port 8080 \
  --mode "reverse:${UPSTREAM_BASE_URL}" \
  --set block_global=false \
  --set flow_detail=1 \
  -s /app/addon.py
