# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 配置管理模块
===================================

职责：
1. 使用单例模式管理全局配置
2. 从 .env 文件加载敏感配置
3. 提供类型安全的配置访问接口
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from dotenv import load_dotenv, dotenv_values
from dataclasses import dataclass, field


def setup_env(override: bool = False):
    """
    Initialize environment variables from .env file.

    Args:
        override: If True, overwrite existing environment variables with values
                  from .env file. Set to True when reloading config after updates.
                  Default is False to preserve behavior on initial load where
                  system environment variables take precedence.
    """
    # src/config.py -> src/ -> root
    env_file = os.getenv("ENV_FILE")
    if env_file:
        env_path = Path(env_file)
    else:
        env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(dotenv_path=env_path, override=override)


@dataclass
class Config:
    """
    系统配置类 - 单例模式
    
    设计说明：
    - 使用 dataclass 简化配置属性定义
    - 所有配置项从环境变量读取，支持默认值
    - 类方法 get_instance() 实现单例访问
    """
    
    # === 自选股配置 ===
    stock_list: List[str] = field(default_factory=list)

    # === 飞书云文档配置 ===
    feishu_app_id: Optional[str] = None
    feishu_app_secret: Optional[str] = None
    feishu_folder_token: Optional[str] = None  # 目标文件夹 Token

    # === 数据源 API Token ===
    tushare_token: Optional[str] = None
    
    # === AI 分析配置 ===
    # LiteLLM unified model config (provider/model format, e.g. gemini/gemini-2.5-flash)
    litellm_model: str = ""  # Primary model; must include provider prefix when set explicitly
    litellm_fallback_models: List[str] = field(default_factory=list)  # Cross-model fallback list

    # Multi-key support: each list is parsed from *_API_KEYS (comma-separated) with single-key fallback
    gemini_api_keys: List[str] = field(default_factory=list)
    anthropic_api_keys: List[str] = field(default_factory=list)
    openai_api_keys: List[str] = field(default_factory=list)

    # Legacy single-key fields (kept for backward compatibility; gemini_api_keys[0] when set)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3-flash-preview"  # 主模型
    gemini_model_fallback: str = "gemini-2.5-flash"  # 备选模型
    gemini_temperature: float = 0.7  # 温度参数（0.0-2.0，控制输出随机性，默认0.7）

    # Gemini API 请求配置（防止 429 限流）
    gemini_request_delay: float = 2.0  # 请求间隔（秒）
    gemini_max_retries: int = 5  # 最大重试次数
    gemini_retry_delay: float = 5.0  # 重试基础延时（秒）

    # Anthropic Claude API（备选，当 Gemini 不可用时使用）
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-5-sonnet-20241022"  # Claude model name
    anthropic_temperature: float = 0.7  # Anthropic temperature (0.0-1.0, default 0.7)
    anthropic_max_tokens: int = 8192  # Max tokens for Anthropic responses

    # OpenAI 兼容 API（备选，当 Gemini/Anthropic 不可用时使用）
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # 如: https://api.openai.com/v1
    openai_model: str = "gpt-4o-mini"  # OpenAI 兼容模型名称
    openai_vision_model: Optional[str] = None  # Vision 专用模型（可选，不配置则用 openai_model；部分模型如 DeepSeek 不支持图像）
    openai_temperature: float = 0.7  # OpenAI 温度参数（0.0-2.0，默认0.7）

    # === 搜索引擎配置（支持多 Key 负载均衡）===
    bocha_api_keys: List[str] = field(default_factory=list)  # Bocha API Keys
    tavily_api_keys: List[str] = field(default_factory=list)  # Tavily API Keys
    brave_api_keys: List[str] = field(default_factory=list)  # Brave Search API Keys
    serpapi_keys: List[str] = field(default_factory=list)  # SerpAPI Keys

    # === 新闻与分析筛选配置 ===
    news_max_age_days: int = 3   # 新闻最大时效（天）
    bias_threshold: float = 5.0  # 乖离率阈值（%），超过此值提示不追高

    # === Agent 模式配置 ===
    agent_mode: bool = False
    agent_max_steps: int = 10
    agent_skills: List[str] = field(default_factory=list)
    agent_strategy_dir: Optional[str] = None

    # === 通知配置（可同时配置多个，全部推送）===
    
    # 企业微信 Webhook
    wechat_webhook_url: Optional[str] = None
    
    # 飞书 Webhook
    feishu_webhook_url: Optional[str] = None
    
    # Telegram 配置（需要同时配置 Bot Token 和 Chat ID）
    telegram_bot_token: Optional[str] = None  # Bot Token（@BotFather 获取）
    telegram_chat_id: Optional[str] = None  # Chat ID
    telegram_message_thread_id: Optional[str] = None  # Topic ID (Message Thread ID) for groups
    
    # 邮件配置（只需邮箱和授权码，SMTP 自动识别）
    email_sender: Optional[str] = None  # 发件人邮箱
    email_sender_name: str = "daily_stock_analysis股票分析助手"  # 发件人显示名称
    email_password: Optional[str] = None  # 邮箱密码/授权码
    email_receivers: List[str] = field(default_factory=list)  # 收件人列表（留空则发给自己）

    # Stock-to-email group routing (Issue #268): STOCK_GROUP_N + EMAIL_GROUP_N
    # When configured, each group's report is sent to that group's emails only.
    stock_email_groups: List[Tuple[List[str], List[str]]] = field(default_factory=list)

    # Pushover 配置（手机/桌面推送通知）
    pushover_user_key: Optional[str] = None  # 用户 Key（https://pushover.net 获取）
    pushover_api_token: Optional[str] = None  # 应用 API Token
    
    # 自定义 Webhook（支持多个，逗号分隔）
    # 适用于：钉钉、Discord、Slack、自建服务等任意支持 POST JSON 的 Webhook
    custom_webhook_urls: List[str] = field(default_factory=list)
    custom_webhook_bearer_token: Optional[str] = None  # Bearer Token（用于需要认证的 Webhook）
    webhook_verify_ssl: bool = True  # Webhook HTTPS 证书校验，false 可支持自签名（有 MITM 风险）

    # Discord 通知配置
    discord_bot_token: Optional[str] = None  # Discord Bot Token
    discord_main_channel_id: Optional[str] = None  # Discord 主频道 ID
    discord_webhook_url: Optional[str] = None  # Discord Webhook URL

    # AstrBot 通知配置
    astrbot_token: Optional[str] = None
    astrbot_url: Optional[str] = None

    # 单股推送模式：每分析完一只股票立即推送，而不是汇总后推送
    single_stock_notify: bool = False

    # 报告类型：simple(精简) 或 full(完整)
    report_type: str = "simple"

    # 仅分析结果摘要：true 时只推送汇总，不含个股详情（Issue #262）
    report_summary_only: bool = False

    # PushPlus 推送配置
    pushplus_token: Optional[str] = None  # PushPlus Token
    pushplus_topic: Optional[str] = None  # PushPlus 群组编码（一对多推送）

    # Server酱3 推送配置
    serverchan3_sendkey: Optional[str] = None  # Server酱3 SendKey

    # 分析间隔时间（秒）- 用于避免API限流
    analysis_delay: float = 0.0  # 个股分析与大盘分析之间的延迟

    # Merge stock + market report into one notification (Issue #190)
    merge_email_notification: bool = False

    # 消息长度限制（字节）- 超长自动分批发送
    feishu_max_bytes: int = 20000  # 飞书限制约 20KB，默认 20000 字节
    wechat_max_bytes: int = 4000   # 企业微信限制 4096 字节，默认 4000 字节
    discord_max_words: int = 2000  # Discord 限制 2000 字，默认 2000 字
    wechat_msg_type: str = "markdown"  # 企业微信消息类型，默认 markdown 类型

    # Markdown 转图片（Issue #289）：对不支持 Markdown 的渠道以图片发送
    markdown_to_image_channels: List[str] = field(default_factory=list)  # 逗号分隔：telegram,wechat,custom,email
    markdown_to_image_max_chars: int = 15000  # 超过此长度不转换，避免超大图片

    # === 数据库配置 ===
    database_path: str = "./data/stock_analysis.db"

    # 是否保存分析上下文快照（用于历史回溯）
    save_context_snapshot: bool = True

    # === 回测配置 ===
    backtest_enabled: bool = True
    backtest_eval_window_days: int = 10
    backtest_min_age_days: int = 14
    backtest_engine_version: str = "v1"
    backtest_neutral_band_pct: float = 2.0
    
    # === 日志配置 ===
    log_dir: str = "./logs"  # 日志文件目录
    log_level: str = "INFO"  # 日志级别
    
    # === 系统配置 ===
    max_workers: int = 3  # 低并发防封禁
    debug: bool = False
    http_proxy: Optional[str] = None  # HTTP 代理 (例如: http://127.0.0.1:10809)
    https_proxy: Optional[str] = None # HTTPS 代理
    
    # === 定时任务配置 ===
    schedule_enabled: bool = False            # 是否启用定时任务
    schedule_time: str = "18:00"              # 每日推送时间（HH:MM 格式）
    schedule_run_immediately: bool = True     # 启动时是否立即执行一次
    run_immediately: bool = True              # 启动时是否立即执行一次（非定时模式）
    market_review_enabled: bool = True        # 是否启用大盘复盘
    # 大盘复盘市场区域：cn(A股)、us(美股)、both(两者)，us 适合仅关注美股的用户
    market_review_region: str = "cn"
    # 交易日检查：默认启用，非交易日跳过执行；设为 false 或 --force-run 可强制执行（Issue #373）
    trading_day_check_enabled: bool = True

    # === 实时行情增强数据配置 ===
    # 实时行情开关（关闭后使用历史收盘价进行分析）
    enable_realtime_quote: bool = True
    # 盘中实时技术面：启用时用实时价计算 MA/多头排列（Issue #234）；关闭则用昨日收盘
    enable_realtime_technical_indicators: bool = True
    # 筹码分布开关（该接口不稳定，云端部署建议关闭）
    enable_chip_distribution: bool = True
    # 东财接口补丁开关
    enable_eastmoney_patch: bool = False
    # 实时行情数据源优先级（逗号分隔）
    # 推荐顺序：tencent > akshare_sina > efinance > akshare_em > tushare
    # - tencent: 腾讯财经，有量比/换手率/市盈率等，单股查询稳定（推荐）
    # - akshare_sina: 新浪财经，基本行情稳定，但无量比
    # - efinance/akshare_em: 东财全量接口，数据最全但容易被封
    # - tushare: Tushare Pro，需要2000积分，数据全面（付费用户可优先使用）
    realtime_source_priority: str = "tencent,akshare_sina,efinance,akshare_em"
    # 实时行情缓存时间（秒）
    realtime_cache_ttl: int = 600
    # 熔断器冷却时间（秒）
    circuit_breaker_cooldown: int = 300

    # Discord 机器人状态
    discord_bot_status: str = "A股智能分析 | /help"

    # === 流控配置（防封禁关键参数）===
    # Akshare 请求间隔范围（秒）
    akshare_sleep_min: float = 2.0
    akshare_sleep_max: float = 5.0
    
    # Tushare 每分钟最大请求数（免费配额）
    tushare_rate_limit_per_minute: int = 80
    
    # 重试配置
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    
    # === WebUI 配置 ===
    webui_enabled: bool = False
    webui_host: str = "127.0.0.1"
    webui_port: int = 8000
    
    # === 机器人配置 ===
    bot_enabled: bool = True              # 是否启用机器人功能
    bot_command_prefix: str = "/"         # 命令前缀
    bot_rate_limit_requests: int = 10     # 频率限制：窗口内最大请求数
    bot_rate_limit_window: int = 60       # 频率限制：窗口时间（秒）
    bot_admin_users: List[str] = field(default_factory=list)  # 管理员用户 ID 列表
    
    # 飞书机器人（事件订阅）- 已有 feishu_app_id, feishu_app_secret
    feishu_verification_token: Optional[str] = None  # 事件订阅验证 Token
    feishu_encrypt_key: Optional[str] = None         # 消息加密密钥（可选）
    feishu_stream_enabled: bool = False              # 是否启用 Stream 长连接模式（无需公网IP）
    
    # 钉钉机器人
    dingtalk_app_key: Optional[str] = None      # 应用 AppKey
    dingtalk_app_secret: Optional[str] = None   # 应用 AppSecret
    dingtalk_stream_enabled: bool = False       # 是否启用 Stream 模式（无需公网IP）
    
    # 企业微信机器人（回调模式）
    wecom_corpid: Optional[str] = None              # 企业 ID
    wecom_token: Optional[str] = None               # 回调 Token
    wecom_encoding_aes_key: Optional[str] = None    # 消息加解密密钥
    wecom_agent_id: Optional[str] = None            # 应用 AgentId
    
    # Telegram 机器人 - 已有 telegram_bot_token, telegram_chat_id
    telegram_webhook_secret: Optional[str] = None   # Webhook 密钥
        
    # 单例实例存储
    _instance: Optional['Config'] = None
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """
        获取配置单例实例
        
        单例模式确保：
        1. 全局只有一个配置实例
        2. 配置只从环境变量加载一次
        3. 所有模块共享相同配置
        """
        if cls._instance is None:
            cls._instance = cls._load_from_env()
        return cls._instance
    
    @classmethod
    def _load_from_env(cls) -> 'Config':
        """
        从 .env 文件加载配置
        
        加载优先级：
        1. 系统环境变量
        2. .env 文件
        3. 代码中的默认值
        """
        # 确保环境变量已加载
        setup_env()

        # === 智能代理配置 (关键修复) ===
        # 如果配置了代理，自动设置 NO_PROXY 以排除国内数据源，避免行情获取失败
        http_proxy = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
        if http_proxy:
            # 国内金融数据源域名列表
            domestic_domains = [
                'eastmoney.com',   # 东方财富 (Efinance/Akshare)
                'sina.com.cn',     # 新浪财经 (Akshare)
                '163.com',         # 网易财经 (Akshare)
                'tushare.pro',     # Tushare
                'baostock.com',    # Baostock
                'sse.com.cn',      # 上交所
                'szse.cn',         # 深交所
                'csindex.com.cn',  # 中证指数
                'cninfo.com.cn',   # 巨潮资讯
                'localhost',
                '127.0.0.1'
            ]

            # 获取现有的 no_proxy
            current_no_proxy = os.getenv('NO_PROXY') or os.getenv('no_proxy') or ''
            existing_domains = current_no_proxy.split(',') if current_no_proxy else []

            # 合并去重
            final_domains = list(set(existing_domains + domestic_domains))
            final_no_proxy = ','.join(filter(None, final_domains))

            # 设置环境变量 (requests/urllib3/aiohttp 都会遵守此设置)
            os.environ['NO_PROXY'] = final_no_proxy
            os.environ['no_proxy'] = final_no_proxy

            # 确保 HTTP_PROXY 也被正确设置（以防仅在 .env 中定义但未导出）
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy

            # HTTPS_PROXY 同理
            https_proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
            if https_proxy:
                os.environ['HTTPS_PROXY'] = https_proxy
                os.environ['https_proxy'] = https_proxy

        
        # 解析自选股列表（逗号分隔，统一为大写 Issue #355）
        stock_list_str = os.getenv('STOCK_LIST', '')
        stock_list = [
            (c or "").strip().upper()
            for c in stock_list_str.split(',')
            if (c or "").strip()
        ]
        
        # 如果没有配置，使用默认的示例股票
        if not stock_list:
            stock_list = ['600519', '000001', '300750']
        
        # === LiteLLM multi-key parsing ===
        # GEMINI_API_KEYS (comma-separated) > GEMINI_API_KEY (single)
        _gemini_keys_raw = os.getenv('GEMINI_API_KEYS', '')
        gemini_api_keys = [k.strip() for k in _gemini_keys_raw.split(',') if k.strip()]
        _single_gemini = os.getenv('GEMINI_API_KEY', '').strip()
        if not gemini_api_keys and _single_gemini:
            gemini_api_keys = [_single_gemini]

        # ANTHROPIC_API_KEYS > ANTHROPIC_API_KEY
        _anthropic_keys_raw = os.getenv('ANTHROPIC_API_KEYS', '')
        anthropic_api_keys = [k.strip() for k in _anthropic_keys_raw.split(',') if k.strip()]
        _single_anthropic = os.getenv('ANTHROPIC_API_KEY', '').strip()
        if not anthropic_api_keys and _single_anthropic:
            anthropic_api_keys = [_single_anthropic]

        # OPENAI_API_KEYS > AIHUBMIX_KEY > OPENAI_API_KEY
        _openai_keys_raw = os.getenv('OPENAI_API_KEYS', '')
        openai_api_keys = [k.strip() for k in _openai_keys_raw.split(',') if k.strip()]
        if not openai_api_keys:
            _aihubmix = os.getenv('AIHUBMIX_KEY', '').strip()
            _single_openai = os.getenv('OPENAI_API_KEY', '').strip()
            _fallback_key = _aihubmix or _single_openai
            if _fallback_key:
                openai_api_keys = [_fallback_key]

        # LITELLM_MODEL: explicit config takes precedence; else infer from available keys
        litellm_model = os.getenv('LITELLM_MODEL', '').strip()
        if not litellm_model:
            _gemini_model_name = os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview').strip()
            _anthropic_model_name = os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022').strip()
            _openai_model_name = os.getenv('OPENAI_MODEL', 'gpt-4o-mini').strip()
            if gemini_api_keys:
                litellm_model = f'gemini/{_gemini_model_name}'
            elif anthropic_api_keys:
                litellm_model = f'anthropic/{_anthropic_model_name}'
            elif openai_api_keys:
                # For openai-compatible models, add prefix only if not already prefixed
                if '/' not in _openai_model_name:
                    litellm_model = f'openai/{_openai_model_name}'
                else:
                    litellm_model = _openai_model_name

        # LITELLM_FALLBACK_MODELS: comma-separated list of fallback models
        _fallback_str = os.getenv('LITELLM_FALLBACK_MODELS', '')
        if _fallback_str.strip():
            litellm_fallback_models = [m.strip() for m in _fallback_str.split(',') if m.strip()]
        else:
            # Backward compat: use gemini_model_fallback when primary is gemini
            _gemini_fallback = os.getenv('GEMINI_MODEL_FALLBACK', 'gemini-2.5-flash').strip()
            if litellm_model.startswith('gemini/') and _gemini_fallback:
                _fb = f'gemini/{_gemini_fallback}' if '/' not in _gemini_fallback else _gemini_fallback
                litellm_fallback_models = [_fb]
            else:
                litellm_fallback_models = []

        # 解析搜索引擎 API Keys（支持多个 key，逗号分隔）
        bocha_keys_str = os.getenv('BOCHA_API_KEYS', '')
        bocha_api_keys = [k.strip() for k in bocha_keys_str.split(',') if k.strip()]
        
        tavily_keys_str = os.getenv('TAVILY_API_KEYS', '')
        tavily_api_keys = [k.strip() for k in tavily_keys_str.split(',') if k.strip()]
        
        serpapi_keys_str = os.getenv('SERPAPI_API_KEYS', '')
        serpapi_keys = [k.strip() for k in serpapi_keys_str.split(',') if k.strip()]

        brave_keys_str = os.getenv('BRAVE_API_KEYS', '')
        brave_api_keys = [k.strip() for k in brave_keys_str.split(',') if k.strip()]

        # 企微消息类型与最大字节数逻辑
        wechat_msg_type = os.getenv('WECHAT_MSG_TYPE', 'markdown')
        wechat_msg_type_lower = wechat_msg_type.lower()
        wechat_max_bytes_env = os.getenv('WECHAT_MAX_BYTES')
        if wechat_max_bytes_env not in (None, ''):
            wechat_max_bytes = int(wechat_max_bytes_env)
        else:
            # 未显式配置时，根据消息类型选择默认字节数
            wechat_max_bytes = 2048 if wechat_msg_type_lower == 'text' else 4000
        
        return cls(
            stock_list=stock_list,
            feishu_app_id=os.getenv('FEISHU_APP_ID'),
            feishu_app_secret=os.getenv('FEISHU_APP_SECRET'),
            feishu_folder_token=os.getenv('FEISHU_FOLDER_TOKEN'),
            tushare_token=os.getenv('TUSHARE_TOKEN'),
            litellm_model=litellm_model,
            litellm_fallback_models=litellm_fallback_models,
            gemini_api_keys=gemini_api_keys,
            anthropic_api_keys=anthropic_api_keys,
            openai_api_keys=openai_api_keys,
            gemini_api_key=os.getenv('GEMINI_API_KEY'),
            gemini_model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'),
            gemini_model_fallback=os.getenv('GEMINI_MODEL_FALLBACK', 'gemini-2.5-flash'),
            gemini_temperature=float(os.getenv('GEMINI_TEMPERATURE', '0.7')),
            gemini_request_delay=float(os.getenv('GEMINI_REQUEST_DELAY', '2.0')),
            gemini_max_retries=int(os.getenv('GEMINI_MAX_RETRIES', '5')),
            gemini_retry_delay=float(os.getenv('GEMINI_RETRY_DELAY', '5.0')),
            anthropic_api_key=os.getenv('ANTHROPIC_API_KEY'),
            anthropic_model=os.getenv('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022'),
            anthropic_temperature=float(os.getenv('ANTHROPIC_TEMPERATURE', '0.7')),
            anthropic_max_tokens=int(os.getenv('ANTHROPIC_MAX_TOKENS', '8192')),
            # AIHubmix is the preferred OpenAI-compatible provider (one key, all models, no VPN required).
            # Within the OpenAI-compatible layer: AIHUBMIX_KEY takes priority over OPENAI_API_KEY.
            # Overall provider fallback order: Gemini > Anthropic > OpenAI-compatible (incl. AIHubmix).
            # base_url is auto-set to aihubmix.com/v1 when AIHUBMIX_KEY is used and no explicit
            # OPENAI_BASE_URL override is provided.
            # Model names match upstream (e.g. gemini-3.1-pro-preview, gpt-4o, gpt-4o-free, deepseek-chat).
            openai_api_key=os.getenv('AIHUBMIX_KEY') or os.getenv('OPENAI_API_KEY') or None,
            openai_base_url=os.getenv('OPENAI_BASE_URL') or (
                'https://aihubmix.com/v1' if os.getenv('AIHUBMIX_KEY') else None
            ),  # noqa: E501
            openai_model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
            openai_vision_model=os.getenv('OPENAI_VISION_MODEL') or None,
            openai_temperature=float(os.getenv('OPENAI_TEMPERATURE', '0.7')),
            bocha_api_keys=bocha_api_keys,
            tavily_api_keys=tavily_api_keys,
            brave_api_keys=brave_api_keys,
            serpapi_keys=serpapi_keys,
            news_max_age_days=max(1, int(os.getenv('NEWS_MAX_AGE_DAYS', '3'))),
            bias_threshold=max(1.0, float(os.getenv('BIAS_THRESHOLD', '5.0'))),
            agent_mode=os.getenv('AGENT_MODE', 'false').lower() == 'true',
            agent_max_steps=int(os.getenv('AGENT_MAX_STEPS', '10')),
            agent_skills=[s.strip() for s in os.getenv('AGENT_SKILLS', '').split(',') if s.strip()],
            agent_strategy_dir=os.getenv('AGENT_STRATEGY_DIR'),
            wechat_webhook_url=os.getenv('WECHAT_WEBHOOK_URL'),
            feishu_webhook_url=os.getenv('FEISHU_WEBHOOK_URL'),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID'),
            telegram_message_thread_id=os.getenv('TELEGRAM_MESSAGE_THREAD_ID'),
            email_sender=os.getenv('EMAIL_SENDER'),
            email_sender_name=os.getenv('EMAIL_SENDER_NAME', 'daily_stock_analysis股票分析助手'),
            email_password=os.getenv('EMAIL_PASSWORD'),
            email_receivers=[r.strip() for r in os.getenv('EMAIL_RECEIVERS', '').split(',') if r.strip()],
            stock_email_groups=cls._parse_stock_email_groups(),
            pushover_user_key=os.getenv('PUSHOVER_USER_KEY'),
            pushover_api_token=os.getenv('PUSHOVER_API_TOKEN'),
            pushplus_token=os.getenv('PUSHPLUS_TOKEN'),
            pushplus_topic=os.getenv('PUSHPLUS_TOPIC'),
            serverchan3_sendkey=os.getenv('SERVERCHAN3_SENDKEY'),
            custom_webhook_urls=[u.strip() for u in os.getenv('CUSTOM_WEBHOOK_URLS', '').split(',') if u.strip()],
            custom_webhook_bearer_token=os.getenv('CUSTOM_WEBHOOK_BEARER_TOKEN'),
            webhook_verify_ssl=os.getenv('WEBHOOK_VERIFY_SSL', 'true').lower() == 'true',
            discord_bot_token=os.getenv('DISCORD_BOT_TOKEN'),
            discord_main_channel_id=os.getenv('DISCORD_MAIN_CHANNEL_ID'),
            discord_webhook_url=os.getenv('DISCORD_WEBHOOK_URL'),
            astrbot_url=os.getenv('ASTRBOT_URL'),
            astrbot_token=os.getenv('ASTRBOT_TOKEN'),
            single_stock_notify=os.getenv('SINGLE_STOCK_NOTIFY', 'false').lower() == 'true',
            report_type=os.getenv('REPORT_TYPE', 'simple').lower(),
            report_summary_only=os.getenv('REPORT_SUMMARY_ONLY', 'false').lower() == 'true',
            analysis_delay=float(os.getenv('ANALYSIS_DELAY', '0')),
            merge_email_notification=os.getenv('MERGE_EMAIL_NOTIFICATION', 'false').lower() == 'true',
            feishu_max_bytes=int(os.getenv('FEISHU_MAX_BYTES', '20000')),
            wechat_max_bytes=wechat_max_bytes,
            wechat_msg_type=wechat_msg_type_lower,
            discord_max_words=int(os.getenv('DISCORD_MAX_WORDS', '2000')),
            markdown_to_image_channels=[
                c.strip().lower()
                for c in os.getenv('MARKDOWN_TO_IMAGE_CHANNELS', '').split(',')
                if c.strip()
            ],
            markdown_to_image_max_chars=int(os.getenv('MARKDOWN_TO_IMAGE_MAX_CHARS', '15000')),
            database_path=os.getenv('DATABASE_PATH', './data/stock_analysis.db'),
            save_context_snapshot=os.getenv('SAVE_CONTEXT_SNAPSHOT', 'true').lower() == 'true',
            backtest_enabled=os.getenv('BACKTEST_ENABLED', 'true').lower() == 'true',
            backtest_eval_window_days=int(os.getenv('BACKTEST_EVAL_WINDOW_DAYS', '10')),
            backtest_min_age_days=int(os.getenv('BACKTEST_MIN_AGE_DAYS', '14')),
            backtest_engine_version=os.getenv('BACKTEST_ENGINE_VERSION', 'v1'),
            backtest_neutral_band_pct=float(os.getenv('BACKTEST_NEUTRAL_BAND_PCT', '2.0')),
            log_dir=os.getenv('LOG_DIR', './logs'),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            max_workers=int(os.getenv('MAX_WORKERS', '3')),
            debug=os.getenv('DEBUG', 'false').lower() == 'true',
            http_proxy=os.getenv('HTTP_PROXY'),
            https_proxy=os.getenv('HTTPS_PROXY'),
            schedule_enabled=os.getenv('SCHEDULE_ENABLED', 'false').lower() == 'true',
            schedule_time=os.getenv('SCHEDULE_TIME', '18:00'),
            schedule_run_immediately=os.getenv('SCHEDULE_RUN_IMMEDIATELY', 'true').lower() == 'true',
            run_immediately=os.getenv('RUN_IMMEDIATELY', 'true').lower() == 'true',
            market_review_enabled=os.getenv('MARKET_REVIEW_ENABLED', 'true').lower() == 'true',
            market_review_region=cls._parse_market_review_region(
                os.getenv('MARKET_REVIEW_REGION', 'cn')
            ),
            trading_day_check_enabled=os.getenv('TRADING_DAY_CHECK_ENABLED', 'true').lower() != 'false',
            webui_enabled=os.getenv('WEBUI_ENABLED', 'false').lower() == 'true',
            webui_host=os.getenv('WEBUI_HOST', '127.0.0.1'),
            webui_port=int(os.getenv('WEBUI_PORT', '8000')),
            # 机器人配置
            bot_enabled=os.getenv('BOT_ENABLED', 'true').lower() == 'true',
            bot_command_prefix=os.getenv('BOT_COMMAND_PREFIX', '/'),
            bot_rate_limit_requests=int(os.getenv('BOT_RATE_LIMIT_REQUESTS', '10')),
            bot_rate_limit_window=int(os.getenv('BOT_RATE_LIMIT_WINDOW', '60')),
            bot_admin_users=[u.strip() for u in os.getenv('BOT_ADMIN_USERS', '').split(',') if u.strip()],
            # 飞书机器人
            feishu_verification_token=os.getenv('FEISHU_VERIFICATION_TOKEN'),
            feishu_encrypt_key=os.getenv('FEISHU_ENCRYPT_KEY'),
            feishu_stream_enabled=os.getenv('FEISHU_STREAM_ENABLED', 'false').lower() == 'true',
            # 钉钉机器人
            dingtalk_app_key=os.getenv('DINGTALK_APP_KEY'),
            dingtalk_app_secret=os.getenv('DINGTALK_APP_SECRET'),
            dingtalk_stream_enabled=os.getenv('DINGTALK_STREAM_ENABLED', 'false').lower() == 'true',
            # 企业微信机器人
            wecom_corpid=os.getenv('WECOM_CORPID'),
            wecom_token=os.getenv('WECOM_TOKEN'),
            wecom_encoding_aes_key=os.getenv('WECOM_ENCODING_AES_KEY'),
            wecom_agent_id=os.getenv('WECOM_AGENT_ID'),
            # Telegram
            telegram_webhook_secret=os.getenv('TELEGRAM_WEBHOOK_SECRET'),
            # Discord 机器人扩展配置
            discord_bot_status=os.getenv('DISCORD_BOT_STATUS', 'A股智能分析 | /help'),
            # 实时行情增强数据配置
            enable_realtime_quote=os.getenv('ENABLE_REALTIME_QUOTE', 'true').lower() == 'true',
            enable_realtime_technical_indicators=os.getenv(
                'ENABLE_REALTIME_TECHNICAL_INDICATORS', 'true'
            ).lower() == 'true',
            enable_chip_distribution=os.getenv('ENABLE_CHIP_DISTRIBUTION', 'true').lower() == 'true',
            # 东财接口补丁开关
            enable_eastmoney_patch=os.getenv('ENABLE_EASTMONEY_PATCH', 'false').lower() == 'true',
            # 实时行情数据源优先级：
            # - tencent: 腾讯财经，有量比/换手率/PE/PB等，单股查询稳定（推荐）
            # - akshare_sina: 新浪财经，基本行情稳定，但无量比
            # - efinance/akshare_em: 东财全量接口，数据最全但容易被封
            # - tushare: Tushare Pro，需要2000积分，数据全面
            realtime_source_priority=cls._resolve_realtime_source_priority(),
            realtime_cache_ttl=int(os.getenv('REALTIME_CACHE_TTL', '600')),
            circuit_breaker_cooldown=int(os.getenv('CIRCUIT_BREAKER_COOLDOWN', '300'))
        )
    
    @classmethod
    def _parse_stock_email_groups(cls) -> List[Tuple[List[str], List[str]]]:
        """
        Parse STOCK_GROUP_N and EMAIL_GROUP_N from environment.
        Returns [(stocks, emails), ...] ordered by group index.
        """
        groups: dict = {}
        stock_re = re.compile(r'^STOCK_GROUP_(\d+)$', re.IGNORECASE)
        email_re = re.compile(r'^EMAIL_GROUP_(\d+)$', re.IGNORECASE)
        for key in os.environ:
            m = stock_re.match(key)
            if m:
                idx = int(m.group(1))
                val = os.environ[key].strip()
                groups.setdefault(idx, {})['stocks'] = [c.strip() for c in val.split(',') if c.strip()]
            m = email_re.match(key)
            if m:
                idx = int(m.group(1))
                val = os.environ[key].strip()
                groups.setdefault(idx, {})['emails'] = [e.strip() for e in val.split(',') if e.strip()]
        result = []
        for idx in sorted(groups.keys()):
            g = groups[idx]
            if 'stocks' in g and 'emails' in g and g['stocks'] and g['emails']:
                result.append((g['stocks'], g['emails']))
        return result

    @classmethod
    def _parse_market_review_region(cls, value: str) -> str:
        """解析大盘复盘市场区域，非法值记录警告后回退为 cn"""
        import logging
        v = (value or 'cn').strip().lower()
        if v in ('cn', 'us', 'both'):
            return v
        logging.getLogger(__name__).warning(
            f"MARKET_REVIEW_REGION 配置值 '{value}' 无效，已回退为默认值 'cn'（合法值：cn / us / both）"
        )
        return 'cn'

    @classmethod
    def _resolve_realtime_source_priority(cls) -> str:
        """
        Resolve realtime source priority with automatic tushare injection.

        When TUSHARE_TOKEN is configured but REALTIME_SOURCE_PRIORITY is not
        explicitly set, automatically prepend 'tushare' to the default priority
        so that the paid data source is utilized for realtime quotes as well.
        """
        explicit = os.getenv('REALTIME_SOURCE_PRIORITY')
        default_priority = 'tencent,akshare_sina,efinance,akshare_em'

        if explicit:
            # User explicitly set priority, respect it
            return explicit

        tushare_token = os.getenv('TUSHARE_TOKEN', '').strip()
        if tushare_token:
            # Token configured but no explicit priority override
            # Prepend tushare so the paid source is tried first
            import logging
            logger = logging.getLogger(__name__)
            resolved = f'tushare,{default_priority}'
            logger.info(
                f"TUSHARE_TOKEN detected, auto-injecting tushare into realtime priority: {resolved}"
            )
            return resolved

        return default_priority

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._instance = None

    def refresh_stock_list(self) -> None:
        """
        热读取 STOCK_LIST 环境变量并更新配置中的自选股列表
        
        支持两种配置方式：
        1. .env 文件（本地开发、定时任务模式） - 修改后下次执行自动生效
        2. 系统环境变量（GitHub Actions、Docker） - 启动时固定，运行中不变
        """
        # 优先从 .env 文件读取最新配置，这样即使在容器环境中修改了 .env 文件，
        # 也能获取到最新的股票列表配置
        env_file = os.getenv("ENV_FILE")
        env_path = Path(env_file) if env_file else (Path(__file__).parent.parent / '.env')
        stock_list_str = ''
        if env_path.exists():
            # 直接从 .env 文件读取最新的配置
            env_values = dotenv_values(env_path)
            stock_list_str = (env_values.get('STOCK_LIST') or '').strip()

        # 如果 .env 文件不存在或未配置，才尝试从系统环境变量读取
        if not stock_list_str:
            stock_list_str = os.getenv('STOCK_LIST', '')

        stock_list = [
            (c or "").strip().upper()
            for c in stock_list_str.split(',')
            if (c or "").strip()
        ]

        if not stock_list:
            stock_list = ['000001']

        self.stock_list = stock_list
    
    def validate(self) -> List[str]:
        """
        验证配置完整性
        
        Returns:
            缺失或无效配置项的警告列表
        """
        warnings = []
        
        if not self.stock_list:
            warnings.append("警告：未配置自选股列表 (STOCK_LIST)")
        
        if not self.tushare_token:
            warnings.append("提示：未配置 Tushare Token，将使用其他数据源")
        
        has_any_llm_key = bool(self.gemini_api_keys or self.anthropic_api_keys or self.openai_api_keys)
        if not has_any_llm_key:
            warnings.append("警告：未配置任何 LLM API Key（GEMINI_API_KEY/ANTHROPIC_API_KEY/OPENAI_API_KEY），AI 分析功能将不可用")
        elif not self.litellm_model:
            warnings.append(
                "提示：LITELLM_MODEL 未配置，将自动从可用 API Key 推断模型。"
                "gemini_model 等 legacy 字段将在未来版本弃用，建议尽早配置 LITELLM_MODEL（格式如 gemini/gemini-2.5-flash）"
            )
        
        if not self.bocha_api_keys and not self.tavily_api_keys and not self.brave_api_keys and not self.serpapi_keys:
            warnings.append("提示：未配置搜索引擎 API Key (Bocha/Tavily/Brave/SerpAPI)，新闻搜索功能将不可用")
        
        # 检查通知配置
        has_notification = (
            self.wechat_webhook_url or
            self.feishu_webhook_url or
            (self.telegram_bot_token and self.telegram_chat_id) or
            (self.email_sender and self.email_password) or
            (self.pushover_user_key and self.pushover_api_token) or
            self.pushplus_token or
            self.serverchan3_sendkey or
            self.custom_webhook_urls or
            (self.discord_bot_token and self.discord_main_channel_id) or
            self.discord_webhook_url
        )
        if not has_notification:
            warnings.append("提示：未配置通知渠道，将不发送推送通知")
        
        return warnings
    
    def get_db_url(self) -> str:
        """
        获取 SQLAlchemy 数据库连接 URL
        
        自动创建数据库目录（如果不存在）
        """
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.absolute()}"


# === 便捷的配置访问函数 ===
def get_config() -> Config:
    """获取全局配置实例的快捷方式"""
    return Config.get_instance()


if __name__ == "__main__":
    # 测试配置加载
    config = get_config()
    print("=== 配置加载测试 ===")
    print(f"自选股列表: {config.stock_list}")
    print(f"数据库路径: {config.database_path}")
    print(f"最大并发数: {config.max_workers}")
    print(f"调试模式: {config.debug}")
    
    # 验证配置
    warnings = config.validate()
    if warnings:
        print("\n配置验证结果:")
        for w in warnings:
            print(f"  - {w}")
