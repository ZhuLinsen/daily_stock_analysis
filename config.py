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
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv, dotenv_values
from dataclasses import dataclass, field


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
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3-flash-preview"  # 主模型
    gemini_model_fallback: str = "gemini-2.5-flash"  # 备选模型
    
    # Gemini API 请求配置（防止 429 限流）
    gemini_request_delay: float = 2.0  # 请求间隔（秒）
    gemini_max_retries: int = 5  # 最大重试次数
    gemini_retry_delay: float = 5.0  # 重试基础延时（秒）
    
    # OpenAI 兼容 API（备选，当 Gemini 不可用时使用）
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # 如: https://api.openai.com/v1
    openai_model: str = "gpt-4o-mini"  # OpenAI 兼容模型名称
    
    # === 搜索引擎配置（支持多 Key 负载均衡）===
    tavily_api_keys: List[str] = field(default_factory=list)  # Tavily API Keys
    serpapi_keys: List[str] = field(default_factory=list)  # SerpAPI Keys
    
    # === 通知配置（可同时配置多个，全部推送）===
    
    # 企业微信 Webhook
    wechat_webhook_url: Optional[str] = None
    
    # 飞书 Webhook
    feishu_webhook_url: Optional[str] = None
    
    # Telegram 配置（需要同时配置 Bot Token 和 Chat ID）
    telegram_bot_token: Optional[str] = None  # Bot Token（@BotFather 获取）
    telegram_chat_id: Optional[str] = None  # Chat ID
    
    # 邮件配置（只需邮箱和授权码，SMTP 自动识别）
    email_sender: Optional[str] = None  # 发件人邮箱
    email_password: Optional[str] = None  # 邮箱密码/授权码
    email_receivers: List[str] = field(default_factory=list)  # 收件人列表（留空则发给自己）
    
    # 自定义 Webhook（支持多个，逗号分隔）
    # 适用于：钉钉、Discord、Slack、自建服务等任意支持 POST JSON 的 Webhook
    custom_webhook_urls: List[str] = field(default_factory=list)
    
    # 消息长度限制（字节）- 超长自动分批发送
    feishu_max_bytes: int = 20000  # 飞书限制约 20KB，默认 20000 字节
    wechat_max_bytes: int = 4000   # 企业微信限制 4096 字节，默认 4000 字节
    
    # === 数据库配置 ===
    database_path: str = "./data/stock_analysis.db"
    
    # === 日志配置 ===
    log_dir: str = "./logs"  # 日志文件目录
    log_level: str = "INFO"  # 日志级别
    
    # === 系统配置 ===
    max_workers: int = 3  # 低并发防封禁
    debug: bool = False
    
    # === 定时任务配置 ===
    schedule_enabled: bool = True            # 是否启用定时任务
    schedule_time: str = "14:45"              # 每日推送时间（HH:MM 格式）
    market_review_enabled: bool = True        # 是否启用大盘复盘
    
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
        # 加载项目根目录下的 .env 文件
        env_path = Path(__file__).parent / '.env'
        load_dotenv(dotenv_path=env_path)
        
        # 解析自选股列表（逗号分隔）
        stock_list_str = os.getenv('STOCK_LIST', '')
        stock_list = [
            code.strip() 
            for code in stock_list_str.split(',') 
            if code.strip()
        ]
        
        # 如果没有配置，使用默认的示例股票
        if not stock_list:
            stock_list = ['600519', '000001', '300750']
        
        # 解析搜索引擎 API Keys（支持多个 key，逗号分隔）
        tavily_keys_str = os.getenv('TAVILY_API_KEYS', '')
        tavily_api_keys = [k.strip() for k in tavily_keys_str.split(',') if k.strip()]
        
        serpapi_keys_str = os.getenv('SERPAPI_API_KEYS', '')
        serpapi_keys = [k.strip() for k in serpapi_keys_str.split(',') if k.strip()]
        
        return cls(
            stock_list=stock_list,
            feishu_app_id=os.getenv('FEISHU_APP_ID'),
            feishu_app_secret=os.getenv('FEISHU_APP_SECRET'),
            feishu_folder_token=os.getenv('FEISHU_FOLDER_TOKEN'),
            tushare_token=os.getenv('TUSHARE_TOKEN'),
            gemini_api_key=os.getenv('GEMINI_API_KEY'),
            gemini_model=os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'),
            gemini_model_fallback=os.getenv('GEMINI_MODEL_FALLBACK', 'gemini-2.5-flash'),
            gemini_request_delay=float(os.getenv('GEMINI_REQUEST_DELAY', '2.0')),
            gemini_max_retries=int(os.getenv('GEMINI_MAX_RETRIES', '5')),
            gemini_retry_delay=float(os.getenv('GEMINI_RETRY_DELAY', '5.0')),
            openai_api_key=os.getenv('OPENAI_API_KEY'),
            openai_base_url=os.getenv('OPENAI_BASE_URL'),
            openai_model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
            tavily_api_keys=tavily_api_keys,
            serpapi_keys=serpapi_keys,
            wechat_webhook_url=os.getenv('WECHAT_WEBHOOK_URL'),
            feishu_webhook_url=os.getenv('FEISHU_WEBHOOK_URL'),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID'),
            email_sender=os.getenv('EMAIL_SENDER'),
            email_password=os.getenv('EMAIL_PASSWORD'),
            email_receivers=[r.strip() for r in os.getenv('EMAIL_RECEIVERS', '').split(',') if r.strip()],
            custom_webhook_urls=[u.strip() for u in os.getenv('CUSTOM_WEBHOOK_URLS', '').split(',') if u.strip()],
            feishu_max_bytes=int(os.getenv('FEISHU_MAX_BYTES', '20000')),
            wechat_max_bytes=int(os.getenv('WECHAT_MAX_BYTES', '4000')),
            database_path=os.getenv('DATABASE_PATH', './data/stock_analysis.db'),
            log_dir=os.getenv('LOG_DIR', './logs'),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            max_workers=int(os.getenv('MAX_WORKERS', '3')),
            debug=os.getenv('DEBUG', 'false').lower() == 'true',
            schedule_enabled=os.getenv('SCHEDULE_ENABLED', 'false').lower() == 'true',
            schedule_time=os.getenv('SCHEDULE_TIME', '18:00'),
            market_review_enabled=os.getenv('MARKET_REVIEW_ENABLED', 'true').lower() == 'true',
        )
    
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
        # 若 .env 中配置了 STOCK_LIST，则以 .env 为准；否则回退到系统环境变量
        env_path = Path(__file__).parent / '.env'
        stock_list_str = ''
        if env_path.exists():
            env_values = dotenv_values(env_path)
            stock_list_str = (env_values.get('STOCK_LIST') or '').strip()

        if not stock_list_str:
            stock_list_str = os.getenv('STOCK_LIST', '')

        stock_list = [
            code.strip()
            for code in stock_list_str.split(',')
            if code.strip()
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
        
        if not self.gemini_api_key and not self.openai_api_key:
            warnings.append("警告：未配置 Gemini 或 OpenAI API Key，AI 分析功能将不可用")
        elif not self.gemini_api_key:
            warnings.append("提示：未配置 Gemini API Key，将使用 OpenAI 兼容 API")
        
        if not self.tavily_api_keys and not self.serpapi_keys:
            warnings.append("提示：未配置搜索引擎 API Key (Tavily/SerpAPI)，新闻搜索功能将不可用")
        
        # 检查通知配置
        has_notification = (
            self.wechat_webhook_url or 
            self.feishu_webhook_url or
            (self.telegram_bot_token and self.telegram_chat_id) or
            (self.email_sender and self.email_password)
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
