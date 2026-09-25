#!/usr/bin/env bash
# Hits /version every 100 ms and logs: timestamp, response body, HTTP status
# Usage: ./loadtest/probe.sh <ip> [logfile]
IP=$1
LOG=${2:-loadtest/cutover.log}
while true; do
  resp=$(curl -s -m 2 -w ' %{http_code}' "http://$IP/version")
  echo "$(date +%T.%3N) $resp" | tee -a "$LOG"
  sleep 0.1
done
