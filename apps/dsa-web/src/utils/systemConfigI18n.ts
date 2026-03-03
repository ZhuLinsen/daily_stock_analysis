import type { SystemConfigCategory } from '../types/systemConfig';

const categoryTitleMap: Record<SystemConfigCategory, string> = {
  base: '基础设置',
  data_source: '数据源',
  ai_model: 'AI 模型',
  notification: '通知渠道',
  system: '系统设置',
  agent: 'Agent 设置',
  backtest: '回测配置',
  uncategorized: '其他',
};

const categoryDescriptionMap: Partial<Record<SystemConfigCategory, string>> = {
  base: '管理自选股与基础运行参数。',
  data_source: '管理行情数据源与优先级策略。',
  ai_model: '管理模型供应商、模型名称与推理参数。',
  notification: '管理机器人、Webhook 和消息推送配置。',
  system: '管理调度、日志、端口等系统级参数。',
  agent: '管理 Agent 模式、技能与策略配置。',
  backtest: '管理回测开关、评估窗口和引擎参数。',
  uncategorized: '其他未归类的配置项。',
};

const fieldTitleMap: Record<string, string> = {
  STOCK_LIST: '自选股列表',
  TUSHARE_TOKEN: 'Tushare Token',
  TAVILY_API_KEYS: 'Tavily API Keys',
  SERPAPI_API_KEYS: 'SerpAPI API Keys',
  BRAVE_API_KEYS: 'Brave API Keys',
  REALTIME_SOURCE_PRIORITY: '实时数据源优先级',
  ENABLE_REALTIME_TECHNICAL_INDICATORS: '盘中实时技术面',
  GEMINI_API_KEY: 'Gemini API Key',
  GEMINI_MODEL: 'Gemini 模型',
  GEMINI_TEMPERATURE: 'Gemini 温度参数',
  OPENAI_API_KEY: 'OpenAI API Key',
  OPENAI_BASE_URL: 'OpenAI Base URL',
  OPENAI_MODEL: 'OpenAI 模型',
  WECHAT_WEBHOOK_URL: '企业微信 Webhook',
  DINGTALK_APP_KEY: '钉钉 App Key',
  DINGTALK_APP_SECRET: '钉钉 App Secret',
  PUSHPLUS_TOKEN: 'PushPlus Token',
  REPORT_SUMMARY_ONLY: '仅分析结果摘要',
  SCHEDULE_TIME: '定时任务时间',
  HTTP_PROXY: 'HTTP 代理',
  LOG_LEVEL: '日志级别',
  WEBUI_PORT: 'WebUI 端口',
  AGENT_MODE: '启用 Agent 模式',
  AGENT_MAX_STEPS: 'Agent 最大步数',
  AGENT_SKILLS: 'Agent 激活技能',
  AGENT_STRATEGY_DIR: 'Agent 策略目录',
  BACKTEST_ENABLED: '启用回测',
  BACKTEST_EVAL_WINDOW_DAYS: '回测评估窗口（交易日）',
  BACKTEST_MIN_AGE_DAYS: '回测最小历史天数',
  BACKTEST_ENGINE_VERSION: '回测引擎版本',
  BACKTEST_NEUTRAL_BAND_PCT: '回测中性区间阈值（%）',
};

const fieldDescriptionMap: Record<string, string> = {
  STOCK_LIST: '使用逗号分隔股票代码，例如：600519,300750。',
  TUSHARE_TOKEN: '用于接入 Tushare Pro 数据服务的凭据。',
  TAVILY_API_KEYS: '用于新闻检索的 Tavily 密钥，支持逗号分隔多个。',
  SERPAPI_API_KEYS: '用于新闻检索的 SerpAPI 密钥，支持逗号分隔多个。',
  BRAVE_API_KEYS: '用于新闻检索的 Brave Search 密钥，支持逗号分隔多个。',
  REALTIME_SOURCE_PRIORITY: '按逗号分隔填写数据源调用优先级。',
  ENABLE_REALTIME_TECHNICAL_INDICATORS: '盘中分析时用实时价计算 MA5/MA10/MA20 与多头排列（Issue #234）；关闭则用昨日收盘。',
  GEMINI_API_KEY: '用于 Gemini 服务调用的密钥。',
  GEMINI_MODEL: '设置 Gemini 分析模型名称。',
  GEMINI_TEMPERATURE: '控制模型输出随机性，范围通常为 0.0 到 2.0。',
  OPENAI_API_KEY: '用于 OpenAI 兼容服务调用的密钥。',
  OPENAI_BASE_URL: 'OpenAI 兼容 API 地址，例如 https://api.deepseek.com/v1。',
  OPENAI_MODEL: 'OpenAI 兼容模型名称，例如 gpt-4o-mini、deepseek-chat。',
  WECHAT_WEBHOOK_URL: '企业微信机器人 Webhook 地址。',
  DINGTALK_APP_KEY: '钉钉应用模式 App Key。',
  DINGTALK_APP_SECRET: '钉钉应用模式 App Secret。',
  PUSHPLUS_TOKEN: 'PushPlus 推送令牌。',
  REPORT_SUMMARY_ONLY: '仅推送分析结果摘要，不包含个股详情。多股时适合快速浏览。',
  SCHEDULE_TIME: '每日定时任务执行时间，格式为 HH:MM。',
  HTTP_PROXY: '网络代理地址，可留空。',
  LOG_LEVEL: '设置日志输出级别。',
  WEBUI_PORT: 'Web 页面服务监听端口。',
  AGENT_MODE: '是否启用 ReAct Agent 进行股票分析。',
  AGENT_MAX_STEPS: 'Agent 思考和调用工具的最大步数。',
  AGENT_SKILLS: '逗号分隔的激活技能/策略列表，例如：trend_following,value_investing。',
  AGENT_STRATEGY_DIR: '存放 Agent 策略 YAML 文件的目录路径。',
  BACKTEST_ENABLED: '是否启用回测功能（true/false）。',
  BACKTEST_EVAL_WINDOW_DAYS: '回测评估窗口长度，单位为交易日。',
  BACKTEST_MIN_AGE_DAYS: '仅回测早于该天数的分析记录。',
  BACKTEST_ENGINE_VERSION: '回测引擎版本标识，用于区分结果版本。',
  BACKTEST_NEUTRAL_BAND_PCT: '中性区间阈值百分比，例如 2 表示 -2%~+2%。',
};

export function getCategoryTitleZh(category: SystemConfigCategory, fallback?: string): string {
  return categoryTitleMap[category] || fallback || category;
}

export function getCategoryDescriptionZh(category: SystemConfigCategory, fallback?: string): string {
  return categoryDescriptionMap[category] || fallback || '';
}

export function getFieldTitleZh(key: string, fallback?: string): string {
  return fieldTitleMap[key] || fallback || key;
}

export function getFieldDescriptionZh(key: string, fallback?: string): string {
  return fieldDescriptionMap[key] || fallback || '';
}
