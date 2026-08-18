# 수출농산물 농약 안전사용기준 상시점검·변경탐지 서비스 (PoC)

농촌진흥청 「수출농산물 농약안전사용지침」이 **현재 배포 중인 해외기준**과, **실제 수입국이 지금 운영하는 공식 기준**을
지속 비교하여, 담당자에게 **의사결정**을 제공하는 시스템.

> 목적은 "국내 MRL vs 해외 MRL"의 단순 비교가 아니라 —
> **"지침이 배포 중인 해외기준이 현행과 달라졌으니 지침을 갱신해야 한다"**,
> **"이 성분/제품은 이제 수출용으로 쓸 수 없게 바뀌었다"**,
> **"eping을 보니 N개월 후 기준이 바뀌니 대비해야 한다"** 같은 판단을 만들어 주는 것.

핵심 철학: **"변경 없음"이 아니라 "최신 정보를 정상 확인했고 그 결과 변경 없음"을 증명**한다.
최신성이 확인되지 않으면 "이상 없음"으로 표시하지 않는다.

## 데이터 소스 (STEP1~4에서 실측 확정)

| Source | 역할 | 접근 | 키 | 상태 |
|---|---|---|---|---|
| RDA odcloud | 국내 지침(한국+캐시 외국 MRL) | REST API `cond[..::EQ/LIKE]` | RDA_SERVICE_KEY | ✅ |
| EU DG SANTE Datalake | EU 현행 MRL·유효성분 | REST API (무키) | — | ✅ |
| Codex (FAO/WHO) | 국제 참조 MRL | 내부 JSON 엔드포인트 | — | ✅ |
| WTO ePing | SPS 변경예고(Early warning) | REST API | WTO_API_KEY | ✅ |
| Japan (CAA/MHLW) | 일본 현행 MRL | 폼 크롤링 | — | ⚠️ 국내망 검증 필요(해외IP 403) |

자세한 근거: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/FIELD_MAPPING.md](docs/FIELD_MAPPING.md),
[docs/MONITORING.md](docs/MONITORING.md), [docs/STEP4_VALIDATION.md](docs/STEP4_VALIDATION.md).

## 빠른 시작

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # 키 채우기 (RDA_SERVICE_KEY, WTO_API_KEY, SMTP_*, KAKAO_*)

.venv\Scripts\python -m src.pipeline            # 수집→비교→보고서→알림
.venv\Scripts\python -m src.pipeline --no-notify # 알림 없이
.venv\Scripts\python -m src.serve               # http://127.0.0.1:8000 대시보드/API
```

생성물: `out/dashboard.html`(대시보드), `out/report_YYYY-MM-DD.html`, `data/pesticide.sqlite`(DB).

## 매일 자동 실행 (09:00)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
```

## API (§33)

`GET /status · /sources · /sources/{name}/health · /changes · /comparisons · /alerts · /history`

## 아키텍처

```
src/
  collectors/   소스별 독립 수집기 (rda, eu, codex, japan, wto_eping) + base(재시도·헬스·freshness)
  normalize.py  MRL 정규화 + RDA 혼합제 파이프-성분 정렬
  masters.py    pesticide/commodity master (식별자 기반 매핑)
  compare.py    deterministic 비교 (LLM 미사용)
  report.py     운영보고서 + 대시보드
  notify.py     이메일 + 카카오 '나에게 보내기'
  api.py        FastAPI 상태/조회 API + 대시보드
  pipeline.py   전체 오케스트레이션 (매일 실행 진입점)
```

## 네트워크 요구사항 (공무원 외부망 등 제한 환경)

해외 소스는 아래 도메인 접근이 필요합니다. 차단 시 해당 소스는 `SOURCE_UNAVAILABLE`로 표시되고,
그 소스 관련 비교는 **"최신성 확인 필요"**로 처리됩니다(캐시값을 최신처럼 쓰지 않음 — Fail-safe).

- `api.odcloud.kr` (RDA, 국내)
- `api.datalake.sante.service.ec.europa.eu` (EU)
- `www.fao.org` (Codex)
- `api.wto.org` (WTO ePing)
- `jpn-pesticides-database.go.jp` (Japan)

## 보안

- 인증키는 `.env`에만 두며 커밋되지 않습니다(`.gitignore`). `.env.example`로 형식만 공유.
- LLM은 규정 일치 여부를 확정하지 않습니다(§5). 구조화 값 비교는 전부 deterministic code.
