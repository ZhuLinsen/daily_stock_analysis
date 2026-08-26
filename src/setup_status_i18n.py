# -*- coding: utf-8 -*-
"""Localization for the read-only first-run setup status API."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from src.report_language import normalize_report_language


# The setup endpoint historically returned Chinese copy.  Preserve that response
# when no language is requested, while allowing the Web UI to request its own
# language without coupling it to the report-language setting in ``.env``.
SETUP_CHECK_TITLES: Dict[str, Dict[str, str]] = {
    "llm_primary": {"zh": "LLM 主渠道", "en": "LLM primary channel", "ko": "LLM 주 채널"},
    "llm_agent": {"zh": "Agent 渠道", "en": "Agent channel", "ko": "Agent 채널"},
    "tracker_research": {"zh": "Tracker 研究侧车", "en": "Tracker research sidecar", "ko": "Tracker 리서치 사이드카"},
    "stock_list": {"zh": "自选股", "en": "Watchlist", "ko": "관심 종목"},
    "notification": {"zh": "通知渠道", "en": "Notification channel", "ko": "알림 채널"},
    "storage": {"zh": "数据库 / 本地存储", "en": "Database / local storage", "ko": "데이터베이스 / 로컬 저장소"},
}

SETUP_CHECK_TEXT: Dict[str, Dict[str, str]] = {
    "已配置 Tracker 韩国股票研究侧车；KOSPI/KOSDAQ 新闻会在分析前按需刷新到隔离缓存。": {
        "en": "The Tracker Korean-stock research sidecar is configured; KOSPI/KOSDAQ news is refreshed into its isolated cache on demand before analysis.",
        "ko": "Tracker 한국 주식 리서치 사이드카가 구성되었습니다. 분석 전에 KOSPI/KOSDAQ 뉴스가 필요 시 격리 캐시로 새로 수집됩니다.",
    },
    "已配置 Tracker 韩国股票研究侧车；仅使用已缓存的 KOSPI/KOSDAQ 研究数据。": {
        "en": "The Tracker Korean-stock research sidecar is configured; only already-cached KOSPI/KOSDAQ research data will be used.",
        "ko": "Tracker 한국 주식 리서치 사이드카가 구성되었습니다. 이미 캐시된 KOSPI/KOSDAQ 리서치 데이터만 사용합니다.",
    },
    "Tracker 研究侧车配置无效。": {
        "en": "The Tracker research sidecar configuration is invalid.",
        "ko": "Tracker 리서치 사이드카 구성이 올바르지 않습니다.",
    },
    "请确认 URL 仅指向本机回环地址，且令牌为 32 至 512 个安全字符。": {
        "en": "Ensure the URL points only to a local loopback address and the token contains 32 to 512 safe characters.",
        "ko": "URL이 로컬 루프백 주소만 가리키고 토큰이 32~512자의 안전한 문자로 구성됐는지 확인하세요.",
    },
    "Tracker 韩国股票研究侧车为可选项；未配置时仍可使用其他新闻搜索渠道。": {
        "en": "The Tracker Korean-stock research sidecar is optional; other news search channels remain available when it is not configured.",
        "ko": "Tracker 한국 주식 리서치 사이드카는 선택사항입니다. 구성하지 않아도 다른 뉴스 검색 채널은 사용할 수 있습니다.",
    },
    "如需韩国股票新闻依据，请在 DSA 与 Tracker 的私有 .env 中配置相同的侧车令牌。": {
        "en": "For Korean-stock news evidence, configure the same sidecar token in the private .env files for both DSA and Tracker.",
        "ko": "한국 주식 뉴스 근거가 필요하면 DSA와 Tracker의 비공개 .env에 동일한 사이드카 토큰을 구성하세요.",
    },
    "已选择 codex_cli，但 DSA 后端进程当前 PATH 中找不到 codex 可执行文件。": {
        "en": "codex_cli is selected, but the DSA backend process cannot find the codex executable in its current PATH.",
        "ko": "codex_cli가 선택되었지만 DSA 백엔드 프로세스의 현재 PATH에서 codex 실행 파일을 찾을 수 없습니다.",
    },
    "请确认 Codex CLI 已安装到后端 PATH 可见目录；桌面端请完全退出并重开。打开 Codex CLI 交互窗口不会改变已运行后端的 PATH；若找到后仍失败，再检查 Codex CLI 登录态，或将 GENERATION_BACKEND 设回 litellm。": {
        "en": "Ensure Codex CLI is installed in a directory visible to the backend PATH; fully quit and reopen the desktop app. Opening a Codex CLI shell does not change the PATH of an already running backend. If it is found but still fails, check the Codex CLI sign-in state or set GENERATION_BACKEND back to litellm.",
        "ko": "Codex CLI가 백엔드 PATH에서 볼 수 있는 디렉터리에 설치되었는지 확인하고, 데스크톱 앱은 완전히 종료한 뒤 다시 여세요. Codex CLI 대화형 창을 열어도 이미 실행 중인 백엔드의 PATH는 바뀌지 않습니다. 계속 실패하면 Codex CLI 로그인 상태를 확인하거나 GENERATION_BACKEND를 litellm으로 되돌리세요.",
    },
    "请先安装并登录对应 CLI，或将 GENERATION_BACKEND 设回 litellm。": {
        "en": "Install and sign in to the selected CLI, or set GENERATION_BACKEND back to litellm.",
        "ko": "해당 CLI를 설치하고 로그인하거나 GENERATION_BACKEND를 litellm으로 되돌리세요.",
    },
    "主模型未出现在当前 LiteLLM YAML model_list 中": {
        "en": "The primary model is not present in the current LiteLLM YAML model_list.",
        "ko": "주 모델이 현재 LiteLLM YAML model_list에 없습니다.",
    },
    "主模型未出现在当前启用渠道模型列表中": {
        "en": "The primary model is not present in the currently enabled channel model list.",
        "ko": "주 모델이 현재 활성화된 채널 모델 목록에 없습니다.",
    },
    "主模型缺少可用渠道或匹配的 API Key": {
        "en": "The primary model has no available channel or matching API key.",
        "ko": "주 모델에 사용할 수 있는 채널 또는 일치하는 API 키가 없습니다.",
    },
    "尚未检测到主模型配置": {
        "en": "No primary model configuration was detected.",
        "ko": "주 모델 구성이 감지되지 않았습니다.",
    },
    "请配置 LITELLM_MODEL、LLM_CHANNELS、LITELLM_CONFIG 或 legacy provider API Key。": {
        "en": "Configure LITELLM_MODEL, LLM_CHANNELS, LITELLM_CONFIG, or a legacy provider API key.",
        "ko": "LITELLM_MODEL, LLM_CHANNELS, LITELLM_CONFIG 또는 레거시 제공자 API 키를 구성하세요.",
    },
    "请将 AGENT_GENERATION_BACKEND 设为 auto 或 litellm，并配置 LiteLLM 工具调用渠道。": {
        "en": "Set AGENT_GENERATION_BACKEND to auto or litellm, then configure a LiteLLM channel that supports tool calls.",
        "ko": "AGENT_GENERATION_BACKEND를 auto 또는 litellm으로 설정한 뒤, 도구 호출을 지원하는 LiteLLM 채널을 구성하세요.",
    },
    "普通分析使用 Codex CLI；但当前 LiteLLM Agent 路径继承的是 Hermes-only 模型，Hermes Phase 3 不支持 Agent 工具调用。": {
        "en": "Regular analysis uses Codex CLI, but the current LiteLLM Agent path inherits a Hermes-only model. Hermes Phase 3 does not support Agent tool calls.",
        "ko": "일반 분석은 Codex CLI를 사용하지만 현재 LiteLLM Agent 경로는 Hermes 전용 모델을 상속합니다. Hermes Phase 3는 Agent 도구 호출을 지원하지 않습니다.",
    },
    "如需使用 Ask-Stock Agent，请配置非 Hermes 的 AGENT_LITELLM_MODEL，或配置包含非 Hermes deployment 的 mixed Agent route。": {
        "en": "To use Ask-Stock Agent, configure a non-Hermes AGENT_LITELLM_MODEL or a mixed Agent route with a non-Hermes deployment.",
        "ko": "Ask-Stock Agent를 사용하려면 Hermes가 아닌 AGENT_LITELLM_MODEL 또는 Hermes가 아닌 배포를 포함하는 혼합 Agent 경로를 구성하세요.",
    },
    "AGENT_GENERATION_BACKEND 已选择 litellm，但未检测到可用 LiteLLM 模型配置。": {
        "en": "AGENT_GENERATION_BACKEND is set to litellm, but no usable LiteLLM model configuration was detected.",
        "ko": "AGENT_GENERATION_BACKEND가 litellm으로 설정되었지만 사용할 수 있는 LiteLLM 모델 구성이 감지되지 않았습니다.",
    },
    "如需使用 Ask-Stock Agent，请配置 AGENT_LITELLM_MODEL、LITELLM_MODEL、LLM_CHANNELS 或 LITELLM_CONFIG。": {
        "en": "To use Ask-Stock Agent, configure AGENT_LITELLM_MODEL, LITELLM_MODEL, LLM_CHANNELS, or LITELLM_CONFIG.",
        "ko": "Ask-Stock Agent를 사용하려면 AGENT_LITELLM_MODEL, LITELLM_MODEL, LLM_CHANNELS 또는 LITELLM_CONFIG를 구성하세요.",
    },
    "Agent 工具调用需要 LiteLLM 模型配置；local CLI 主生成方式不会被自动继承。": {
        "en": "Agent tool calls require a LiteLLM model configuration; the local CLI primary-generation path is not inherited automatically.",
        "ko": "Agent 도구 호출에는 LiteLLM 모델 구성이 필요하며, 로컬 CLI 주 생성 방식은 자동으로 상속되지 않습니다.",
    },
    "如需使用 Ask-Stock Agent，请配置 LiteLLM 模型，或将 AGENT_GENERATION_BACKEND 固定为 litellm 后补齐模型配置。": {
        "en": "To use Ask-Stock Agent, configure a LiteLLM model, or set AGENT_GENERATION_BACKEND to litellm and complete the model configuration.",
        "ko": "Ask-Stock Agent를 사용하려면 LiteLLM 모델을 구성하거나 AGENT_GENERATION_BACKEND를 litellm으로 고정한 뒤 모델 구성을 완료하세요.",
    },
    "Hermes Phase 3 不支持 Agent 工具调用，且当前继承的主模型没有非 Hermes deployment。": {
        "en": "Hermes Phase 3 does not support Agent tool calls, and the inherited primary model has no non-Hermes deployment.",
        "ko": "Hermes Phase 3는 Agent 도구 호출을 지원하지 않으며, 상속된 주 모델에는 Hermes가 아닌 배포가 없습니다.",
    },
    "请选择非 Hermes Agent 模型，或配置包含非 Hermes deployment 的 mixed Agent route。": {
        "en": "Choose a non-Hermes Agent model or configure a mixed Agent route with a non-Hermes deployment.",
        "ko": "Hermes가 아닌 Agent 모델을 선택하거나 Hermes가 아닌 배포를 포함하는 혼합 Agent 경로를 구성하세요.",
    },
    "请选择非 Hermes Agent 模型，或配置 mixed route 中的非 Hermes deployment。": {
        "en": "Choose a non-Hermes Agent model or configure a non-Hermes deployment in the mixed route.",
        "ko": "Hermes가 아닌 Agent 모델을 선택하거나 혼합 경로에 Hermes가 아닌 배포를 구성하세요.",
    },
    "未单独配置 Agent 主模型，将继承 LLM 主渠道。": {
        "en": "No separate Agent primary model is configured; it will inherit the LLM primary channel.",
        "ko": "별도의 Agent 주 모델이 구성되지 않아 LLM 주 채널을 상속합니다.",
    },
    "Agent 未配置独立模型，且 LLM 主渠道尚不可用。": {
        "en": "No dedicated Agent model is configured, and the LLM primary channel is not available yet.",
        "ko": "전용 Agent 모델이 구성되지 않았고 LLM 주 채널도 아직 사용할 수 없습니다.",
    },
    "请先补齐 LLM 主渠道配置。": {
        "en": "Complete the LLM primary-channel configuration first.",
        "ko": "먼저 LLM 주 채널 구성을 완료하세요.",
    },
    "请调整 AGENT_LITELLM_MODEL 或补齐对应渠道配置。": {
        "en": "Adjust AGENT_LITELLM_MODEL or complete the matching channel configuration.",
        "ko": "AGENT_LITELLM_MODEL을 조정하거나 해당 채널 구성을 완료하세요.",
    },
    "当前 STOCK_LIST 为空。": {
        "en": "STOCK_LIST is currently empty.",
        "ko": "현재 STOCK_LIST가 비어 있습니다.",
    },
    "请至少添加 1 只股票用于首次试跑。": {
        "en": "Add at least one stock for the initial smoke run.",
        "ko": "최초 시험 실행에 사용할 종목을 최소 1개 추가하세요.",
    },
    "已检测到至少一个通知渠道配置。": {
        "en": "At least one notification channel is configured.",
        "ko": "알림 채널이 하나 이상 구성되어 있습니다.",
    },
    "通知为可选项，未配置也不影响首次跑通。": {
        "en": "Notifications are optional and are not required for the initial run.",
        "ko": "알림은 선택사항이며 구성하지 않아도 최초 실행에는 영향을 주지 않습니다.",
    },
    "需要推送时可稍后配置飞书、钉钉、Telegram、邮件或其他通知渠道。": {
        "en": "When you need delivery, configure Feishu, DingTalk, Telegram, email, or another notification channel later.",
        "ko": "알림 발송이 필요할 때 Feishu, DingTalk, Telegram, 이메일 또는 다른 알림 채널을 나중에 구성할 수 있습니다.",
    },
    "请检查 DATABASE_PATH 或上级目录权限。": {
        "en": "Check DATABASE_PATH or the parent-directory permissions.",
        "ko": "DATABASE_PATH 또는 상위 디렉터리 권한을 확인하세요.",
    },
    "请调整 DATABASE_PATH 或目录权限。": {
        "en": "Adjust DATABASE_PATH or the directory permissions.",
        "ko": "DATABASE_PATH 또는 디렉터리 권한을 조정하세요.",
    },
}

SETUP_SOURCE_LABELS: Dict[str, Dict[str, str]] = {
    "显式主模型": {"en": "explicit primary model", "ko": "명시적 주 모델"},
    "LiteLLM YAML": {"en": "LiteLLM YAML", "ko": "LiteLLM YAML"},
    "LLM 渠道": {"en": "LLM channel", "ko": "LLM 채널"},
    "legacy provider": {"en": "legacy provider", "ko": "레거시 제공자"},
}

SETUP_FALLBACK_TEXT = {
    "en": "Review the configuration-status details.",
    "ko": "설정 상태의 세부 정보를 확인하세요.",
}


def _localize_setup_text(value: str, language: str) -> str:
    """Translate setup detail copy while retaining models and filesystem paths."""
    direct = SETUP_CHECK_TEXT.get(value)
    if direct is not None:
        return direct[language]

    match = re.fullmatch(r"已启用 (?P<display>.+) 本地生成 Backend（experimental/limited）。", value)
    if match:
        display = match.group("display")
        return (
            f"{display} local generation backend is enabled (experimental/limited)."
            if language == "en"
            else f"{display} 로컬 생성 백엔드가 활성화되어 있습니다(실험적/제한적)."
        )

    match = re.fullmatch(r"已选择 (?P<backend>.+)，但未找到 (?P<executable>.+) 可执行文件。", value)
    if match:
        backend = match.group("backend")
        executable = match.group("executable")
        return (
            f"{backend} is selected, but the {executable} executable was not found."
            if language == "en"
            else f"{backend}가 선택되었지만 {executable} 실행 파일을 찾을 수 없습니다."
        )

    match = re.fullmatch(r"已检测到 (?P<source>[^:]+): (?P<model>.+)", value)
    if match:
        source = match.group("source")
        model = match.group("model")
        localized_source = SETUP_SOURCE_LABELS.get(source, {}).get(language, source)
        return (
            f"Detected {localized_source}: {model}"
            if language == "en"
            else f"{localized_source}이(가) 감지되었습니다: {model}"
        )

    match = re.fullmatch(r"Agent 工具调用暂不支持 (?P<backend>.+) text-only backend。", value)
    if match:
        backend = match.group("backend")
        return (
            f"Agent tool calls do not currently support the {backend} text-only backend."
            if language == "en"
            else f"Agent 도구 호출은 현재 {backend} 텍스트 전용 백엔드를 지원하지 않습니다."
        )

    match = re.fullmatch(r"普通分析使用 Codex CLI；Agent 工具调用仍使用 LiteLLM 主模型: (?P<model>.+)", value)
    if match:
        model = match.group("model")
        return (
            f"Regular analysis uses Codex CLI; Agent tool calls still use the LiteLLM primary model: {model}"
            if language == "en"
            else f"일반 분석은 Codex CLI를 사용하며 Agent 도구 호출은 계속 LiteLLM 주 모델을 사용합니다: {model}"
        )

    match = re.fullmatch(
        r"Agent 主模型 (?P<model>.+) 只有 Hermes deployment，Phase 3 不支持 Agent 工具调用。",
        value,
    )
    if match:
        model = match.group("model")
        return (
            f"Agent primary model {model} has only a Hermes deployment; Phase 3 does not support Agent tool calls."
            if language == "en"
            else f"Agent 주 모델 {model}에는 Hermes 배포만 있어 Phase 3에서 Agent 도구 호출을 지원하지 않습니다."
        )

    match = re.fullmatch(r"已配置 Agent 主模型: (?P<model>.+)", value)
    if match:
        model = match.group("model")
        return f"Agent primary model is configured: {model}" if language == "en" else f"Agent 주 모델이 구성되었습니다: {model}"

    match = re.fullmatch(r"Agent 主模型 (?P<model>.+) 缺少可用渠道或匹配的 API Key。", value)
    if match:
        model = match.group("model")
        return (
            f"Agent primary model {model} has no available channel or matching API key."
            if language == "en"
            else f"Agent 주 모델 {model}에 사용할 수 있는 채널 또는 일치하는 API 키가 없습니다."
        )

    match = re.fullmatch(r"已配置 (?P<count>\d+) 只股票。", value)
    if match:
        count = match.group("count")
        return f"{count} stock(s) are configured." if language == "en" else f"종목 {count}개가 구성되었습니다."

    for pattern, english_template, korean_template in (
        (r"数据库路径父目录不可用: (?P<path>.+)", "The database parent directory is unavailable: {path}", "데이터베이스 상위 디렉터리를 사용할 수 없습니다: {path}"),
        (r"数据库上级目录可创建: (?P<path>.+)", "The database parent directory can be created: {path}", "데이터베이스 상위 디렉터리를 만들 수 있습니다: {path}"),
        (r"数据库路径可用: (?P<path>.+)", "The database path is available: {path}", "데이터베이스 경로를 사용할 수 있습니다: {path}"),
        (r"数据库路径上级目录不可写: (?P<path>.+)", "The database parent directory is not writable: {path}", "데이터베이스 상위 디렉터리에 쓸 수 없습니다: {path}"),
    ):
        match = re.fullmatch(pattern, value)
        if match:
            return (english_template if language == "en" else korean_template).format(**match.groupdict())

    return SETUP_FALLBACK_TEXT[language]


def localize_setup_checks(
    checks: Sequence[Dict[str, Any]],
    language: Optional[str],
) -> List[Dict[str, Any]]:
    """Return localized copies of setup checks without changing readiness semantics."""
    normalized_language = normalize_report_language(language)
    if normalized_language == "zh":
        return list(checks)

    localized_checks: List[Dict[str, Any]] = []
    for check in checks:
        localized = dict(check)
        localized["title"] = SETUP_CHECK_TITLES.get(check["key"], {}).get(
            normalized_language,
            "Configuration" if normalized_language == "en" else "설정",
        )
        localized["message"] = _localize_setup_text(check["message"], normalized_language)
        if check.get("next_step"):
            localized["next_step"] = _localize_setup_text(check["next_step"], normalized_language)
        localized_checks.append(localized)
    return localized_checks
