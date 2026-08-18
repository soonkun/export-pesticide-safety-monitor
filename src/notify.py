"""알림 발송: 이메일(SMTP) + 카카오 '나에게 보내기'(메모 API).

- 이메일: 수신자 목록(SMTP_TO)에게 HTML 보고서 발송.
- 카카오: 본인 카카오톡으로 요약 텍스트 발송(refresh token으로 access token 갱신).
설정이 없으면 해당 채널은 건너뛴다(에러 아님). 채널(친구톡/알림톡)은 사업자 필요 → 미구현.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from . import config
from .http import HTTP_VERIFY

REPORT_URL = "https://www.rda.go.kr"   # 카카오 텍스트 템플릿 링크(공개 URL 필요)


def send_email(subject: str, html_body: str) -> tuple[bool, str]:
    if not (config.SMTP_HOST and config.SMTP_TO):
        return False, "SMTP 미설정 — 건너뜀"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(config.SMTP_TO)
    msg.attach(MIMEText("HTML 보고서입니다. HTML을 지원하는 클라이언트에서 확인하세요.", "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASS)
            smtp.sendmail(config.SMTP_FROM, config.SMTP_TO, msg.as_string())
        return True, f"이메일 발송 완료 → {', '.join(config.SMTP_TO)}"
    except Exception as e:
        return False, f"이메일 실패: {e}"


def _kakao_access_token() -> str | None:
    r = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": config.KAKAO_REST_KEY,
        "refresh_token": config.KAKAO_REFRESH_TOKEN,
    }, timeout=30, verify=HTTP_VERIFY)
    r.raise_for_status()
    return r.json().get("access_token")


def send_kakao(text: str) -> tuple[bool, str]:
    if not (config.KAKAO_REST_KEY and config.KAKAO_REFRESH_TOKEN):
        return False, "카카오 미설정 — 건너뜀"
    try:
        token = _kakao_access_token()
        import json as _json
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": REPORT_URL, "mobile_web_url": REPORT_URL},
            "button_title": "대시보드",
        }
        r = requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": _json.dumps(template, ensure_ascii=False)},
            timeout=30, verify=HTTP_VERIFY)
        r.raise_for_status()
        return True, "카카오 '나에게 보내기' 발송 완료"
    except Exception as e:
        return False, f"카카오 실패: {e}"


def dispatch(report: dict) -> list[tuple[str, bool, str]]:
    subject = f"[{config.REPORT_TITLE}] {report['summary']['date']}"
    out = []
    ok, msg = send_email(subject, report["html"])
    out.append(("email", ok, msg))
    ok, msg = send_kakao(report["text"])
    out.append(("kakao", ok, msg))
    return out
