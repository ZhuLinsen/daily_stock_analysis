import { describe, expect, it } from 'vitest';
import { UI_TEXT } from '../src/i18n/uiText';
import { getSettingsHelpContent } from '../src/locales/settingsHelp';
import { getFieldDescriptionZh, getFieldOptionLabelZh, getFieldTitleZh } from '../src/utils/systemConfigI18n';

const requiredLocalizedKeys = [
  'TICKFLOW_API_KEY',
  'TICKFLOW_PRIORITY',
  'TICKFLOW_KLINE_ADJUST',
  'TICKFLOW_BATCH_DAILY_ENABLED',
  'TICKFLOW_BATCH_SIZE',
  'STOCK_INDEX_REMOTE_UPDATE_ENABLED',
  'SEARXNG_BASE_URLS',
  'ENABLE_REALTIME_QUOTE',
  'ENABLE_CHIP_DISTRIBUTION',
  'PYTDX_HOST',
  'PYTDX_PORT',
  'PYTDX_SERVERS',
  'BIAS_THRESHOLD',
  'GENERATION_BACKEND',
  'LLM_PROMPT_CACHE_TELEMETRY_ENABLED',
  'LLM_PROMPT_CACHE_HINTS_ENABLED',
  'LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL',
  'LLM_USAGE_HMAC_SECRET',
  'LLM_USAGE_HMAC_KEY_VERSION',
  'TELEGRAM_BOT_TOKEN',
  'TELEGRAM_CHAT_ID',
  'TELEGRAM_MESSAGE_THREAD_ID',
  'FEISHU_STREAM_ENABLED',
  'DINGTALK_STREAM_ENABLED',
  'EMAIL_SENDER',
  'EMAIL_PASSWORD',
  'EMAIL_RECEIVERS',
  'DISCORD_WEBHOOK_URL',
  'DISCORD_BOT_TOKEN',
  'DISCORD_MAIN_CHANNEL_ID',
  'DISCORD_INTERACTIONS_PUBLIC_KEY',
  'SLACK_BOT_TOKEN',
  'SLACK_CHANNEL_ID',
  'SLACK_WEBHOOK_URL',
  'PUSHPLUS_TOPIC',
  'PUSHOVER_USER_KEY',
  'PUSHOVER_API_TOKEN',
  'SERVERCHAN3_SENDKEY',
  'ASTRBOT_URL',
  'ASTRBOT_TOKEN',
  'CUSTOM_WEBHOOK_BEARER_TOKEN',
  'WEBHOOK_VERIFY_SSL',
  'SINGLE_STOCK_NOTIFY',
  'REPORT_TYPE',
  'REPORT_LANGUAGE',
  'REPORT_TEMPLATES_DIR',
  'REPORT_INTEGRITY_ENABLED',
  'REPORT_RENDERER_ENABLED',
  'REPORT_INTEGRITY_RETRY',
  'REPORT_HISTORY_COMPARE_N',
  'MERGE_EMAIL_NOTIFICATION',
  'NOTIFICATION_REPORT_CHANNELS',
  'NOTIFICATION_ALERT_CHANNELS',
  'NOTIFICATION_SYSTEM_ERROR_CHANNELS',
  'NOTIFICATION_DEDUP_TTL_SECONDS',
  'NOTIFICATION_COOLDOWN_SECONDS',
  'NOTIFICATION_QUIET_HOURS',
  'NOTIFICATION_TIMEZONE',
  'NOTIFICATION_MIN_SEVERITY',
  'NOTIFICATION_DAILY_DIGEST_ENABLED',
  'SCHEDULE_ENABLED',
  'DSA_RUNTIME_SCHEDULER_TIMEOUT_SECONDS',
  'SCHEDULE_RUN_IMMEDIATELY',
  'TRADING_DAY_CHECK_ENABLED',
  'WEBUI_HOST',
  'LOG_DIR',
  'WEBUI_ENABLED',
  'WEBUI_AUTO_BUILD',
  'ADMIN_AUTH_ENABLED',
  'TRUST_X_FORWARDED_FOR',
  'RUN_IMMEDIATELY',
  'MARKET_REVIEW_ENABLED',
  'DAILY_MARKET_CONTEXT_ENABLED',
  'MARKET_REVIEW_REGION',
  'ANALYSIS_DELAY',
  'SAVE_CONTEXT_SNAPSHOT',
  'DEBUG',
  'AGENT_NL_ROUTING',
  'AGENT_DEEP_RESEARCH_BUDGET',
  'AGENT_DEEP_RESEARCH_TIMEOUT',
  'AGENT_EVENT_MONITOR_ENABLED',
  'AGENT_EVENT_MONITOR_INTERVAL_MINUTES',
  'AGENT_EVENT_ALERT_RULES_JSON',
] as const;

describe('systemConfigI18n required key coverage', () => {
  it('provides zh title and description mapping for known missing keys', () => {
    requiredLocalizedKeys.forEach((key) => {
      expect(getFieldTitleZh(key, key)).not.toBe(key);
      expect(getFieldDescriptionZh(key, 'schema fallback description')).not.toBe('schema fallback description');
    });
  });

  it('uses a Chinese primary title for SearXNG base URLs', () => {
    const title = getFieldTitleZh('SEARXNG_BASE_URLS', 'SEARXNG_BASE_URLS');

    expect(title).toBe('SearXNG 自建实例地址');
    expect(title).not.toBe('SearXNG Base URLs');
  });

  it('documents LLM usage HMAC privacy boundaries', () => {
    const zh = getSettingsHelpContent('settings.ai_model.LLM_USAGE_HMAC_SECRET', undefined, 'zh-CN');
    const en = getSettingsHelpContent('settings.ai_model.LLM_USAGE_HMAC_SECRET', undefined, 'en');

    expect(zh?.summary).toContain('HMAC');
    expect(zh?.notes?.join(' ')).toContain('不要');
    expect(en?.summary).toContain('HMAC');
    expect(en?.notes?.join(' ')).toContain('Do not');
  });

  it('documents the runtime scheduler timeout in both UI languages', () => {
    const zh = getSettingsHelpContent('settings.system.schedule', undefined, 'zh-CN');
    const en = getSettingsHelpContent('settings.system.schedule', undefined, 'en');
    const zhText = JSON.stringify(zh);
    const enText = JSON.stringify(en);

    expect(zhText).toContain('DSA_RUNTIME_SCHEDULER_TIMEOUT_SECONDS');
    expect(zhText).toContain('2700');
    expect(zhText).toContain('60');
    expect(enText).toContain('DSA_RUNTIME_SCHEDULER_TIMEOUT_SECONDS');
    expect(enText).toContain('2700');
    expect(enText).toContain('60');
  });
});

describe('systemConfigI18n option label localization', () => {
  const realSelectOptionCases = [
    ['NEWS_STRATEGY_PROFILE', 'ultra_short', undefined, '超短线（1天）'],
    ['NEWS_STRATEGY_PROFILE', 'short', undefined, '短期（3天）'],
    ['NEWS_STRATEGY_PROFILE', 'medium', undefined, '中期（7天）'],
    ['NEWS_STRATEGY_PROFILE', 'long', undefined, '长期（30天）'],
    ['REPORT_TYPE', 'simple', undefined, '简洁'],
    ['REPORT_TYPE', 'full', undefined, '完整'],
    ['REPORT_TYPE', 'brief', undefined, '简报'],
    ['REPORT_LANGUAGE', 'zh', 'Chinese', '中文'],
    ['REPORT_LANGUAGE', 'en', 'English', '英文'],
    ['REPORT_LANGUAGE', 'ko', 'Korean', '韩文'],
    ['NOTIFICATION_MIN_SEVERITY', '', 'Not set', '未设置'],
    ['NOTIFICATION_MIN_SEVERITY', 'info', 'info', '信息'],
    ['NOTIFICATION_MIN_SEVERITY', 'warning', 'warning', '警告'],
    ['NOTIFICATION_MIN_SEVERITY', 'error', 'error', '错误'],
    ['NOTIFICATION_MIN_SEVERITY', 'critical', 'critical', '严重'],
    ['LOG_LEVEL', 'DEBUG', undefined, '调试'],
    ['LOG_LEVEL', 'INFO', undefined, '信息'],
    ['LOG_LEVEL', 'WARNING', undefined, '警告'],
    ['LOG_LEVEL', 'ERROR', undefined, '错误'],
    ['LOG_LEVEL', 'CRITICAL', undefined, '严重'],
    ['LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL', 'off', undefined, '关闭'],
    ['LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL', 'basic', undefined, '基础'],
    ['LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL', 'debug', undefined, '调试'],
    ['MARKET_REVIEW_COLOR_SCHEME', 'green_up', 'Green Up / Red Down', '绿涨红跌'],
    ['MARKET_REVIEW_COLOR_SCHEME', 'red_up', 'Red Up / Green Down', '红涨绿跌'],
    ['GENERATION_BACKEND', 'litellm', undefined, '默认模型配置'],
    ['AGENT_ARCH', 'single', 'Single Agent', '单 Agent'],
    ['AGENT_ARCH', 'multi', 'Multi Agent (Orchestrator)', '多 Agent（编排）'],
    ['AGENT_ORCHESTRATOR_MODE', 'quick', 'Quick', '快速'],
    ['AGENT_ORCHESTRATOR_MODE', 'standard', 'Standard', '标准'],
    ['AGENT_ORCHESTRATOR_MODE', 'full', 'Full', '完整'],
    ['AGENT_ORCHESTRATOR_MODE', 'specialist', 'Specialist', '专家'],
    ['AGENT_SKILL_ROUTING', 'auto', 'Auto (Regime-based)', '自动（按市场状态）'],
    ['AGENT_SKILL_ROUTING', 'manual', 'Manual (Use AGENT_SKILLS)', '手动（使用 AGENT_SKILLS）'],
  ] as const;

  it('localizes all select options currently exposed by system config schema', () => {
    realSelectOptionCases.forEach(([key, value, fallbackLabel, expectedLabel]) => {
      const label = getFieldOptionLabelZh(key, value, fallbackLabel);

      expect(label).toBe(expectedLabel);
      expect(label).not.toBe(value);
      if (fallbackLabel) {
        expect(label).not.toBe(fallbackLabel);
      }
    });
  });

  it('treats free-text config keys as passthrough for option labels', () => {
    expect(getFieldOptionLabelZh('MARKET_REVIEW_REGION', 'cn')).toBe('cn');
    expect(getFieldOptionLabelZh('MARKET_REVIEW_REGION', 'cn,us,jp,kr')).toBe('cn,us,jp,kr');
  });
});

describe('SAVE_CONTEXT_SNAPSHOT settings help contract', () => {
  it('describes the persistence boundary without implying old records are changed', () => {
    const help = getSettingsHelpContent('settings.system.SAVE_CONTEXT_SNAPSHOT', undefined, 'zh-CN');
    const text = [
      help?.summary,
      help?.usage,
      ...(help?.valueNotes ?? []),
      ...(help?.impact ?? []),
      ...(help?.notes ?? []),
    ].join('\n');

    expect(text).toContain('新历史记录');
    expect(text).toContain('不关闭当次 AnalysisContextPack 构建');
    expect(text).toContain('不关闭 LLM Prompt');
    expect(text).not.toContain('旧记录');
  });
});

describe('generation backend settings help contract', () => {
  it('uses user-facing generation channel copy instead of implementation terms', () => {
    const zhInlineText = [
      getFieldTitleZh('GENERATION_BACKEND', ''),
      getFieldDescriptionZh('GENERATION_BACKEND', ''),
      getFieldTitleZh('AGENT_BACKEND', ''),
      getFieldDescriptionZh('AGENT_BACKEND', ''),
    ].join('\n');
    const zhBackend = getSettingsHelpContent('settings.ai_model.GENERATION_BACKEND', undefined, 'zh-CN');
    const enBackend = getSettingsHelpContent('settings.ai_model.GENERATION_BACKEND', undefined, 'en');
    const zhAgent = getSettingsHelpContent('settings.agent.AGENT_BACKEND', undefined, 'zh-CN');
    const enAgent = getSettingsHelpContent('settings.agent.AGENT_BACKEND', undefined, 'en');
    const zhText = [
      zhBackend?.title,
      zhBackend?.summary,
      zhBackend?.usage,
      ...(zhBackend?.valueNotes ?? []),
      ...(zhBackend?.impact ?? []),
      ...(zhBackend?.notes ?? []),
      zhAgent?.title,
      zhAgent?.summary,
      zhAgent?.usage,
      ...(zhAgent?.valueNotes ?? []),
      ...(zhAgent?.impact ?? []),
      ...(zhAgent?.notes ?? []),
    ].join('\n');
    const enText = [
      enBackend?.title,
      enBackend?.summary,
      enBackend?.usage,
      ...(enBackend?.valueNotes ?? []),
      ...(enBackend?.impact ?? []),
      ...(enBackend?.notes ?? []),
      enAgent?.title,
      enAgent?.summary,
      enAgent?.usage,
      ...(enAgent?.valueNotes ?? []),
      ...(enAgent?.impact ?? []),
      ...(enAgent?.notes ?? []),
    ].join('\n');

    expect(zhBackend?.title).toBe('分析生成方式');
    expect(zhAgent?.title).toBe('问股生成方式');
    expect(zhBackend?.showFieldKey).toBe(false);
    expect(zhAgent?.showFieldKey).toBe(false);
    expect(zhBackend?.examples).toEqual([]);
    expect(zhAgent?.examples).toEqual([]);
    expect(zhText).toContain('个股分析');
    expect(zhText).toContain('大盘复盘');
    expect(zhText).toContain('自动');
    expect(zhBackend?.usage).toContain('默认模型配置');
    expect(zhText).not.toContain('unsupported_tool_calling');
    expect(zhText).not.toContain('run_agent_loop');
    [
      'Backend',
      'backend',
      'backend-level',
      'generation backend',
      'self fallback',
      'stdout',
      'stderr',
      'contract',
      'MAX_WORKERS',
      'Router',
      'diagnostics',
      'executable',
      'coding-agent',
      'experimental/limited',
      'fail-fast',
    ].forEach((term) => {
      expect(zhInlineText).not.toContain(term);
      expect(zhText).not.toContain(term);
    });

    expect(enBackend?.title).toBe('Analysis Generation Method');
    expect(enAgent?.title).toBe('Ask-Stock Method');
    expect(enText).toContain('stock analysis');
    expect(enText).toContain('market reviews');
    expect(enText).toContain('Auto');
    expect(enBackend?.usage).toContain('Default model settings');
    expect(enText).not.toContain('unsupported_tool_calling');
    expect(enText).not.toContain('run_agent_loop');
  });
});

describe('generation backend status panel i18n contract', () => {
  it('keeps the new status panel copy localized in both UI languages', () => {
    expect(UI_TEXT.zh['settings.generationBackendStatus']).toBe('生成后端状态');
    expect(UI_TEXT.zh['settings.generationBackendSmokeTest']).toBe('JSON 冒烟测试');
    expect(UI_TEXT.zh['settings.generationBackendPrimary']).toBe('主后端');
    expect(UI_TEXT.zh['settings.generationBackendFallback']).toBe('备用后端');
    expect(UI_TEXT.zh['settings.generationBackendGenerationOnly']).toBe('仅生成');
    expect(UI_TEXT.zh['settings.generationBackendStatusDescription']).toContain('快速检查');
    expect(UI_TEXT.zh['settings.generationBackendStatusDescription']).not.toContain('cheap check');
    expect(UI_TEXT.zh['settings.generationBackendSmokePassed']).not.toContain('Smoke test');

    expect(UI_TEXT.en['settings.generationBackendStatus']).toBe('Generation backend status');
    expect(UI_TEXT.en['settings.generationBackendSmokeTest']).toBe('JSON smoke test');
    expect(UI_TEXT.en['settings.generationBackendPrimary']).toBe('Primary backend');
    expect(UI_TEXT.en['settings.generationBackendFallback']).toBe('Fallback backend');
    expect(UI_TEXT.en['settings.generationBackendGenerationOnly']).toBe('Generation only');
  });
});

describe('decision signal settings guard', () => {
  it('does not add placeholder DecisionSignal setting translations without a real schema field', () => {
    const placeholderKeys = [
      'DECISION_SIGNAL_ENABLED',
      'DECISION_SIGNALS_ENABLED',
      'DECISION_SIGNAL_WRITE_ENABLED',
      'DECISION_SIGNAL_EXTRACT_ENABLED',
    ];

    placeholderKeys.forEach((key) => {
      expect(getFieldTitleZh(key, key)).toBe(key);
      expect(getFieldDescriptionZh(key, 'schema fallback description')).toBe('schema fallback description');
    });
  });
});
