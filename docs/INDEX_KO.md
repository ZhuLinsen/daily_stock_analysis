# 한국어 문서 안내

한국어로 처음 사용하는 분을 위한 문서 진입점입니다. 먼저 [한국어 시작 가이드](getting-started_KO.md)를 읽고, 필요한 상세 문서를 아래에서 선택하세요.

현재 한국어 문서는 시작 가이드와 이 안내입니다. 상세 문서는 영어·중국어 원문으로 연결하며, 링크 옆에 언어를 표시했습니다. Web UI 전체 한글화는 포함하지 않습니다. 리포트의 한국어 출력은 `REPORT_LANGUAGE=ko`로 설정합니다.

[简体中文 문서 안내](INDEX.md) · [English documentation](INDEX_EN.md)

## 목적별 문서

| 필요한 내용 | 문서 | 언어 |
| --- | --- | --- |
| 첫 실행, 한국어 리포트, 한국 종목 코드 | [시작 가이드](getting-started_KO.md) | 한국어 |
| 프로젝트 기능과 실행 예시 | [프로젝트 소개](README_EN.md) | 영어 |
| 전체 환경변수·실행 방식·설정 | [전체 가이드](full-guide_EN.md) | 영어 |
| AI 모델 제공자·여러 모델·로컬 모델 | [LLM 설정 가이드](LLM_CONFIG_GUIDE_EN.md) | 영어 |
| Telegram·이메일 등 알림 채널 | [알림 설정](full-guide_EN.md#notification-channel-configuration) | 영어 |
| Docker·서버 배포 | [배포 가이드](DEPLOY_EN.md) | 영어 |
| Web UI 외부 접속·인증 | [클라우드 Web UI 배포](deploy-webui-cloud.md) | 중국어 |
| 데스크톱 설치·초기 설정 | [클라이언트 설치 안내](beginner-client-setup.md) | 중국어 |
| 데스크톱 패키지·플랫폼별 제약 | [데스크톱 패키지 안내](desktop-package.md) | 중국어 |
| 한국·일본 등 시장별 데이터 지원 범위 | [시장 지원과 경계](market-support.md) | 중국어 |
| 데이터 소스 상태·진단 | [데이터 센터](data-center-diagnostics.md) | 중국어 |
| Bot 명령과 연동 | [Bot 명령 가이드](bot-command_EN.md) | 영어 |
| 실행 오류·자주 묻는 질문 | [FAQ](FAQ_EN.md) | 영어 |
| 변경 내역 | [변경 로그](CHANGELOG.md) | 중국어 중심 |
| 코드·문서 기여 | [기여 가이드](CONTRIBUTING_EN.md) | 영어 |

## 설정·구현 확인

문서의 설정을 실제 파일과 대조하려면 다음 위치를 확인하세요.

- [환경변수 예시](../.env.example): 설정 이름과 기본값.
- [자동 분석 워크플로](../.github/workflows/00-daily-analysis.yml): Actions 입력, 예약 실행 시각, Secrets·Variables 전달.
- [실행 진입점](../main.py): CLI 옵션과 실행 모드.
- [Web 프런트엔드 패키지](../apps/dsa-web/package.json): Node.js·npm 요구 버전과 빌드 명령.

설정 이름·CLI 옵션·종목 코드·API 필드명은 번역하지 않고 원래 표기를 유지합니다. 원문이나 구현이 변경되면 번역 내용도 함께 확인해야 합니다.
