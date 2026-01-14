# -*- coding: utf-8 -*-
"""Web admin config schema for env management."""

from __future__ import annotations

CONFIG_SECTIONS = [
    {
        "id": "core",
        "title": "核心配置",
        "description": "系统运行所需的关键参数。",
        "items": [
            {
                "key": "STOCK_LIST",
                "label": "自选股列表",
                "help": "逗号分隔，例如 600519,300750,002594",
                "type": "list",
                "required": True,
            },
            {
                "key": "DATABASE_PATH",
                "label": "数据库路径",
                "help": "SQLite 数据库文件位置",
                "type": "path",
                "required": True,
            },
        ],
    },
    {
        "id": "data",
        "title": "数据源",
        "description": "行情数据与数据服务配置。",
        "items": [
            {
                "key": "TUSHARE_TOKEN",
                "label": "Tushare Token",
                "help": "Tushare Pro 数据源 Token",
                "type": "secret",
            },
        ],
    },
    {
        "id": "ai",
        "title": "AI 模型",
        "description": "Gemini 或 OpenAI 兼容接口二选一，可同时配置。",
        "items": [
            {
                "key": "GEMINI_API_KEY",
                "label": "Gemini API Key",
                "help": "从 Google AI Studio 获取",
                "type": "secret",
            },
            {
                "key": "GEMINI_MODEL",
                "label": "Gemini 模型",
                "help": "默认 gemini-3-flash-preview",
                "type": "string",
            },
            {
                "key": "GEMINI_MODEL_FALLBACK",
                "label": "Gemini 备选模型",
                "help": "默认 gemini-2.5-flash",
                "type": "string",
            },
            {
                "key": "GEMINI_REQUEST_DELAY",
                "label": "Gemini 请求间隔（秒）",
                "help": "防止限流，建议 >= 2",
                "type": "number",
            },
            {
                "key": "GEMINI_MAX_RETRIES",
                "label": "Gemini 最大重试次数",
                "help": "默认 5",
                "type": "number",
            },
            {
                "key": "GEMINI_RETRY_DELAY",
                "label": "Gemini 重试基础延时（秒）",
                "help": "默认 5",
                "type": "number",
            },
            {
                "key": "OPENAI_API_KEY",
                "label": "OpenAI 兼容 API Key",
                "help": "支持 DeepSeek / 通义 / Moonshot 等",
                "type": "secret",
            },
            {
                "key": "OPENAI_BASE_URL",
                "label": "OpenAI Base URL",
                "help": "可选，第三方 API 地址",
                "type": "string",
            },
            {
                "key": "OPENAI_MODEL",
                "label": "OpenAI 模型",
                "help": "默认 gpt-4o-mini",
                "type": "string",
            },
        ],
    },
    {
        "id": "search",
        "title": "搜索引擎",
        "description": "新闻与情报搜索配置。",
        "items": [
            {
                "key": "TAVILY_API_KEYS",
                "label": "Tavily API Keys",
                "help": "多个 key 用逗号分隔",
                "type": "list",
            },
            {
                "key": "SERPAPI_API_KEYS",
                "label": "SerpAPI Keys",
                "help": "多个 key 用逗号分隔",
                "type": "list",
            },
        ],
    },
    {
        "id": "notifications",
        "title": "通知渠道",
        "description": "支持多渠道同时推送。",
        "items": [
            {
                "key": "WECHAT_WEBHOOK_URL",
                "label": "企业微信 Webhook",
                "help": "企业微信群机器人 Webhook",
                "type": "string",
            },
            {
                "key": "FEISHU_WEBHOOK_URL",
                "label": "飞书 Webhook",
                "help": "飞书群机器人 Webhook",
                "type": "string",
            },
            {
                "key": "TELEGRAM_BOT_TOKEN",
                "label": "Telegram Bot Token",
                "help": "@BotFather 获取",
                "type": "secret",
            },
            {
                "key": "TELEGRAM_CHAT_ID",
                "label": "Telegram Chat ID",
                "help": "@userinfobot 或 getUpdates 获取",
                "type": "string",
            },
            {
                "key": "EMAIL_SENDER",
                "label": "发件人邮箱",
                "help": "如 your_email@example.com",
                "type": "string",
            },
            {
                "key": "EMAIL_PASSWORD",
                "label": "邮箱授权码",
                "help": "非登录密码",
                "type": "secret",
            },
            {
                "key": "EMAIL_RECEIVERS",
                "label": "收件人列表",
                "help": "多个邮箱用逗号分隔",
                "type": "list",
            },
            {
                "key": "CUSTOM_WEBHOOK_URLS",
                "label": "自定义 Webhook",
                "help": "多个 URL 用逗号分隔",
                "type": "list",
            },
            {
                "key": "FEISHU_MAX_BYTES",
                "label": "飞书消息长度限制",
                "help": "默认 20000",
                "type": "number",
            },
            {
                "key": "WECHAT_MAX_BYTES",
                "label": "企业微信消息长度限制",
                "help": "默认 4000",
                "type": "number",
            },
        ],
    },
    {
        "id": "feishu_docs",
        "title": "飞书文档",
        "description": "用于飞书云文档推送。",
        "items": [
            {
                "key": "FEISHU_APP_ID",
                "label": "飞书应用 App ID",
                "help": "飞书开发者后台获取",
                "type": "string",
            },
            {
                "key": "FEISHU_APP_SECRET",
                "label": "飞书应用 App Secret",
                "help": "飞书开发者后台获取",
                "type": "secret",
            },
            {
                "key": "FEISHU_FOLDER_TOKEN",
                "label": "飞书云盘文件夹 Token",
                "help": "目标文件夹标识",
                "type": "string",
            },
        ],
    },
    {
        "id": "schedule",
        "title": "定时任务",
        "description": "定时执行与大盘复盘开关。",
        "items": [
            {
                "key": "SCHEDULE_ENABLED",
                "label": "启用定时任务",
                "help": "true / false",
                "type": "bool",
            },
            {
                "key": "SCHEDULE_TIME",
                "label": "每日执行时间",
                "help": "24 小时制，HH:MM",
                "type": "string",
            },
            {
                "key": "MARKET_REVIEW_ENABLED",
                "label": "启用大盘复盘",
                "help": "true / false",
                "type": "bool",
            },
        ],
    },
    {
        "id": "system",
        "title": "系统配置",
        "description": "日志与并发等系统参数。",
        "items": [
            {
                "key": "LOG_DIR",
                "label": "日志目录",
                "help": "默认 ./logs",
                "type": "path",
            },
            {
                "key": "LOG_LEVEL",
                "label": "日志级别",
                "help": "DEBUG / INFO / WARNING / ERROR",
                "type": "string",
            },
            {
                "key": "MAX_WORKERS",
                "label": "最大并发线程数",
                "help": "建议保持低并发",
                "type": "number",
            },
            {
                "key": "DEBUG",
                "label": "调试模式",
                "help": "true / false",
                "type": "bool",
            },
        ],
    },
]

SENSITIVE_TYPES = {"secret"}
