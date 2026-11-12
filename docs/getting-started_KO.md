# 한국어 시작 가이드

Daily Stock Analysis는 관심 종목의 시세·기술 지표·뉴스를 모아 AI 분석 리포트를 만들고 알림으로 전송하는 프로젝트입니다. 중국 A주, 홍콩, 미국, 일본, 한국, 대만 종목을 지원하며, 시장별로 제공되는 데이터 범위가 다릅니다.

이 문서는 처음 실행하고 한국어 리포트를 받기 위한 안내입니다. 전체 설정을 번역한 문서는 아니며, 추가 설명은 [한국어 문서 안내](INDEX_KO.md)에서 찾아볼 수 있습니다.

## 1. 실행 방식 선택

| 방식 | 필요한 환경 | 자세한 안내 |
| --- | --- | --- |
| GitHub Actions | GitHub 계정, 모델 API 키, 알림 채널 | 아래의 Actions 설정 |
| 로컬 실행 | Python 3.10 이상, Git, 모델 API 키 | 아래의 로컬 설정 |
| Web UI | 로컬 실행 환경, 프런트엔드를 빌드할 Node.js·npm | 아래의 Web UI 안내 |
| Docker·서버 | Docker 또는 서버 운영 환경 | [배포 가이드 — 영어](DEPLOY_EN.md) |
| 데스크톱 앱 | 지원하는 Windows·macOS 환경 | [설치·설정 안내 — 중국어](beginner-client-setup.md), [패키지 안내 — 중국어](desktop-package.md) |

모델 API와 일부 데이터·검색 제공자는 별도 이용료나 할당량이 있을 수 있습니다. 실행 환경과 데이터 제공자의 제약은 각 상세 문서를 확인하세요.

## 2. 한국어 리포트와 종목 코드

로컬 실행에서는 `.env`에 다음 값을 설정합니다.

```dotenv
REPORT_LANGUAGE=ko
STOCK_LIST=005930.KS,000660.KS,AAPL
```

- `REPORT_LANGUAGE=ko`는 리포트와 기본 AI 대화 응답의 언어를 지정합니다. 요청에 별도 언어를 지정하면 요청값이 우선합니다.
- Web UI의 메뉴·설정 화면 언어는 별도입니다. 현재 중국어와 영어만 지원하므로, 이 값을 바꿔도 Web UI 전체가 한국어로 바뀌지는 않습니다.
- 한국 KOSPI 종목은 `005930.KS`처럼 `.KS`, KOSDAQ 종목은 `247540.KQ`처럼 `.KQ`를 붙입니다. 시장 혼동을 피하려면 숫자만 입력하지 말고 거래소 접미사를 포함하세요.
- 다른 시장 예: 중국 A주 `600519`, 홍콩 `hk00700`, 미국 `AAPL`, 일본 `7203.T`, 대만 `2330.TW`.
- 한국 종목은 주로 Yahoo Finance 일봉·기본 시세와 제한적인 기본 재무 데이터를 사용합니다. 중국 A주 전용 수급·용호방·섹터 데이터는 지원하지 않습니다. 시세 지연이나 누락이 있을 수 있으며, 자동 완성 목록이 한국 시장 전체를 포함하지는 않습니다.

한국 시장 전체 리뷰가 필요하면 `MARKET_REVIEW_REGION=kr`를 설정합니다. 이 설정은 시장 리뷰의 대상이며, 개별 종목 분석 목록은 `STOCK_LIST`로 따로 지정합니다. 시장 리뷰의 한국 시장 데이터는 주요 지수와 뉴스 중심이며 전체 종목의 상승·하락 수나 섹터 순위를 제공하지 않습니다. [시장별 지원 범위 — 중국어](market-support.md)에서 경계를 확인할 수 있습니다.

## 3. GitHub Actions로 실행

1. 원본 저장소를 자신의 GitHub 계정으로 Fork합니다.
2. 포크의 `Settings → Secrets and variables → Actions`에서 모델과 알림 설정을 추가합니다.
3. `Actions` 탭에서 워크플로 실행을 활성화합니다.
4. `每日股票分析` 워크플로를 선택하고 `Run workflow`로 실행합니다. 파일은 [00-daily-analysis.yml](../.github/workflows/00-daily-analysis.yml)입니다.

### 모델·알림 Secrets

아래 모델 키 중 사용할 제공자 하나를 선택합니다. 여러 제공자·로컬 모델·명시적 모델 선택은 [LLM 설정 가이드 — 영어](LLM_CONFIG_GUIDE_EN.md)를 참고하세요.

| Secret | 용도 |
| --- | --- |
| `GEMINI_API_KEY` | Gemini 모델 API 키 |
| `ANTHROPIC_API_KEY` | Claude 모델 API 키 |
| `OPENAI_API_KEY` | OpenAI 또는 OpenAI 호환 제공자의 API 키 |
| `OPENAI_BASE_URL`, `OPENAI_MODEL` | OpenAI 호환 서비스를 사용할 때 제공자에 맞는 주소와 모델 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram으로 받는 경우 두 항목 모두 설정 |

Telegram 외에도 Discord·Slack·이메일·기업용 메신저를 지원합니다. 실제로 사용할 채널의 설정은 [알림 설정 — 영어](full-guide_EN.md#notification-channel-configuration)에서 확인하세요.

뉴스 검색이 필요하면 `SERPAPI_API_KEYS` 또는 `TAVILY_API_KEYS` 등의 Secret도 추가합니다. 검색 설정이 없으면 뉴스 기반 분석에 제한이 있습니다. 지원 제공자와 우선순위는 [검색 설정 — 영어](full-guide_EN.md#search-service-configuration)를 참고하세요.

### 일반 Variables

`Variables → New repository variable`에서 다음 값을 추가합니다.

| Variable | 예시 | 설명 |
| --- | --- | --- |
| `REPORT_LANGUAGE` | `ko` | 한국어 리포트 |
| `STOCK_LIST` | `005930.KS,000660.KS,AAPL` | 쉼표로 구분한 관심 종목 |
| `MARKET_REVIEW_REGION` | `kr` | 한국 시장 리뷰가 필요한 경우 |

현재 워크플로는 위 항목에 대해 Repository Variable을 우선하고 같은 이름의 Secret을 대체값으로 사용합니다. API 키·토큰은 Secrets에 저장하세요.

기본 예약 실행은 월요일부터 금요일까지 UTC 10:00, 즉 **한국 시간 19:00**입니다. 실제 분석 대상은 거래일 검사와 실행 모드에 따라 달라집니다. 한국 시장 마감 시각에 자동으로 맞춰지는 설정은 아닙니다. 실행 시간을 바꾸려면 포크의 워크플로 `schedule`을 수정합니다.

실행 후 `Actions`의 실행 기록에서 실패 단계와 로그를 확인하고, 설정한 알림 채널에서 리포트를 확인합니다.

## 4. 로컬에서 실행

아래 명령은 macOS·Linux의 셸 기준입니다. Windows에서는 사용하는 셸에 맞게 가상환경 활성화와 파일 복사 명령을 바꿉니다.

```bash
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열고 사용할 모델 제공자의 API 키, `STOCK_LIST`, `REPORT_LANGUAGE=ko`를 설정합니다. Telegram 알림을 사용하면 앞서 설명한 두 Telegram 설정값도 입력합니다. 모델 이름·주소는 자신의 제공자에서 사용 가능한 값으로 설정하며, 예시는 [.env.example](../.env.example)과 [LLM 설정 가이드 — 영어](LLM_CONFIG_GUIDE_EN.md)를 따릅니다.

```bash
# 설정한 관심 종목 분석
python main.py

# 이번 실행에 사용할 종목 직접 지정
python main.py --stocks 005930.KS,000660.KS,AAPL

# 시장 리뷰만 실행 (.env의 MARKET_REVIEW_REGION 사용)
python main.py --market-review

# 개별 종목 AI 분석과 시장 리뷰를 생략하고 데이터 수집 흐름 확인
python main.py --dry-run --no-market-review
```

`--dry-run`만 사용하면 개별 종목의 AI 분석만 생략하며, 활성화된 시장 리뷰는 계속 실행되어 모델 API를 호출하고 리포트를 저장·전송할 수 있습니다. 위 데이터 수집 확인 예시에서는 `--no-market-review`를 함께 지정해 시장 리뷰도 끕니다. 이 명령은 AI 모델 연결이나 알림 전송 성공을 검증하지 않습니다.

운영체제에 `python3` 명령이 없다면 설치한 Python 실행 파일을 사용하세요. 가상환경을 활성화한 뒤에는 해당 환경의 `python`과 `pip`가 사용되는지 확인합니다.

## 5. Web UI 사용

`.env` 설정 후 다음 명령으로 분석을 자동 시작하지 않고 서비스를 실행할 수 있습니다.

```bash
python main.py --serve-only
```

Web UI 프런트엔드는 기본적으로 시작할 때 빌드됩니다. 소스에서 빌드하려면 [프런트엔드 package.json](../apps/dsa-web/package.json)의 Node.js·npm 요구 버전을 충족해야 합니다. Node.js는 `>=20.19.0 <27`, npm은 `>=10`입니다. 자동 빌드를 끄는 경우에는 빌드 산출물을 먼저 준비해야 합니다. 자세한 동작은 [전체 가이드 — 영어](full-guide_EN.md)를 참고하세요.

기본 접속 주소는 `http://127.0.0.1:8000`이며, 실제 주소와 포트는 `WEBUI_HOST`·`WEBUI_PORT` 또는 실행 인수에 따라 달라집니다. 화면 언어는 리포트 언어와 별도로 선택합니다. 서버·외부 접속과 인증 설정은 [Web UI 배포 안내 — 중국어](deploy-webui-cloud.md)를 따릅니다.

## 6. 자주 확인할 사항

| 증상 | 확인할 내용 |
| --- | --- |
| 리포트가 한국어로 나오지 않음 | 실행 환경의 `REPORT_LANGUAGE=ko`와 요청별 언어 지정 여부를 확인합니다. 프로세스 환경변수가 `.env`보다 우선할 수 있습니다. |
| 리포트는 한국어인데 메뉴는 중국어·영어임 | 현재 지원 범위입니다. 리포트 언어와 UI 언어는 독립적입니다. |
| 한국 종목이 다른 시장으로 인식됨 | `.KS`·`.KQ`를 포함한 코드를 사용하고 거래소를 확인합니다. |
| Actions 실행 결과가 없음 | Actions 활성화, 실행 모드, 거래일 검사, 워크플로 로그를 확인합니다. |
| 모델 연결 실패 | API 키·제공자 주소·모델 권한·할당량을 확인합니다. 설정 화면에서 변경했다면 저장 후 연결을 테스트합니다. |
| 데이터가 일부 누락됨 | 시장별 지원 범위와 데이터 소스의 지연·제한을 확인합니다. |
| 알림이 오지 않음 | 선택한 채널의 필수 설정과 전송 로그를 확인합니다. 모델 분석 성공과 알림 전송 성공은 별개입니다. |

그 밖의 문제는 [FAQ — 영어](FAQ_EN.md)와 [한국어 문서 안내](INDEX_KO.md)에서 해당 주제를 찾아보세요.
