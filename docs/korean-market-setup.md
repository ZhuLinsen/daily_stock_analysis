# 한국 주식 시장 설정

이 배포는 KOSPI와 KOSDAQ 분석을 기본값으로 사용합니다. 종목 코드는 Yahoo Finance 접미사를 포함해 입력합니다.

| 시장 | 코드 형식 | 예시 |
| --- | --- | --- |
| KOSPI | `6자리.KS` | `005930.KS` (삼성전자), `000660.KS` (SK하이닉스) |
| KOSDAQ | `6자리.KQ` | `035720.KQ` (카카오), `247540.KQ` (에코프로비엠) |

`.KS`와 `.KQ`를 생략하면 6자리 숫자가 중국 A주 코드로 해석될 수 있으므로, 한국 종목에는 접미사를 항상 붙이세요.

## 권장 환경 변수

```dotenv
STOCK_LIST=005930.KS,000660.KS,035720.KQ,247540.KQ
REPORT_LANGUAGE=ko
MARKET_REVIEW_REGION=kr

# 정기 분석·보고서 생성
GENERATION_BACKEND=codex_cli
GENERATION_FALLBACK_BACKEND=codex_cli

# WebUI의 AI 종목 질의
AGENT_BACKEND=codex_app_server
AGENT_ARCH=single

# KRX 전용 전 종목 스크리너가 준비되기 전까지 비활성화
SCREENING_ENABLED=false
```

`GENERATION_BACKEND=codex_cli`는 보고서 생성에, `AGENT_BACKEND=codex_app_server`는 WebUI의 AI 종목 질의에 사용됩니다. 두 설정은 목적이 다르므로 함께 설정합니다. Codex CLI가 DSA API 프로세스의 `PATH`에서 실행 가능하고 로그인되어 있어야 합니다.

시장 복기는 KOSPI(`^KS11`)와 KOSDAQ(`^KQ11`)을 기준으로 만들며, 통화 표기는 KRW를 사용합니다. 한국 시장의 시장 폭·업종 순위·통합 수급 통계는 현재 데이터 계약에 포함되지 않으므로, 보고서는 제공된 지수와 뉴스에 근거해 이 한계를 명시합니다.

## 저장된 분석이 없을 때의 근거 수집

Codex 에이전트는 저장된 분석 컨텍스트를 참고하되, 이를 현재 매수·매도 판단의 유일한 근거로 사용하지 않습니다. 저장 데이터가 없거나 오래되었거나 불완전한 경우에는 실시간 시세, 최근 일봉, MA·MACD·RSI·거래량 기반 기술 분석을 추가로 조회해 근거를 만듭니다. 이용 가능한 경우 기본 정보와 뉴스도 함께 확인합니다.

Tracker 리서치 사이드카를 함께 운영한다면 아래 값을 DSA의 비공개 `.env`에 설정할 수 있습니다. Tracker와 DSA에 같은 토큰을 두고, 사이드카는 `127.0.0.1`에서만 실행하세요.

```env
TRACKER_RESEARCH_API_URL=http://127.0.0.1:47832
TRACKER_RESEARCH_API_TOKEN=<Tracker와 동일한 32자 이상 토큰>
TRACKER_RESEARCH_API_TIMEOUT_S=8
TRACKER_RESEARCH_PREFLIGHT_ENABLED=true
TRACKER_RESEARCH_REFRESH_WAIT_S=8
```

이 연동은 `.KS`·`.KQ` 종목에 대해 Tracker가 관리하는 시장 데이터, DART, 수급, KRX 상태, 공시·뉴스 요약을 보완 근거로 사용합니다. 캐시가 없거나 오래된 경우에는 **DSA 백엔드만** 제한된 refresh 작업을 Tracker 리서치 사이드카에 요청하고, 결과는 Tracker 운영 DB가 아닌 격리된 리서치 캐시에 저장됩니다. Codex/Agent 도구는 계속 읽기 전용이며, 토큰은 브라우저·LLM 도구·PM2 app 설정 또는 dump에 전달하지 않고 두 서비스의 비공개 `.env`에만 둡니다.

`TRACKER_RESEARCH_PREFLIGHT_ENABLED=false`로 두면 이미 캐시된 데이터만 읽습니다. `TRACKER_RESEARCH_REFRESH_WAIT_S`는 이번 분석에서 새 캐시를 기다리는 최대 시간(0~30초)이며, 제한 시간을 넘거나 사이드카가 실패해도 실시간 시세·일봉·기술 분석은 계속 실행됩니다. 이때 보고서는 “뉴스 채널 미설정”이 아니라 이번 실행에서 뉴스 데이터를 확보하지 못했다고 표시합니다.

## WebUI 외부 접속

```dotenv
WEBUI_HOST=0.0.0.0
WEBUI_PORT=8000
WEBUI_AUTO_BUILD=false
```

`0.0.0.0` 바인딩은 같은 네트워크의 다른 장치에서도 접근할 수 있게 합니다. 외부에 노출하는 경우 `ADMIN_AUTH_ENABLED=true`를 설정하고, 방화벽 또는 TLS 역방향 프록시로 접근 범위를 제한하세요.

프런트엔드 코드를 변경한 뒤에는 다음을 실행한 후 API 프로세스를 재시작합니다.

```bash
cd apps/dsa-web
npm install
npm run build
```

PM2를 사용 중이면 저장소 루트에서 `pm2 restart dsa-api`로 반영할 수 있습니다.
