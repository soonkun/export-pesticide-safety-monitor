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
| RDA odcloud | 국내 지침(한국+캐시 외국 MRL) — **전량 13개국 × 85조합** | REST API | RDA_SERVICE_KEY | ✅ |
| EU DG SANTE Datalake | EU 현행 MRL·유효성분 | REST API (무키) | — | ✅ |
| Codex (FAO/WHO) | 국제 참조 MRL | 내부 JSON 엔드포인트 | — | ✅ |
| WTO ePing | SPS 변경예고(Early warning) | REST API | WTO_API_KEY | ✅ |
| Japan (FFCR) | 일본 현행 MRL(포지티브리스트) | 폼 세션 + HTML 표 | — | ✅ |
| USA (eCFR) | 미국 현행 MRL — 40 CFR Part 180 | REST API (XML, 무키) | — | ✅ |
| Taiwan (TFDA) | 대만 현행 MRL — 農藥殘留容許量標準 | 정부 오픈데이터 API (무키) | — | ✅ |
| Hong Kong (CFS) | 홍콩 현행 MRL — Cap. 132CM Schedule 1 | 폼 세션 조회 | — | ✅ |
| Canada (PMRA) | 캐나다 현행 MRL | 공개 추출 CSV (무키) | — | ✅ |
| China (CFSA) | 중국 GB 2763 — **개정 감시만** | 표준 검색 API | — | 👁 감시 |
| Australia (FRL) | 호주 Schedule 20 — **개정 감시만** | 연방입법등록부 OData | — | 👁 감시 |
| Singapore (SSO) | 싱가폴 Food Reg 제9부칙 — **개정 감시만** | Statutes Online | — | 👁 감시 |
| Indonesia (SNI 7313) | 인니 현행 MRL | 원문 사이트가 해외 접근 차단 | — | ⏸ 보류 |

### 대조 범위 (중요)

지침은 **13개국 × 85개 (국가×작목) 조합**을 배포한다. 이 중 현행 기준과 실제로 대조 가능한 것은
**일본 18작목 + EU 1작목 = 19조합**이다. 나머지는 "이상 없음"이 아니라 **확인하지 못한 것**이며,
대시보드의 `📐 대조 범위` 섹션에 국가별·사유별로 건수를 그대로 표시한다.

| 사유 | 조합 | 비고 |
|---|---|---|
| 대조함 | 45 | 일본 18(FFCR) · 대만 13(TFDA) · 홍콩 6(CFS) · 미국 4(eCFR) · 캐나다 3(PMRA) · EU 1 |
| **개정 감시** | 7 | 중국·호주·싱가폴 — 값은 못 읽지만 **현행판이 바뀌면 알림** |
| 현행 기준 소스 미연결 | 5 | 태국·뉴질랜드·러시아 — [조사 기록](docs/DATA_SOURCES.md) 참고 |
| 보류 | 9 | 인도네시아 — 원문 사이트가 해외 접근 차단, 담당 연구사 확인 후 재개 |
| 작목 매핑 확인 필요 | 18 | 수입국 식품분류 대응 항목을 담당자가 확정해야 함(§12) |

#### 인도네시아는 보류 상태

표준 게시처(`bsn.go.id`)와 `brmp.pertanian.go.id` 가 **해외 접근을 차단**해 수집 자체가 불가능하다
(2026-08-20 실측: 타임아웃 / Cloudflare 403). 담당 연구사가 실제로 참고하는 사이트를 확인한 뒤 재개한다.
`config.SOURCES["Indonesia"]["deferred"]` 를 지우면 수집이 다시 시도된다.
수집 경로가 끝내 없으면 `data/manual/indonesia_mrl.csv` 수동 입력으로도 받을 수 있게 해 두었다
(`data/manual/indonesia_mrl.csv.example` 참고).

### 세 층으로 본다 — 값 대조 · 개정 감시 · WTO 예고

| 층 | 시점 | 알려주는 것 | 한계 |
|---|---|---|---|
| **값 대조** | 매 수집 | "지침 2 → 현행 1" 정확한 숫자 | 값을 읽을 수 있는 나라만 |
| **개정 감시** | 공표/시행 시점 | "그 기준 문서가 실제로 바뀜" | 어떤 값이 바뀌었는지는 모름 |
| **WTO ePing** | 시행 전(보통 60일) | "바뀔 예정" | 초안 · 성분명이 첨부에만 있음 · 긴급조치는 사후 통보 |

일본 스피네토람 4건은 **WTO 가 아니라 값 대조**에서 나왔다(일본 통보문 43건 중 해당 0건).
반대로 호주 플루디옥소닐 의견마감 D-4 는 **WTO 첨부 스캔**으로만 잡힌다(호주는 값 대조 불가).
세 층이 서로를 대체하지 않는다.

### 값을 못 읽는 기준은 '개정 감시'로 다룬다

문서를 한 번 내려받는 것은 스냅샷이지 모니터링이 아니다. 중국 GB 2763 은 스캔 PDF 라 값을
읽을 수 없고, 호주 Schedule 20 은 문서 다운로드 경로를 못 찾았다. 그렇다고 비워두면 정작
**기준이 개정된 순간**을 놓친다.

두 나라 모두 **현행판이 무엇이고 언제 바뀌었는지는 공개 API 로 매일 확인된다.**

| 국가 | 감시 지표 | 현재 값 |
|---|---|---|
| 중국 | CFSA 표준검색 API 의 GB 2763 판 목록 | GB 2763-2021 (시행 2021-09-03) + GB 2763.1-2022 |
| 싱가폴 | SSO 의 Food Reg 30조 판 번호·시행일 | reg30 4/4판 · 시행 2026-01-30 |
| 호주 | 연방입법등록부 OData 의 Schedule 20 현행 컴필레이션 | compilation 91 (F2026C00754, 시행 2026-07-16) |

판 번호·발표일·시행일이 바뀌거나 **새 판이 등장하면** `STANDARD_CHANGED` 알림이 뜬다
(`standard_watch` 테이블). 담당자에게 필요한 것은 10,092개 숫자가 아니라
**언제 원문을 들여다봐야 하는가** 이다. 값 대조가 불가하다는 사실은 커버리지에 그대로 남는다.

### 남은 일 (TODO)

1. **작목 매핑 확정 — 담당자 판단 필요.** 아래 작목은 수입국 식품분류에서 어느 항목에 대응하는지
   근거가 없어 비워 두었다. 근거 없이 유사 항목(`Other ~` 그룹 등)에 붙이면 **틀린 기준으로 대조**하게 된다.
   `masters.PENDING_COMMODITIES` 에 사유와 함께 있고 대시보드 `📐 대조 범위`에도 표시된다.

   | 작목 | 확인할 것 |
   |---|---|
   | 감귤 | 일본 `UNSHU orange, pulp` / `Other citrus fruits` 중 어느 것인지 · EU product_id 미확인 |
   | 고추 | FFCR 에 `Chili pepper, dried` 만 있음 — 신선 고추 대응 항목 |
   | 대추·들깻잎·유자·인삼 | FFCR 개별 항목 없음 — `Other ~` 그룹 적용 여부 |

2. **인도네시아 참고 사이트 확인** — 담당 연구사에게 실제 참고처를 확인한 뒤 재개(지침 3,171행 · 9작목).
3. **미연결 국가 수집기 추가** — 지침 행수 기준 중국(1,303) · 캐나다(671) · 호주(441) 순.
   중국 GB 2763 은 유료 표준이라 인니와 같은 벽일 수 있다. 캐나다(PMRA)·호주(FSANZ)는 공개 자료가 있다.
4. **EU 변경 시점** — EU Datalake API 가 MRL 레코드에 날짜를 주지 않아 `변경 감지`는 수집 이후부터 쌓인다.

자세한 근거: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), [docs/FIELD_MAPPING.md](docs/FIELD_MAPPING.md),
[docs/MONITORING.md](docs/MONITORING.md), [docs/STEP4_VALIDATION.md](docs/STEP4_VALIDATION.md).

## 빠른 시작 (Linux)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # 키 채우기 (RDA_SERVICE_KEY, WTO_API_KEY, SMTP_*, KAKAO_*, OPS_PASS)
python test_monitor.py      # 핵심 로직 자체점검 (네트워크 불필요)

.venv/bin/python -m src.pipeline             # 수집→비교→보고서→알림
.venv/bin/python -m src.pipeline --no-notify # 알림 없이
.venv/bin/python -m src.pipeline --only EU   # 소스 1개만 점검(국내망 진단)
.venv/bin/python -m src.serve                # http://127.0.0.1:8000
```

생성물: `out/dashboard.html`(대시보드), `out/report_YYYY-MM-DD.html`, `data/pesticide.sqlite`(DB).

## 설치 (매일 09:00 자동실행 + 관제서버 + 공개터널)

```bash
sudo scripts/install-systemd.sh
```

등록되는 유닛 3개:

| unit | 역할 |
|---|---|
| `pesticide-monitor.timer` / `.service` | 매일 09:00 파이프라인 (`Persistent=true` — 꺼져 있던 날도 부팅 후 보충 실행) |
| `pesticide-api.service` | 관제/대시보드 서버 (127.0.0.1:8000) |
| `pesticide-tunnel.service` | Cloudflare Tunnel — 위 서버를 공개 URL로 노출 |

```bash
sudo systemctl start pesticide-monitor.service      # 즉시 1회 실행
systemctl list-timers pesticide-monitor.timer       # 다음 실행 시각
journalctl -u pesticide-monitor -n 100              # 실행 로그
```

## 관제·테스트 콘솔

`GET /ops` — 브라우저에서 수동 실행 / 소스별 점검 / 실행로그 실시간 확인.

- **전체 실행** : 수집→비교→보고서 (알림 발송 여부 선택)
- **소스별 점검** : RDA·EU·Codex·Japan·WTO 개별 수집 테스트 → 상태/최신성/records/응답시간 즉시 확인
- **📨 테스트 발송** : 카톡/메일로 테스트 메시지 1건 발송 → 채널이 실제로 도착하는지 즉시 확인
- 실행은 서브프로세스로 돌고 결과는 `collection_runs`·`source_health`에 그대로 기록된다(수동 실행도 감사 대상).

**인증**: 전 경로 HTTP Basic (`.env`의 `OPS_USER`/`OPS_PASS`).
`OPS_PASS`가 비어 있으면 서버가 기동하지 않는다 — 공개 URL에 인증 없이 뜨는 사고를 막기 위함.

## Cloudflare 배포

관제 서버는 **국내망에서 RDA odcloud를 호출해야 하므로** Cloudflare 위(Workers/Pages)에서 돌릴 수 없다.
서버는 국내망 리눅스 장비에 두고, Cloudflare Tunnel로 공개 URL만 붙인다(인바운드 포트 개방 불필요).

```bash
# 1) cloudflared 설치
curl -sL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared

# 2) 고정 도메인 (Cloudflare 계정 필요)
#    대시보드 > Zero Trust > Networks > Tunnels 에서 터널 생성 후 토큰을 .env 에:
#    CLOUDFLARE_TUNNEL_TOKEN=eyJ...
#    → install-systemd.sh 가 이 토큰으로 pesticide-tunnel.service 를 구성한다.

# 3) 토큰이 없으면 임시 URL(*.trycloudflare.com)로 뜬다. 재시작마다 주소가 바뀌므로 테스트용.
journalctl -u pesticide-tunnel -n 30 | grep trycloudflare
```

## Cloudflare Access (비밀번호 없이 로그인)

Basic 인증 대신 업무 이메일 6자리 코드/SSO로 로그인. **계정에 등록된 도메인이 필요**하며
임시 `trycloudflare.com` 주소에는 걸 수 없다.

**비용**: Access·Tunnel 은 Zero Trust Free 플랜(50인)에 포함되어 요금은 0원. 단
(a) 무료 플랜이어도 온보딩 시 **결제수단 등록을 요구**하고(청구는 없음),
(b) **도메인 보유 비용**은 별도(연 1~2만원대). 이 둘이 부담이면 아래 "대안" 참고.

대시보드 순서:

1. **Networks > Tunnels > Create a tunnel** → `Cloudflared` 선택 → 이름 `pesticide-monitor`
2. 토큰(`eyJ...`)을 복사해 `.env` 에 `CLOUDFLARE_TUNNEL_TOKEN=eyJ...`
3. 같은 화면 **Public Hostname** 탭 → 예: `monitor` + `보유도메인.kr`,
   Service = `HTTP` + `127.0.0.1:8000` (DNS 레코드는 자동 생성됨)
4. **Access > Applications > Add an application** → `Self-hosted`
   → Application domain = 3에서 만든 호스트명
5. **Policy**: Action `Allow`, Include = `Emails`(담당자 이메일 목록) 또는
   `Emails ending in` `@korea.kr` 같은 도메인 조건
6. 서버에 반영:
   ```bash
   sudo scripts/install-systemd.sh    # 토큰 감지해서 고정 터널로 구성
   ```

이후 접속하면 Cloudflare 로그인 화면 → 이메일 코드 입력 → 콘솔.
(Access 를 켠 뒤에도 origin Basic 인증은 그대로 남는다. 팝업이 한 번 더 뜨는 게 거슬리면
origin 은 127.0.0.1 바인딩이라 cloudflared 만 접근 가능하므로 Basic 을 끄는 선택지가 있다.)

### 대안 (카드 등록·도메인 없이)

| 방식 | 비용 | 인증 |
|---|---|---|
| 터널 내리고 내부망에서만 접속 | 0 | 없음(망 자체가 경계) — `http://서버IP:8000`, `.env` 에 `HOST=0.0.0.0` |
| 터널 유지 + 강한 비밀번호 | 0 | Basic. 브라우저 비밀번호 관리자에 저장하면 실제 입력은 최초 1회뿐 |
| Cloudflare Access | 0 (카드 등록·도메인 필요) | 이메일 6자리 코드 / SSO |

공개 URL 이 꼭 필요한 게 아니라면 첫 번째가 가장 단순하고 안전하다.

## API (§33)

`GET /status · /sources · /sources/{name}/health · /changes · /comparisons · /alerts · /history`
`GET /ops · GET /ops/job · POST /ops/run · POST /ops/test/{source}`

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
- `db.ffcr.or.jp` (Japan — 일본식품화학연구진흥재단 잔류농약기준 DB)
  · 후생노동성 원문 DB `jpn-pesticides-database.go.jp` 는 해외 IP/봇을 403 차단해 자동 수집이 불가하다.
  · FFCR 자료는 고시(告示 370호) 편집본이며 무단 전재를 금지하므로, 수집값은 내부 검토용으로만 쓰고
    지침 개정 시에는 관보/후생노동성 고시 원문으로 재확인한다.

## 보안

- 인증키는 `.env`에만 두며 커밋되지 않습니다(`.gitignore`). `.env.example`로 형식만 공유.
- `.env`는 **0600(소유자 전용)** 이어야 합니다 — 공유 스토리지에 644로 두면 동일 그룹 사용자가
  RDA/WTO 키·SMTP 비밀번호·관제 비밀번호를 전부 읽습니다. `install-systemd.sh`가 강제합니다.
  ```bash
  chmod 600 .env && stat -c '%a %U %n' .env   # 600 이어야 정상
  ```
- 관제 콘솔은 공개 URL로 뜨므로 HTTP Basic 인증 필수. `OPS_PASS` 미설정 시 서버가 기동을 거부합니다.
- LLM은 규정 일치 여부를 확정하지 않습니다(§5). 구조화 값 비교는 전부 deterministic code.
