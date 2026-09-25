# S-PAPER · 논문 자동 수집·요약

Next.js 한국어 화면, FastAPI, PostgreSQL, Celery worker/Beat, Redis로 구성한 로컬 실행 서비스입니다. SerpApi Google Scholar를 우선하고 arXiv를 보조 검색원으로 사용합니다. 논문을 사용자 수집 설정에 누적 연결하며, 확보한 초록만 한국어로 요약합니다.

## 실행

Docker Desktop/Engine + Compose가 필요합니다.

```bash
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
# 출력값을 .env의 APP_SECRET_KEY에 입력
# POSTGRES_PASSWORD와 DATABASE_URL의 비밀번호를 같은 강한 값으로 변경
# 아래 API 설정을 입력한 뒤 실행

docker compose up --build -d
# migrate 서비스가 alembic upgrade head를 실행한 후 API/worker/Beat를 시작합니다.
docker compose exec api python -m app.cli create-user --email admin@example.com --admin
# 비밀번호는 터미널에서 두 번 입력합니다. 기본 계정/비밀번호는 없습니다.
```

브라우저: http://localhost:3000

```bash
docker compose logs -f api worker scheduler
docker compose exec api alembic current
docker compose exec api python -m app.cli create-user --email researcher@example.com
docker compose down
```

`down`은 영속 볼륨을 보존합니다. `down -v`는 DB·큐를 삭제하므로 데이터를 버리려는 경우에만 사용하세요. 자동 수집과 지금 수집은 **worker와 scheduler(Beat)가 계속 실행되어야** 합니다. 웹 요청은 DB에 작업을 기록하며 Beat가 최대 약 30초 안에 큐로 전달합니다. 브라우저의 5초 polling은 상태 표시용입니다.

## 외부 설정

| 환경변수 | 역할 |
|---|---|
| `SERPAPI_API_KEY` | 실제 Google Scholar 검색. 빈 값·`your_serpapi_api_key`는 CONFIGURATION_ERROR |
| `CROSSREF_MAILTO` | Crossref 연락처, polite pool 및 식별 가능한 User-Agent |
| `LLM_PROVIDER` | `openai` 또는 `gemini` 중 하나 |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | OpenAI 선택 시 키와 Structured Outputs 지원 모델 |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini 선택 시 키와 JSON Schema 지원 모델 |
| `APP_SECRET_KEY` | 최소 32자 무작위 세션 HMAC 키 |
| `APP_ORIGIN` | 브라우저에서 접근하는 정확한 origin. 기본 `http://localhost:3000` |
| `COOKIE_SECURE` | 로컬 HTTP는 false. HTTPS 배포 시 true |
| `SESSION_HOURS` | 서버 세션 만료, 기본 24시간 |
| `PUBLISHER_ALLOWED_HOSTS` | 허용된 공개 출판사 HTML 메타데이터 도메인. 쉼표 구분, 기본 빈 값 |
| `IF_PROVIDER` | MVP는 `imported`만 지원 |
| `API_INTERNAL_URL` | Next 서버의 API proxy 대상. Compose build 기본 `http://api:8000` |
| `DATABASE_URL`, `POSTGRES_*` | DB 연결과 컨테이너 초기 계정 |
| `REDIS_URL` | Celery 큐, 캐시, 전 worker 요청 제한, 로그인 rate limit |
| `APP_TIMEZONE` | 기본 운영 시간대 안내. 구독은 각 IANA 시간대를 별도 저장 |
| `DEMO_MODE` | true이면 화면에 데모 표시. 운영 provider를 mock으로 바꾸거나 가짜 논문을 자동 생성하지 않음 |
| `RUN_LIVE_API_TESTS` | true + 실제 SerpApi 및 선택 LLM 키/모델이 있을 때만 명시적 live 테스트 허용 |

선택하지 않은 LLM의 키는 필요 없습니다. 모델 이름/가격을 하드코딩하지 않았습니다. 키나 모델이 없으면 논문 저장·조회·CSV는 계속 동작하고 요약은 설정 오류로 표시됩니다. `.env`는 Git/Docker build context에서 제외하며 API 키는 브라우저에 전달하지 않습니다. 배포할 경우 HTTPS와 적절한 DB 접근 제어를 적용하고 APP_ORIGIN을 변경하세요.

## 사용 흐름

1. 로그인 → 수집 설정 → 주제·쉼표 구분 키워드·검색원·목표 수(1–100) 입력.
2. 매일/매주/ N시간/N일, 시각, IANA 시간대를 선택. 기본 Asia/Seoul 매일 09:00, 10편.
3. 고급 설정에서 실제 검색어 미리보기, 직접 재정의, 정렬·연도 범위·겹침 재검색 기간을 조정.
4. 지금 수집 → 실행 이력에서 목표/실제 신규, 중복, source별 상태와 요청·캐시·재시도·토큰 확인.
5. 누적 논문에서 제목/저널/연도/출처/설정/수집일/요약 상태 필터와 상세 열기.
6. 누적 전체 CSV 또는 서버의 전체 필터 결과 CSV 다운로드.

설정 삭제는 보관 처리입니다. 누적 논문과 발견 이력을 보존합니다. 전체 논문/CSV는 여러 설정에 연결된 같은 Paper를 한 번만 보여줍니다. 다른 사용자의 설정·작업·논문·CSV에는 접근할 수 없습니다. 원본 외부 메타데이터는 내부에만 보관합니다.

## 데이터 원칙과 검색 정책

- 필수 7항목: 제목, 저널, 저널 IF 지수, 발표년도, DOI, 초록, AI 논문 요약. 제목이 없는 후보는 사유를 기록하고 건너뜁니다. 나머지 미확보 값은 NULL/빈 셀입니다. snippet은 초록과 별도 저장합니다.
- Scholar publication_info 원문 보존, 유일하게 확인되는 연도만 분리. 저널명이 모호한 문자열은 보수적으로 NULL로 두고 Crossref 또는 허용된 출판사 메타데이터로 보완합니다.
- Crossref 제목 후보는 정규화 제목 유사도 ≥0.94 **및 저자·동일 연도·저널 중 2개 이상의 독립 근거**가 필요합니다. 5단어 미만 제목은 정확한 제목 일치도 요구합니다. 후보 간 유사도 차이 <0.03이면 모호하여 채택하지 않습니다. 명시 DOI는 직접 조회하고 Crossref 404가 나도 DOI를 폐기하지 않습니다.
- 명시 DOI → 동일 source ID(버전 제외 arXiv ID) → 같은 source 내 보수적 제목/저자/연도 비교. 프리프린트와 출판본은 명시 DOI 같은 연결 근거가 있어야 합칩니다. 서로 다른 명시 DOI는 자동 병합하지 않습니다.
- 발표년도는 확인된 저널 게재연도가 있으면 그것을 사용하고, 없으면 arXiv 최초 제출연도를 사용합니다. 원본 제출일·갱신일·버전·journal_ref는 PaperSource에 보존합니다. 연도만 확보한 날짜에 1월 1일을 채우지 않습니다. 주요 값의 출처·확인 시각·매칭 근거는 provenance로 제공합니다.
- 두 활성 검색원의 첫 페이지를 독립적으로 확보한 뒤 Scholar를 우선 처리하고 Scholar 추가 페이지에 우선 예산을 배분합니다. 합산 신규 연결 수가 목표에 도달하면 추가 페이지를 요청하지 않습니다. 이미 확보한 보조 페이지는 동일 논문의 출처/초록 보완에 사용할 수 있습니다.
- 처음은 관련도, 이후는 최근순과 겹치는 기간 재조회입니다. Scholar `scisbd=2`는 **최근 1년간 추가된 논문** 범위이므로 과거 논문 수집은 관련도 + 연도 범위를 선택해야 합니다. arXiv는 제출일 필터를 사용합니다. 영구 offset을 사용하지 않으며 정확한 일 단위 신규 발표 탐색을 보장하지 않습니다.
- arXiv는 Redis의 공유 원자적 슬롯으로 모든 worker/재시도 사이 3.05초 이상 간격, 24시간 캐시를 적용합니다. Crossref는 1초 간격과 24시간 캐시입니다. Scholar 검색 캐시는 1시간입니다.
- Publisher 보완은 명시 allowlist + HTTPS + 공개 IP만 허용하며, 검증 IP로 연결하고 원 호스트 TLS SNI를 유지해 DNS rebinding을 차단합니다. 10초·1MB·최대 3회 redirect, HTML만 읽습니다. PDF 다운로드나 접근 제한 우회는 하지 않습니다.

## IF CSV

관리자 화면에서 권한 있는 검증 데이터를 가져옵니다. Clarivate API 이용 권한이 제공되지 않았으므로 별도 adapter는 구현/활성화하지 않았습니다. 일반 인용 수·SJR·CiteScore로 IF를 대체하지 않습니다.

```csv
journal_name,issn,eissn,metric_year,impact_factor,source_name,source_reference,verified_at
```

UTF-8 CSV, 최대 10MB/50,000행. ISSN 체크섬, 유한한 음수 아닌 IF, 과거/현재 기준 연도, 시간대를 포함한 검증 시각, 저널·연도/ISSN 중복을 검증합니다. 오류가 있으면 행 번호를 반환하고 **전체 import를 취소**합니다. 기존 저널/연도는 조용히 덮어쓰지 않습니다. 이름만 있는 행은 보관할 수 있지만 자동 매칭에는 사용하지 않습니다. ISSN/eISSN이 같은 데이터 중 최신 metric_year를 적용합니다. 실제 IF=0은 정상 값입니다.

## 작업 내구성과 예산

- `subscription_id + scheduled_for` unique, 활성 작업 partial unique index, 구독 row lock으로 수동/정기 중복 회차 방지.
- DB의 queued 행이 outbox 역할을 합니다. broker 등록 뒤 enqueued_at을 기록하므로 중간 장애로 중복 발행되어도 worker의 PostgreSQL advisory lock이 중복 실행을 차단합니다.
- 논문/출처/구독 연결/작업 발견 이력은 한 트랜잭션에 저장합니다. 짧은 저장 구간은 PostgreSQL advisory transaction lock으로 직렬화합니다. 이는 MVP에서 정확성을 우선한 선택이며 높은 처리량에서는 lock 분할을 검토해야 합니다.
- 정상 수신한 페이지의 정규화 후보는 비공개 job checkpoint에 저장합니다. 재시작 시 완료 페이지를 재호출하지 않고 저장된 발견 이력으로 집계를 복원합니다. 장기 running은 MAX_JOB_SECONDS+180초 후 재발행합니다. 시간 예산을 초과한 회차는 이미 저장된 결과를 유지하고 partial로 종료합니다.
- 요약은 abstract hash/provider/model/language/prompt version unique + 논문별 DB advisory lock으로 재사용합니다. 실패 논문만 재시도할 수 있고 queued 재시도도 DB에 영속 저장합니다. 이미 과금됐지만 응답을 저장하기 전 프로세스가 죽은 경우 외부 API 자체의 exactly-once 과금은 보장할 수 없습니다.
- 401/403/미설정/검색량 소진은 재시도하지 않습니다. 일시 429·5xx·network/timeout만 최대 시도, Retry-After, exponential backoff+jitter를 적용합니다. HTTP 200 error body도 검사합니다. HTTP 요청 횟수는 확정 과금 횟수가 아닙니다.
- 기본 한도: source당 5페이지, Scholar HTTP 8회(재시도 포함), HTTP 시도 3회, 요청 timeout 30초, job 총 900초, LLM 100호출/응답 최대 1000토큰. `.env.example`에서 변경합니다. LLM SDK 자동 재시도는 끄고 요약 실패는 개별 기록합니다. 예산 초과 요약은 pending으로 남습니다.
- 정상 0건은 success/no_new_results, 정상 결과 소진은 success/results_exhausted. source/요약 오류 또는 예산 종료는 partial, 유효 진행 없이 모든 source 실패는 failed입니다.

## CSV

정확히 `제목,저널,저널 IF 지수,발표년도,DOI,초록,AI 논문 요약` 7열, UTF-8 BOM, 표준 CSV writer를 사용합니다. 텍스트의 수식 시작 문자 앞에는 작은따옴표를 붙입니다. 쉼표·큰따옴표·줄바꿈을 보존하고, IF는 숫자 또는 빈 셀, 요약은 읽을 수 있는 한국어입니다. 서버 cursor로 안정된 정렬 결과를 100개씩 읽으며 현재 화면 페이지로 제한하지 않습니다. 파일명은 UTC 다운로드 시각 기준 `papers_YYYYMMDD_HHMM.csv`입니다.

## 개발·테스트

Python 3.12–3.14, Node.js 22를 사용합니다. Python 전이 의존성은 `backend/uv.lock`, 웹은 `web/package-lock.json`으로 고정했습니다.

```bash
cd backend
uv sync --frozen
uv run pytest -q
# sqlite fixture 테스트. live/실제 PostgreSQL 테스트는 별도 설정 없으면 skip.
cd ../web
npm ci
npm run build
npm run typecheck
```

실제 PostgreSQL 경쟁 상태 테스트(전용 테스트 DB를 사용):

```bash
docker run -d --name s-paper-test-db -e POSTGRES_USER=app -e POSTGRES_PASSWORD=test-only-password -e POSTGRES_DB=papers -p 127.0.0.1:55432:5432 postgres:16-alpine
docker run -d --name s-paper-test-redis -p 127.0.0.1:56379:6379 redis:7-alpine
cd backend
TEST_POSTGRES_URL=postgresql+psycopg://app:test-only-password@127.0.0.1:55432/papers uv run pytest -q
# tests/test_postgres.py는 매 테스트마다 임의의 전용 schema만 생성·삭제합니다.
```

실제 앱 경로 Playwright(외부 API/LLM만 fixture):

```bash
# 프로젝트 루트, backend/.venv와 웹 build 필요
cd web
PLAYWRIGHT_BROWSERS_PATH=../.tools/playwright npx playwright install chromium
npm run build
cd ..
python3 scripts/run_e2e.py
```

스크립트는 migration → 테스트 계정 생성 → 실제 API/worker/Beat/Next → Playwright → 프로세스 종료를 수행합니다. 기본 로컬 포트 3000/8000/55432/56379가 비어 있어야 합니다. `TEST_POSTGRES_URL`, `TEST_REDIS_URL`로 테스트 DB/Redis를 변경할 수 있습니다. **운영 DB를 지정하지 마세요.** 테스트 전용 `tests.e2e_runtime`에서만 외부 응답을 대체합니다. `app`의 운영 provider는 fixture를 import하지 않습니다. 테스트는 목표 10편 중 fixture의 실제 고유 2편 확보를 확인하고 부족분을 채우지 않습니다. 로그는 `test-results`, 브라우저 결과는 `web/test-results`, HTML 보고서는 `web/playwright-report`입니다.

유료 실제 smoke 검증:

```bash
cd backend
# 실제 PostgreSQL/Redis와 키·모델을 backend 프로세스 환경에 설정한 뒤:
RUN_LIVE_API_TESTS=true uv run pytest tests/test_live.py -v -s
```

`EEG brain age` / `EEG, brain age` / 두 source / 목표 10으로 실제 요청합니다. 명시 플래그와 실제 SerpApi 및 선택 LLM 키·모델이 모두 있어야 실행됩니다. DB에 전용 live 테스트 사용자를 추가하고 실제 결과를 보존합니다. 검색·parsing·Crossref 시도·중복·저장·초록 요약·Dashboard API·CSV를 검사하고 `docs/live-report.json`에 **목표와 실제 개수, 초록·실제 요약 수**를 기록합니다. 초록 0건이면 요약 미검증이며 DOI/IF 결측을 실패로 판단하지 않습니다. 정기 scheduler는 시간 제어 테스트로 검증해 유료 반복 호출을 만들지 않습니다.

## 코드 위치

- `backend/app/models.py`, `migrations/versions`: 관계형 schema / Alembic migration
- `providers/`: 실제 Scholar/arXiv/Crossref/publisher HTTP, 방어적 parser, 공통 gateway
- `collection.py`, `jobs.py`, `tasks.py`: 정규화·중복·저장·checkpoint·outbox·Celery/Beat
- `summaries.py`, `metrics.py`: 실제 OpenAI Responses/Gemini GenAI 호출, 구조 검증, IF import
- `main.py`, `auth.py`, `papers.py`: 사용자별 API/세션/CSV
- `web/app`: 한국어 실연결 UI, `web/e2e`: Playwright
- `docs/verification.md`: 이번 구현에서 실제 수행한 검증과 미실행 항목

## 확인한 공식 문서

2026-09-25/26 확인. 호출 코드는 설치된 공식 SDK signature와 함께 확인했습니다.

- [SerpApi Scholar](https://serpapi.com/google-scholar-api), [Organic Results](https://serpapi.com/google-scholar-organic-results), [Pagination](https://serpapi.com/blog/serpapi-pagination/), [오류 코드](https://serpapi.com/api-status-and-error-codes)
- [arXiv Atom API](https://info.arxiv.org/help/api/user-manual.html)
- [Crossref REST](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Clarivate Journals API](https://developer.clarivate.com/apis/wos-journal) — 라이선스/키 미제공, 연동 완료로 표시하지 않음
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) — 공식 Python SDK Responses.parse
- [Gemini Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output), [공식 Google GenAI Python SDK](https://googleapis.github.io/python-genai/) — 설치 SDK에서 지원하는 models.generate_content + response_json_schema
