#!/usr/bin/env bash
# Weekly FMV Update — intended for Monday morning cron / scheduler
# Usage:  crontab -e  →  0 7 * * 1 /home/user/sports-card-agent/scripts/weekly_fmv_update.sh
#         or: systemd timer, GitHub Actions, Task Scheduler, etc.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$SCRIPT_DIR/data"
LOG_FILE="$LOG_DIR/fmv_cron.log"
PYTHON="${PYTHON:-python3}"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "FMV Update started: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$SCRIPT_DIR"
$PYTHON -m src.cli update-fmv --delay 1.0 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "FMV Update finished: $(date '+%Y-%m-%d %H:%M:%S') (exit: $EXIT_CODE)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
