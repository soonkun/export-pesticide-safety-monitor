#!/usr/bin/env bash
# 리눅스 설치: 매일 09:00 파이프라인 타이머 + 관제 API 서비스 + Cloudflare Tunnel
# 실행: sudo scripts/install-systemd.sh
set -euo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"
ENV_FILE="$APP/.env"

# .env 에는 RDA/WTO 키·SMTP 비밀번호·관제 비밀번호가 들어간다.
# 공유 경로에 644 로 놓이면 동일 그룹 사용자가 전부 읽으므로 소유자 전용으로 고정한다.
touch "$ENV_FILE"
chown "$USER_NAME" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# OPS_PASS 없으면 생성 (관제 페이지 Basic 인증). 비밀번호 없이는 API가 뜨지 않는다.
if ! grep -q '^OPS_PASS=.\+' "$ENV_FILE" 2>/dev/null; then
  PASS="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  sed -i '/^OPS_PASS=/d' "$ENV_FILE" 2>/dev/null || true
  printf '\nOPS_USER=admin\nOPS_PASS=%s\n' "$PASS" >> "$ENV_FILE"
  echo "생성된 관제 비밀번호: admin / $PASS   (.env 에 저장됨, 0600)"
fi

write() { cat > "/etc/systemd/system/$1"; chmod 644 "/etc/systemd/system/$1"; echo "  + /etc/systemd/system/$1"; }

write pesticide-monitor.service <<UNIT
[Unit]
Description=수출농산물 농약기준 모니터링 - 일일 수집/비교/보고/알림
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$APP
ExecStart=$APP/scripts/run_daily.sh
UNIT

write pesticide-monitor.timer <<UNIT
[Unit]
Description=매일 09:00 모니터링 실행
[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
[Install]
WantedBy=timers.target
UNIT

write pesticide-api.service <<UNIT
[Unit]
Description=수출농산물 농약기준 모니터링 - 관제/API 서버
After=network-online.target
[Service]
User=$USER_NAME
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python -m src.serve
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

# Cloudflare Tunnel: .env 의 CLOUDFLARE_TUNNEL_TOKEN 이 있으면 고정 도메인, 없으면 임시 URL
if grep -q '^CLOUDFLARE_TUNNEL_TOKEN=.\+' "$ENV_FILE" 2>/dev/null; then
  TUNNEL_CMD="/usr/local/bin/cloudflared tunnel --no-autoupdate run --token \${CLOUDFLARE_TUNNEL_TOKEN}"
else
  TUNNEL_CMD="/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000"
  echo "  ! CLOUDFLARE_TUNNEL_TOKEN 미설정 - 임시 trycloudflare.com URL 사용 (재시작 시 주소 변경)"
fi
write pesticide-tunnel.service <<UNIT
[Unit]
Description=Cloudflare Tunnel - 관제 페이지 공개
After=pesticide-api.service
[Service]
EnvironmentFile=-$ENV_FILE
ExecStart=$TUNNEL_CMD
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now pesticide-monitor.timer pesticide-api.service pesticide-tunnel.service
echo
systemctl list-timers pesticide-monitor.timer --no-pager || true
echo "즉시 1회 실행: sudo systemctl start pesticide-monitor.service"
echo "공개 URL 확인: journalctl -u pesticide-tunnel -n 30 | grep trycloudflare"
