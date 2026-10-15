#!/usr/bin/env bash
# Long-running monitor: check every INTERVAL seconds for DURATION seconds, then exit
# (the workflow hands off to the next run). Avoids relying on GitHub's flaky cron.
source "$(dirname "$0")/common.sh"
INTERVAL=${INTERVAL:-600}
DURATION=${DURATION:-20700}   # 5h45m (job limit is 6h)
END=$(( $(date +%s) + DURATION ))
while :; do
  check_once
  now=$(date +%s)
  [ "$now" -ge "$END" ] && break
  left=$(( END - now ))
  sleep $(( left < INTERVAL ? left : INTERVAL ))
done
