<!-- i18n-source: README.md | synced-commit: 38023206 | synced-date: 2026-11-28 -->
<div align="center">

# 📈 AI 주식 자동 분석 시스템 (Daily Stock Analysis)

[![GitHub stars](https://img.shields.io/github/stars/ZhuLinsen/daily_stock_analysis?style=social)](https://github.com/ZhuLinsen/daily_stock_analysis/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-Ready-2088FF?logo=github-actions&logoColor=white)](https://github.com/features/actions)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/zhulinsen/daily_stock_analysis)

**한국주식（`.KS`/`.KQ`）・미국주식・홍콩・A주・일본・대만 관심종목을 매일 자동 분석하고 알림을 보내는 AI 주식 분석 시스템**

관심종목 데일리 분석 → 의사결정 대시보드 생성 → Telegram / Discord / Slack / Email / Feishu / WeCom 푸시 알림

한국어 | [English](README_EN.md) | [简体中文](../README.md) | [繁體中文](README_CHT.md) | [日本語](README_JA.md)

</div>

> [!NOTE]
> **지원 언어 및 데이터 범위 안내**
> - **한국어 리포트 기본 지원**：`REPORT_LANGUAGE=ko` 설정 시 **AI 분석 리포트・공유 카드 이미지・Web 리포트 패널**이 한국어로 출력됩니다. Web UI 내비게이션/설정 메뉴는 현재 **English / 中文** 을 지원합니다.
> - **한국 주식（예: `005930.KS`, `000660.KS`, `035420.KS`）**：Yahoo Finance 기반으로 시세・일봉・기술적 지표・지수 리뷰（`^KS11` / `^KQ11`）를 지원합니다. 시장별 지원 범위와 제한 사항은 [Multi-Market Support & Boundaries](./market-support_EN.md) 를 참고하세요.
> - **전체 상세 문서**：이 페이지는 한국어 빠른 시작 안내입니다. 최신 전체 문서는 [English Docs](./INDEX_EN.md) / [공식 문서 사이트 (EN)](https://dsa.zhulinsen.tech/en/) / [简体中文 README](../README.md) 기준으로 관리됩니다.

## 🖥️ 화면 미리보기

<p align="center">
  <a href="assets/readme_workspace_tour_20260510.gif"><img src="assets/readme_workspace_preview.gif" alt="DSA Web workspace demo" width="640"></a><br>
  <sub>클릭하여 전체 데모 보기</sub>
</p>

## ✨ 핵심 기능

| 기능 | 설명 |
|---|---|
| **한국어 AI 의사결정 리포트** | 핵심 결론, 점수, 추세, 매수/손절/목표가, 리스크 경고, 모멘텀, 체크리스트 생성（`REPORT_LANGUAGE=ko` 지원） |
| **멀티 마켓 지원** | 한국주식（`005930.KS` 등）, 미국주식（`AAPL`）, 홍콩（`hk00700`）, A주（`600519`）, 일본（`7203.T`）, 대만（`2330.TW`）, ETF 지원 |
| **Web / 데스크톱 워크스페이스** | 수동 분석, 실시간 진행 상황, 리포트 히스토리, 백테스트, 포트폴리오 리스크, 알림 규칙, 다크/라이트 테마 |
| **Agent 전략 Q&A** | 20종 기본 내장 전략과 커스텀 YAML 스킬 기반의 멀티턴 종목 대화 분석 |
| **무료 자동화 & 알림** | GitHub Actions / Docker / 로컬 스케줄러 / FastAPI 지원, Telegram・Discord・Slack・Email 등 다채널 알림 |

## 🚀 5분 빠른 시작

### 방법 1: GitHub Actions (서버 불필요・무료)

1. 이 저장소를 **Fork** 합니다.
2. Fork한 저장소의 `Settings` → `Secrets and variables` → `Actions` 에서 필수 Secrets 를 등록합니다:

| Secret 이름 | 예시 / 설명 | 필수 여부 |
|---|---|:---:|
| `STOCK_LIST` | `005930.KS,000660.KS,AAPL,NVDA` (쉼표 구분) | ✅ |
| `REPORT_LANGUAGE` | `ko` (한국어 리포트 출력) | 권장 |
| AI API Key (택 1) | `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` 등 | ✅ |
| 알림 채널 (선택) | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID`, `EMAIL_SENDER` + `EMAIL_PASSWORD` 등 | 선택 |
| 뉴스 검색 (권장) | `SERPAPI_API_KEYS` / `TAVILY_API_KEYS` / `BRAVE_API_KEYS` | 권장 |

3. `Actions` 탭에서 워크플로우를 활성화한 뒤 `每日股票分析` → `Run workflow` 로 즉시 테스트합니다.

### 방법 2: 로컬 / WebUI / 데스크톱 앱

```bash
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git && cd daily_stock_analysis
pip install -r requirements.txt
cp .env.example .env   # STOCK_LIST=005930.KS,000660.KS,AAPL 및 REPORT_LANGUAGE=ko, AI Key 설정

# 지정 종목 1회 분석 실행
python main.py --stocks 005930.KS,000660.KS,AAPL --no-market-review

# Web UI 실행 (http://127.0.0.1:8000)
python main.py --serve-only
```

> 코드 설치 없이 바로 사용하려면 [Beginner Desktop Setup Guide (EN)](./beginner-client-setup_EN.md) 를 참고하세요.

## 📚 상세 문서 (English / 中文)

| 문서 | 내용 |
|---|---|
| [Full English README](./README_EN.md) | 영문 전체 개요・스폰서・CLI・에이전트 플러그인 설치 |
| [Documentation Index (EN)](./INDEX_EN.md) | 전체 문서 목차 및 중국 시장 용어 정리 |
| [Official Docs Site (EN)](https://dsa.zhulinsen.tech/en/) | 검색을 지원하는 공식 문서 사이트 |
| [Multi-Market Support & Boundaries](./market-support_EN.md) | 한국・미국 등 시장별 데이터 소스 및 제한 사항 |
| [LLM Config Guide (EN)](./LLM_CONFIG_GUIDE_EN.md) | Gemini / OpenAI / Claude / DeepSeek / Ollama / LiteLLM 라우팅 설정 |
| [Notification Channels (EN)](./notifications_EN.md) | Telegram / Discord / Slack / Email / Webhook 알림 설정 |
| [Deploy Guide (EN)](./DEPLOY_EN.md) / [FAQ (EN)](./FAQ_EN.md) | Docker・서버 배포 및 자주 묻는 질문 |

## 📄 라이선스 & 면책 조항

- **라이선스**: [MIT License](../LICENSE) © 2026 ZhuLinsen
- **면책 조항**: 본 프로젝트는 정보 제공 및 학습 목적으로만 제공되며 투자 권유나 자문이 아닙니다. 모든 투자 판단과 책임은 사용자 본인에게 있습니다.
