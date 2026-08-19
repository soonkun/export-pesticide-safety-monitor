#!/usr/bin/env bash
# 매일 실행 (systemd timer 또는 cron이 호출)
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m src.pipeline "$@"
