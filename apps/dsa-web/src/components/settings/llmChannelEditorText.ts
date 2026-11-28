import type { UiLanguage } from '../../i18n/uiText';
import type { LLMApiSurface, LLMCapabilityCheck, LLMCapabilityCheckResult, SystemConfigFieldSchema } from '../../types/systemConfig';

export interface LlmChannelEditorLocale {
  apiSurfaceOptions: Array<{ value: LLMApiSurface; label: string }>;
  invalidApiSurfaceOption: (value: string) => string;
  runtimeCapabilityOptions: Array<{ value: LLMCapabilityCheck; label: string; hint: string }>;
  capabilityStatusLabels: Record<LLMCapabilityCheckResult['status'], string>;
  runtimeOnlyHermesSecretMessage: string;
  helpDocs: NonNullable<SystemConfigFieldSchema['docs']>;
  modelCountConfigured: (count: number) => string;
  modelCountEmpty: string;
  statusConnected: string;
  statusConnectionFailed: string;
  statusTesting: string;
  missingKeyBadge: string;
  removeChannelTooltip: string;
  channelNameLabel: string;
  protocolLabel: string;
  protocolPlaceholder: string;
  apiSurfaceLabel: string;
  apiSurfacePlaceholder: string;
  baseUrlLabel: string;
  baseUrlOfficialPlaceholder: string;
  configReferenceTitle: string;
  officialSourcesPrefix: string;
  capabilityReferenceDisclaimer: string;
  apiKeyLabel: string;
  apiKeyOllamaPlaceholder: string;
  apiKeyMultiPlaceholder: string;
  fetchModelsLoading: string;
  fetchModelsButton: string;
  discoveryDefaultHint: string;
  discoveredModelsLabel: string;
  manualModelsLabelWithDiscovery: string;
  manualModelsLabelDefault: string;
  manualModelsHintWithDiscovery: string;
  manualModelsHintDefault: string;
  extraManualModelsPrefix: string;
  listSeparator: string;
  testConnectionLoading: string;
  testConnectionButton: string;
  firstModelTestNote: (model: string) => string;
  capabilitySectionTitle: string;
  capabilityHelpTitle: string;
  capabilitySectionDesc: string;
  capabilityCheckLoading: string;
  capabilityCheckButton: string;
  currentConfigOption: (model: string) => string;
  stageLabels: Record<string, string>;
  defaultStageLabel: string;
  errorLabels: Record<string, string>;
  defaultErrorLabel: string;
  troubleshootingHints: Record<string, string>;
  formatErrorDiscoveryHint: string;
  formatErrorChatHint: string;
  emptyResponseDiscoveryHint: string;
  reasonHints: Record<string, string>;
  testModelHintPrefix: (model: string) => string;
  testScopeInfo: string;
  testModelActionHint: string;
  failureSummaryWithError: (prefix: string, summary: string, rawError: string) => string;
  failureSummary: (prefix: string, summary: string) => string;
  defaultFailureSummary: string;
  capabilitySummary: (passed: number, failed: number, skipped: number) => string;
  validationEmptyChannelName: string;
  validationMixedHermesRoute: string;
  validationNonCanonicalRouteAlias: string;
  validationInvalidPrimaryModel: string;
  validationInvalidAgentPrimaryModel: string;
  validationInvalidFallbackModel: string;
  validationInvalidVisionModel: string;
  saveSuccessAi: string;
  saveSuccessChannels: string;
  testLoadingText: string;
  testSuccessText: (resolvedModel?: string | null, latencyMs?: number | null) => string;
  testFailureFallback: string;
  discoveryLoadingText: string;
  discoverySuccessText: (count: number, latencyMs?: number | null) => string;
  discoveryFailureFallback: string;
  capabilityCheckingText: string;
  capabilityNoResultsText: string;
  capabilityFailureFallback: string;
  headerTitle: string;
  headerBadge: string;
  headerDesc: string;
  expandLabel: string;
  collapseLabel: string;
  quickAddTitle: string;
  quickAddDesc: string;
  channelCountBadge: (count: number) => string;
  addChannelButton: string;
  selectProviderPlaceholder: string;
  channelListTitle: string;
  enabledChannelsSummary: (enabled: number, total: number) => string;
  emptyChannelsTitle: string;
  emptyChannelsDesc: string;
  runtimeSectionTitle: string;
  runtimeSectionDesc: string;
  runtimeBadge: string;
  temperatureLabel: string;
  temperatureDesc: string;
  noAvailableModelsNotice: string;
  primaryModelLabel: string;
  primaryModelAutoOption: string;
  agentPrimaryModelLabel: string;
  agentPrimaryModelAutoOption: string;
  fallbackModelsLabel: string;
  fallbackModelsDesc: string;
  visionModelLabel: string;
  visionModelAutoOption: string;
  yamlActiveNotice: string;
  savingButton: string;
  saveAiConfigButton: string;
  saveChannelsButton: string;
  noUnsavedChanges: string;
  saveWarningsTitle: string;
}

export const LLM_CHANNEL_EDITOR_TEXT: Record<UiLanguage, LlmChannelEditorLocale> = {
  zh: {
    apiSurfaceOptions: [
      { value: 'chat_completions', label: 'Chat Completions（默认）' },
      { value: 'responses', label: 'Responses API' },
    ],
    invalidApiSurfaceOption: (value) => `无效配置：${value}`,
    runtimeCapabilityOptions: [
      { value: 'json', label: 'JSON', hint: '检测 response_format JSON 输出是否可用。' },
      { value: 'tools', label: 'Tools', hint: '检测 function/tool calling 是否可用。' },
      { value: 'stream', label: 'Stream', hint: '检测流式输出是否能返回有效 chunk。' },
      { value: 'vision', label: 'Vision', hint: '检测当前模型是否接受 image_url 输入。' },
    ],
    capabilityStatusLabels: {
      passed: '通过',
      failed: '失败',
      skipped: '跳过',
    },
    runtimeOnlyHermesSecretMessage: '运行时注入的 Hermes Key 不会回传；如需在设置页测试，请重新输入 Key 或保存到 .env。',
    helpDocs: [
      {
        label: 'LLM 配置指南',
        href: 'https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/LLM_CONFIG_GUIDE.md',
      },
      {
        label: 'LLM 服务商配置速查',
        href: 'https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/llm-providers.md',
      },
    ],
    modelCountConfigured: (count) => `${count} 个模型已配置`,
    modelCountEmpty: '未配置模型',
    statusConnected: '连接正常',
    statusConnectionFailed: '连接失败',
    statusTesting: '测试中',
    missingKeyBadge: '未填 Key',
    removeChannelTooltip: '删除渠道',
    channelNameLabel: '渠道名称',
    protocolLabel: '协议',
    protocolPlaceholder: '选择协议',
    apiSurfaceLabel: 'API Surface',
    apiSurfacePlaceholder: '选择 API Surface',
    baseUrlLabel: 'Base URL',
    baseUrlOfficialPlaceholder: '官方接口可留空',
    configReferenceTitle: '配置参考',
    officialSourcesPrefix: '官方来源：',
    capabilityReferenceDisclaimer: '能力标签仅用于配置参考，不代表运行时能力已验证通过。',
    apiKeyLabel: 'API Key',
    apiKeyOllamaPlaceholder: '本地 Ollama 可留空',
    apiKeyMultiPlaceholder: '支持多个 Key 逗号分隔',
    fetchModelsLoading: '获取中...',
    fetchModelsButton: '获取模型',
    discoveryDefaultHint: '支持 `/models` 的 OpenAI Compatible 渠道可自动拉取模型。',
    discoveredModelsLabel: '可选模型（可多选）',
    manualModelsLabelWithDiscovery: '手动模型（逗号分隔）',
    manualModelsLabelDefault: '模型（逗号分隔）',
    manualModelsHintWithDiscovery: '如有自定义模型名未出现在列表中，可继续手动补充，保存格式仍为逗号分隔。',
    manualModelsHintDefault: '若渠道不支持自动发现或请求失败，可直接手动填写模型列表。',
    extraManualModelsPrefix: '额外手动模型：',
    listSeparator: '，',
    testConnectionLoading: '测试中...',
    testConnectionButton: '测试连接',
    firstModelTestNote: (model) => `基础连接测试默认使用模型列表首项：${model}`,
    capabilitySectionTitle: '运行时能力检测（可选）',
    capabilityHelpTitle: '运行时能力检测',
    capabilitySectionDesc: '仅在手动触发时发起真实 LLM 请求；多选可能需要 20-40 秒。',
    capabilityCheckLoading: '检测中...',
    capabilityCheckButton: '检测能力',
    currentConfigOption: (model) => `${model}（当前配置）`,
    stageLabels: {
      model_discovery: '模型发现',
      chat_completion: '聊天调用',
      responses: 'Responses 调用',
      response_parse: '响应解析',
      capability_json: 'JSON 能力',
      capability_tools: 'Tools 能力',
      capability_stream: 'Stream 能力',
      capability_vision: 'Vision 能力',
    },
    defaultStageLabel: '连接测试',
    errorLabels: {
      auth: '鉴权失败',
      timeout: '请求超时',
      quota: '额度或限流',
      model_not_found: '模型不可用',
      request_blocked: '请求被拦截',
      empty_response: '空响应',
      format_error: '格式异常',
      network_error: '网络异常',
      invalid_config: '配置无效',
      unsupported_protocol: '协议暂不支持',
      capability_unsupported: '能力不支持',
      skipped: '已跳过',
    },
    defaultErrorLabel: '测试失败',
    troubleshootingHints: {
      auth: '请检查 API Key 是否正确、是否有多余空格，以及当前渠道是否需要额外组织/项目权限。',
      timeout: '可重试；若持续超时，请检查 Base URL、网络代理、服务商可用区或本地防火墙。',
      quota: '请检查余额、套餐额度、RPM/TPM 限流或并发设置，必要时稍后重试。',
      model_not_found: '请确认模型名与渠道协议匹配，并先用“获取模型”核对该渠道实际可用模型列表。',
      empty_response: '渠道已连通但未返回正文；可尝试切换兼容模型、关闭额外响应模式后再测试。',
      network_error: '请检查 Base URL、代理、TLS/证书、中转网关或本地网络策略，并可稍后重试。',
      invalid_config: '先补齐协议、Base URL、API Key 和模型配置，再执行一键测试。',
      unsupported_protocol: '当前仅对 OpenAI Compatible / DeepSeek 渠道提供自动模型发现，请改为手动维护模型列表。',
    },
    formatErrorDiscoveryHint: '该渠道返回的 /models 响应格式不兼容，请改为手动填写模型列表。',
    formatErrorChatHint: '返回结构与预期不一致，请确认该渠道兼容 Chat Completions 接口。',
    emptyResponseDiscoveryHint: '该渠道的 /models 接口未返回可用模型 ID；请检查 Base URL 是否指向兼容的模型列表接口，或改为手动填写模型列表。',
    reasonHints: {
      missing_api_key: 'API Key 为空，或逗号分隔后没有任何可用 Key；请填入至少一个有效 Key 后再测试。',
      api_key_rejected: '服务商拒绝了当前 API Key；请检查 Key、组织/项目权限、区域和账号状态。',
      rate_limit: '服务商触发 RPM/TPM 或并发限流；请降低请求频率或稍后重试。',
      insufficient_balance: '服务商返回余额、账单或额度不足；请检查账户余额和套餐状态。',
      quota_exceeded: '服务商返回配额已耗尽；请确认账号套餐、余量和项目额度。',
      provider_blocked: '请求被服务商或中转网关拦截；请检查账号风控、地域限制、模型权限、代理商网关策略、内容安全策略或请求来源限制。',
      dns_error: '域名解析失败；请检查 Base URL 域名、网络代理和 DNS 配置。',
      tls_error: 'TLS/证书握手失败；请检查 HTTPS 证书、中转网关或公司代理策略。',
      connection_refused: '目标服务拒绝连接；请确认 Base URL 端口、服务进程和防火墙配置。',
      model_access_denied: '当前账号无法使用该模型；请确认模型是否已开通、账号是否可见，或模型是否已被禁用。',
      provider_prefix_mismatch: '模型 provider 前缀与当前渠道不匹配；请确认模型名是否应使用该渠道的 OpenAI-compatible 路由。',
      capability_unsupported: '当前模型或兼容层不支持该能力；这不影响基础文本连接，可换模型或关闭该能力依赖。',
    },
    testModelHintPrefix: (model) => `本次测试模型：${model}。`,
    testScopeInfo: '基础连接测试默认只测试模型列表中的第一个模型。',
    testModelActionHint: '若该模型不可用，请调整模型顺序或移除不可用模型后重试。',
    failureSummaryWithError: (prefix, summary, rawError) => `${prefix}：${summary}（原始摘要：${rawError}）`,
    failureSummary: (prefix, summary) => `${prefix}：${summary}`,
    defaultFailureSummary: '测试失败',
    capabilitySummary: (passed, failed, skipped) => `能力检测完成：${passed} 通过 / ${failed} 失败 / ${skipped} 跳过`,
    validationEmptyChannelName: '渠道名称不能为空，且只能包含字母、数字或下划线。',
    validationMixedHermesRoute: 'Mixed Hermes/non-Hermes route 暂不支持作为主生成或备选模型，请选择纯 Hermes 或纯非 Hermes route。',
    validationNonCanonicalRouteAlias: '当前运行时模型使用非规范 route alias，请从下拉框重新选择规范模型。',
    validationInvalidPrimaryModel: '当前主模型不在已启用渠道的模型列表中，请重新选择。',
    validationInvalidAgentPrimaryModel: '当前 Agent 主模型没有 Agent-safe 非 Hermes deployment，请重新选择。',
    validationInvalidFallbackModel: '存在无效的备选模型，请重新选择。',
    validationInvalidVisionModel: '当前 Vision 模型不能包含 Hermes deployment，请重新选择纯非 Hermes route。',
    saveSuccessAi: 'AI 配置已保存',
    saveSuccessChannels: '渠道配置已保存',
    testLoadingText: '测试中...',
    testSuccessText: (resolvedModel, latencyMs) => (
      `连接成功${resolvedModel ? ` · ${resolvedModel}` : ''}${latencyMs ? ` · ${latencyMs} ms` : ''}`
    ),
    testFailureFallback: '测试失败',
    discoveryLoadingText: '正在获取模型列表...',
    discoverySuccessText: (count, latencyMs) => (
      `已获取 ${count} 个模型${latencyMs ? ` · ${latencyMs} ms` : ''}`
    ),
    discoveryFailureFallback: '获取模型失败',
    capabilityCheckingText: '正在检测运行时能力...',
    capabilityNoResultsText: '未返回能力检测结果',
    capabilityFailureFallback: '能力检测失败',
    headerTitle: 'AI 模型配置',
    headerBadge: '渠道管理',
    headerDesc: '添加服务商渠道后可自动获取模型列表并多选，也可继续手动填写。配置会自动同步到 .env 文件。',
    expandLabel: '▶ 展开',
    collapseLabel: '▼ 收起',
    quickAddTitle: '快速添加渠道',
    quickAddDesc: '先选择预设服务商，再一键创建配置草稿。',
    channelCountBadge: (count) => `${count} 个渠道`,
    addChannelButton: '+ 添加渠道',
    selectProviderPlaceholder: '选择服务商',
    channelListTitle: '渠道列表',
    enabledChannelsSummary: (enabled, total) => `${enabled}/${total} 已启用`,
    emptyChannelsTitle: '还没有渠道',
    emptyChannelsDesc: '选择服务商预设后点击“添加渠道”即可开始配置。',
    runtimeSectionTitle: '运行时参数',
    runtimeSectionDesc: '主模型、备选模型、Vision 与 Temperature 会直接写入运行时配置。',
    runtimeBadge: 'Runtime',
    temperatureLabel: 'Temperature',
    temperatureDesc: '控制模型输出随机性，0 为确定性输出，2 为最大随机性，推荐 0.7。',
    noAvailableModelsNotice: '先添加至少一个已启用渠道并填写模型，下面的主模型 / 备选模型 / Vision 选项才会出现。',
    primaryModelLabel: '主模型',
    primaryModelAutoOption: '自动（使用第一个可用模型）',
    agentPrimaryModelLabel: 'Agent 主模型',
    agentPrimaryModelAutoOption: '自动（继承普通分析主模型）',
    fallbackModelsLabel: '备选模型',
    fallbackModelsDesc: '备选模型只会在主模型失败时使用。主模型不会重复加入备选模型。',
    visionModelLabel: 'Vision 模型',
    visionModelAutoOption: '自动（跟随 Vision 默认逻辑）',
    yamlActiveNotice: '检测到已配置高级模型路由 YAML：此处仅管理渠道条目和基础连接信息。运行时主模型 / 备选模型 / Vision / Temperature 仍由下方通用字段决定；若 YAML 解析成功，则以其中的路由与可用模型声明为准，本配置不会覆盖 YAML 文件本身。',
    savingButton: '保存中...',
    saveAiConfigButton: '保存 AI 配置',
    saveChannelsButton: '保存渠道配置',
    noUnsavedChanges: '当前没有未保存的改动',
    saveWarningsTitle: '保存后提示',
  },
  en: {
    apiSurfaceOptions: [
      { value: 'chat_completions', label: 'Chat Completions (Default)' },
      { value: 'responses', label: 'Responses API' },
    ],
    invalidApiSurfaceOption: (value) => `Invalid config: ${value}`,
    runtimeCapabilityOptions: [
      { value: 'json', label: 'JSON', hint: 'Checks whether response_format JSON output works.' },
      { value: 'tools', label: 'Tools', hint: 'Checks whether function/tool calling works.' },
      { value: 'stream', label: 'Stream', hint: 'Checks whether streaming output returns valid chunks.' },
      { value: 'vision', label: 'Vision', hint: 'Checks whether the current model accepts image_url inputs.' },
    ],
    capabilityStatusLabels: {
      passed: 'Passed',
      failed: 'Failed',
      skipped: 'Skipped',
    },
    runtimeOnlyHermesSecretMessage: 'Runtime-injected Hermes keys are not echoed back. Re-enter the key or save it to .env to test from Settings.',
    helpDocs: [
      {
        label: 'LLM Configuration Guide',
        href: 'https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/LLM_CONFIG_GUIDE_EN.md',
      },
      {
        label: 'LLM Provider Reference',
        href: 'https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/llm-providers.md',
      },
    ],
    modelCountConfigured: (count) => `${count} ${count === 1 ? 'model' : 'models'} configured`,
    modelCountEmpty: 'No models configured',
    statusConnected: 'Connected',
    statusConnectionFailed: 'Connection failed',
    statusTesting: 'Testing',
    missingKeyBadge: 'Missing Key',
    removeChannelTooltip: 'Remove channel',
    channelNameLabel: 'Channel Name',
    protocolLabel: 'Protocol',
    protocolPlaceholder: 'Select protocol',
    apiSurfaceLabel: 'API Surface',
    apiSurfacePlaceholder: 'Select API Surface',
    baseUrlLabel: 'Base URL',
    baseUrlOfficialPlaceholder: 'Leave blank for official API',
    configReferenceTitle: 'Config Reference',
    officialSourcesPrefix: 'Official Sources: ',
    capabilityReferenceDisclaimer: 'Capability badges are for configuration reference only and do not guarantee runtime support.',
    apiKeyLabel: 'API Key',
    apiKeyOllamaPlaceholder: 'Leave blank for local Ollama',
    apiKeyMultiPlaceholder: 'Comma-separated for multiple keys',
    fetchModelsLoading: 'Fetching...',
    fetchModelsButton: 'Fetch Models',
    discoveryDefaultHint: 'OpenAI-compatible channels supporting `/models` can auto-fetch available models.',
    discoveredModelsLabel: 'Available Models (Multi-select)',
    manualModelsLabelWithDiscovery: 'Manual Models (comma-separated)',
    manualModelsLabelDefault: 'Models (comma-separated)',
    manualModelsHintWithDiscovery: 'Add any custom model IDs missing from the discovered list; values are saved as a comma-separated string.',
    manualModelsHintDefault: 'Enter model IDs manually if auto-discovery is unsupported or fails.',
    extraManualModelsPrefix: 'Additional manual models: ',
    listSeparator: ', ',
    testConnectionLoading: 'Testing...',
    testConnectionButton: 'Test Connection',
    firstModelTestNote: (model) => `Basic connectivity test uses the first model in the list: ${model}`,
    capabilitySectionTitle: 'Runtime Capability Checks (Optional)',
    capabilityHelpTitle: 'Runtime Capability Checks',
    capabilitySectionDesc: 'Sends live LLM requests only when triggered manually; multi-select checks may take 20-40s.',
    capabilityCheckLoading: 'Checking...',
    capabilityCheckButton: 'Check Capabilities',
    currentConfigOption: (model) => `${model} (current)`,
    stageLabels: {
      model_discovery: 'Model Discovery',
      chat_completion: 'Chat Completion',
      responses: 'Responses Call',
      response_parse: 'Response Parsing',
      capability_json: 'JSON Capability',
      capability_tools: 'Tools Capability',
      capability_stream: 'Stream Capability',
      capability_vision: 'Vision Capability',
    },
    defaultStageLabel: 'Connection Test',
    errorLabels: {
      auth: 'Authentication Failed',
      timeout: 'Request Timeout',
      quota: 'Quota or Rate Limit',
      model_not_found: 'Model Unavailable',
      request_blocked: 'Request Blocked',
      empty_response: 'Empty Response',
      format_error: 'Format Error',
      network_error: 'Network Error',
      invalid_config: 'Invalid Config',
      unsupported_protocol: 'Protocol Not Supported',
      capability_unsupported: 'Capability Unsupported',
      skipped: 'Skipped',
    },
    defaultErrorLabel: 'Test Failed',
    troubleshootingHints: {
      auth: 'Check whether the API Key is valid without extra spaces, and verify organization/project permissions if required.',
      timeout: 'Try again; if timeouts persist, check Base URL, proxy settings, provider region, or firewall rules.',
      quota: 'Check account balance, plan quota, RPM/TPM rate limits, or concurrency limits and try again later.',
      model_not_found: 'Verify that the model name matches the channel protocol, and use "Fetch Models" to inspect available models.',
      empty_response: 'Connected but returned no text content; try a compatible model or disable extra response modes.',
      network_error: 'Check Base URL, proxy, TLS certificates, gateway settings, or local network policies and try again.',
      invalid_config: 'Complete protocol, Base URL, API Key, and model settings before running a connection test.',
      unsupported_protocol: 'Auto-discovery is only available for OpenAI Compatible / DeepSeek channels; maintain the model list manually instead.',
    },
    formatErrorDiscoveryHint: 'The /models response format from this channel is incompatible; enter the model list manually.',
    formatErrorChatHint: 'Unexpected response structure; verify that this channel supports Chat Completions.',
    emptyResponseDiscoveryHint: 'The /models endpoint returned no usable model IDs; check that Base URL targets a compatible models endpoint or enter models manually.',
    reasonHints: {
      missing_api_key: 'API Key is empty or contains no valid comma-separated key; enter at least one valid key before testing.',
      api_key_rejected: 'Provider rejected this API Key; check the key value, org/project permissions, region, and account status.',
      rate_limit: 'Provider triggered RPM/TPM or concurrency rate limits; reduce request frequency or retry later.',
      insufficient_balance: 'Provider reported insufficient balance, billing issue, or quota exhaustion; check your billing status.',
      quota_exceeded: 'Provider reported exhausted quota; check your plan limits, credits, and project quota.',
      provider_blocked: 'Request was blocked by the provider or gateway; check risk controls, geo restrictions, model permissions, content policy, or origin rules.',
      dns_error: 'DNS resolution failed; check the Base URL hostname, proxy, and DNS configuration.',
      tls_error: 'TLS/certificate handshake failed; check HTTPS certificates, relay gateway, or corporate proxy rules.',
      connection_refused: 'Target service refused connection; check the Base URL port, service process, and firewall.',
      model_access_denied: 'This account does not have access to the model; confirm the model is enabled and not restricted.',
      provider_prefix_mismatch: 'Model provider prefix does not match this channel; confirm whether it should use OpenAI-compatible routing.',
      capability_unsupported: 'The selected model or compatibility layer does not support this capability; basic text calls still work, or you can switch models.',
    },
    testModelHintPrefix: (model) => `Tested model: ${model}.`,
    testScopeInfo: 'Basic connectivity tests only check the first model in the list.',
    testModelActionHint: 'If this model is unavailable, reorder or remove it and retry.',
    failureSummaryWithError: (prefix, summary, rawError) => `${prefix}: ${summary} (raw error: ${rawError})`,
    failureSummary: (prefix, summary) => `${prefix}: ${summary}`,
    defaultFailureSummary: 'Test failed',
    capabilitySummary: (passed, failed, skipped) => `Capability checks complete: ${passed} passed / ${failed} failed / ${skipped} skipped`,
    validationEmptyChannelName: 'Channel name cannot be empty and may only contain lowercase letters, numbers, or underscores.',
    validationMixedHermesRoute: 'Mixed Hermes/non-Hermes routes are not supported as primary or fallback models; select a pure Hermes or non-Hermes route.',
    validationNonCanonicalRouteAlias: 'A runtime model uses a non-canonical route alias; reselect a canonical model from the dropdown.',
    validationInvalidPrimaryModel: 'The primary model is not in any enabled channel model list; please reselect.',
    validationInvalidAgentPrimaryModel: 'The Agent primary model has no Agent-safe non-Hermes deployment; please reselect.',
    validationInvalidFallbackModel: 'One or more fallback models are invalid; please reselect.',
    validationInvalidVisionModel: 'The Vision model cannot use a Hermes deployment; please select a non-Hermes route.',
    saveSuccessAi: 'AI configuration saved',
    saveSuccessChannels: 'Channel configuration saved',
    testLoadingText: 'Testing...',
    testSuccessText: (resolvedModel, latencyMs) => (
      `Connected${resolvedModel ? ` · ${resolvedModel}` : ''}${latencyMs ? ` · ${latencyMs} ms` : ''}`
    ),
    testFailureFallback: 'Test failed',
    discoveryLoadingText: 'Fetching model list...',
    discoverySuccessText: (count, latencyMs) => (
      `Fetched ${count} ${count === 1 ? 'model' : 'models'}${latencyMs ? ` · ${latencyMs} ms` : ''}`
    ),
    discoveryFailureFallback: 'Failed to fetch models',
    capabilityCheckingText: 'Checking runtime capabilities...',
    capabilityNoResultsText: 'No capability check results returned',
    capabilityFailureFallback: 'Capability check failed',
    headerTitle: 'AI Model Configuration',
    headerBadge: 'Channel Manager',
    headerDesc: 'Add provider channels to auto-fetch and multi-select models, or enter them manually. Settings sync to your .env file.',
    expandLabel: '▶ Expand',
    collapseLabel: '▼ Collapse',
    quickAddTitle: 'Quick Add Channel',
    quickAddDesc: 'Select a preset provider to create a channel configuration draft.',
    channelCountBadge: (count) => `${count} ${count === 1 ? 'channel' : 'channels'}`,
    addChannelButton: '+ Add Channel',
    selectProviderPlaceholder: 'Select provider',
    channelListTitle: 'Channels',
    enabledChannelsSummary: (enabled, total) => `${enabled}/${total} enabled`,
    emptyChannelsTitle: 'No channels configured',
    emptyChannelsDesc: 'Select a provider preset above and click "+ Add Channel" to get started.',
    runtimeSectionTitle: 'Runtime Parameters',
    runtimeSectionDesc: 'Primary model, fallback models, Vision, and Temperature are saved directly to runtime configuration.',
    runtimeBadge: 'Runtime',
    temperatureLabel: 'Temperature',
    temperatureDesc: 'Controls model randomness (0 = deterministic, 2 = maximum randomness; 0.7 recommended).',
    noAvailableModelsNotice: 'Add at least one enabled channel with models to unlock Primary, Fallback, and Vision model options below.',
    primaryModelLabel: 'Primary Model',
    primaryModelAutoOption: 'Auto (use first available model)',
    agentPrimaryModelLabel: 'Agent Primary Model',
    agentPrimaryModelAutoOption: 'Auto (inherit primary analysis model)',
    fallbackModelsLabel: 'Fallback Models',
    fallbackModelsDesc: 'Fallback models are only used when the primary model fails. The primary model is not duplicated in fallbacks.',
    visionModelLabel: 'Vision Model',
    visionModelAutoOption: 'Auto (follow Vision default routing)',
    yamlActiveNotice: 'Advanced model routing YAML detected: this panel only manages channel entries and connectivity. Runtime primary, fallback, Vision models, and Temperature remain controlled by the general fields below (or by parsed YAML routes, without overwriting your YAML file).',
    savingButton: 'Saving...',
    saveAiConfigButton: 'Save AI Config',
    saveChannelsButton: 'Save Channel Config',
    noUnsavedChanges: 'No unsaved changes',
    saveWarningsTitle: 'Post-save Notices',
  },
};
