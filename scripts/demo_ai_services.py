#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 服务适配层 - 使用示例

本脚本演示统一 AI 服务适配层的完整使用方式。
支持 DeepSeek 和红蝶AI 两种服务，通过统一接口无缝切换。

运行方式:
  # 方式一：交互式演示（需要配置 .env 中的 API Key）
  python scripts/demo_ai_services.py

  # 方式二：指定 API Key（临时演示）
  DEEPSEEK_API_KEY=sk-xxx HONGDIE_API_KEY=sk-xxx python scripts/demo_ai_services.py

  # 方式三：仅模拟演示（展示 API 用法，不实际调用）
  DEMO_MODE=1 python scripts/demo_ai_services.py

配置说明:
  详细配置项见 .env.example 中 "AI 服务抽象层配置" 章节
"""

from __future__ import annotations

import json
import logging
import os
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_services import (
    AIAuthenticationError,
    AIInvalidResponseError,
    AIRateLimitError,
    AIServiceConfig,
    AIServiceError,
    AIServiceFactory,
    AITimeoutError,
    BaseAIService,
    DeepSeekService,
    HongdieService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("demo")

SEPARATOR = "=" * 70


def print_section(title: str) -> None:
    """打印章节标题。"""
    print(f"\n{SEPARATOR}")
    print(f"  {title}")
    print(SEPARATOR)


def print_result(label: str, value: object) -> None:
    """格式化打印结果。"""
    if isinstance(value, dict):
        print(f"  {label}: {json.dumps(value, ensure_ascii=False, indent=2)}")
    else:
        print(f"  {label}: {value}")


# =========================================================================
# 示例 1: 基础配置
# =========================================================================


def demo_config() -> None:
    """演示配置加载和使用。"""
    print_section("示例 1: 配置加载")

    # 从环境变量加载配置
    config = AIServiceConfig.from_env()
    print("从环境变量加载的配置（API Key 已掩码）:")
    masked = config.mask_api_keys()
    print(f"  DeepSeek: enabled={masked.deepseek.enabled}, "
          f"api_key='{masked.deepseek.api_key}', "
          f"model='{masked.deepseek.model}', "
          f"base_url='{masked.deepseek.base_url}'")
    print(f"  红蝶AI:   enabled={masked.hongdie.enabled}, "
          f"api_key='{masked.hongdie.api_key}', "
          f"model='{masked.hongdie.model}', "
          f"base_url='{masked.hongdie.base_url}'")
    print(f"  缓存: enabled={config.cache_enabled}, "
          f"max_size={config.cache_max_size}, ttl={config.cache_ttl_seconds}s")
    print(f"  限流: enabled={config.rate_limiter_enabled}")

    # 获取已启用的服务
    enabled = config.get_enabled_services()
    print(f"  已启用服务: {enabled or '(无)'}")

    # 编程式创建配置
    print("\n编程式配置示例（覆盖环境变量）:")
    custom_config = AIServiceConfig()
    custom_config.deepseek.enabled = True
    custom_config.deepseek.api_key = "sk-your-deepseek-key"
    custom_config.deepseek.model = "deepseek-v4-flash"
    custom_config.deepseek.temperature = 0.3
    custom_config.deepseek.max_tokens = 2048
    custom_config.hongdie.enabled = True
    custom_config.hongdie.api_key = "sk-your-hongdie-key"
    custom_config.hongdie.base_url = "https://tokento.vip/v1"
    custom_config.hongdie.model = "gpt-4o"

    masked2 = custom_config.mask_api_keys()
    print(f"  DeepSeek: api_key='{masked2.deepseek.api_key}', "
          f"model='{masked2.deepseek.model}', "
          f"temperature={masked2.deepseek.temperature}")
    print(f"  红蝶AI:   api_key='{masked2.hongdie.api_key}', "
          f"base_url='{masked2.hongdie.base_url}', "
          f"model='{masked2.hongdie.model}'")


# =========================================================================
# 示例 2: 服务工厂
# =========================================================================


def demo_factory() -> None:
    """演示服务工厂的用法。"""
    print_section("示例 2: 服务工厂")

    # 方式一：从环境变量创建工厂
    factory = AIServiceFactory.from_env()
    print("工厂已从环境变量创建")

    # 查看可用服务
    available = AIServiceFactory.get_available_services()
    print("\n可用的服务类型:")
    for name, desc in available.items():
        print(f"  - {name}: {desc}")

    # 获取服务实例（单例模式，重复获取返回同一实例）
    try:
        service = factory.get_service("deepseek")
        print(f"\n获取 DeepSeek 服务实例: {type(service).__name__}")
        print(f"  已配置: {service.is_configured}")

        # 再次获取（验证单例）
        service2 = factory.get_service("deepseek")
        print(f"  再次获取（同一实例）: {service is service2}")
    except ValueError as e:
        print(f"\n  获取 DeepSeek 服务失败: {e}")

    try:
        service = factory.get_service("hongdie")
        print(f"\n获取红蝶AI 服务实例: {type(service).__name__}")
        print(f"  已配置: {service.is_configured}")
    except ValueError as e:
        print(f"\n  获取红蝶AI 服务失败: {e}")

    # 创建所有已启用的服务
    print("\n创建所有已启用服务:")
    enabled_services = factory.create_all_enabled()
    for name, svc in enabled_services.items():
        print(f"  - {name}: {type(svc).__name__}, 已配置={svc.is_configured}")


# =========================================================================
# 示例 3: 文本生成
# =========================================================================


def demo_generate_text(service: BaseAIService, label: str) -> None:
    """演示文本生成。"""
    print_section(f"示例 3: 文本生成 ({label})")

    if not service.is_configured:
        print(f"  服务未配置，跳过实际调用。设置 {label.upper()}_API_KEY 后重试。")
        return

    # 3a: 基本文本生成
    print("3a: 基本文本生成")
    try:
        result = service.generate_text(
            "用一句话介绍什么是价值投资",
            use_cache=False,
        )
        print_result("响应", result)
    except Exception as e:
        print(f"  调用失败: {e}")

    # 3b: 带系统提示词
    print("\n3b: 带系统提示词")
    try:
        result = service.generate_text(
            "现在茅台适合买入吗？",
            system_prompt="你是一位资深的价值投资分析师，回答应当简洁、客观、有理有据。",
            use_cache=False,
        )
        print_result("响应", result)
    except Exception as e:
        print(f"  调用失败: {e}")

    # 3c: 自定义参数（温度、最大令牌数）
    print("\n3c: 自定义参数（temperature=0.1, max_tokens=200）")
    try:
        result = service.generate_text(
            "列出 3 个选股核心指标并简要说明原因",
            temperature=0.1,
            max_tokens=200,
            use_cache=False,
        )
        print_result("响应", result)
    except Exception as e:
        print(f"  调用失败: {e}")

    # 3d: 缓存演示
    print("\n3d: 缓存演示（第二次调用应命中缓存）")
    try:
        import time

        prompt = "什么是股票的技术分析？"
        t0 = time.time()
        r1 = service.generate_text(prompt, use_cache=True)
        t1 = time.time()
        r2 = service.generate_text(prompt, use_cache=True)
        t2 = time.time()
        print(f"  首次调用: {t1-t0:.3f}s")
        print(f"  缓存调用: {t2-t1:.3f}s")
        print(f"  结果一致: {r1 == r2}")
    except Exception as e:
        print(f"  调用失败: {e}")


# =========================================================================
# 示例 4: 连接检查
# =========================================================================


def demo_check_connection(service: BaseAIService, label: str) -> None:
    """演示连接健康检查。"""
    print_section(f"示例 4: 连接检查 ({label})")

    result = service.check_connection()
    print_result("检查结果", result)


# =========================================================================
# 示例 5: 错误处理
# =========================================================================


def demo_error_handling() -> None:
    """演示不同错误类型的处理。"""
    print_section("示例 5: 错误处理演示")

    # 使用未配置的服务
    config = AIServiceConfig()
    config.deepseek.enabled = True
    config.deepseek.api_key = ""  # 空的 API Key

    factory = AIServiceFactory(config)

    try:
        service = factory.get_service("deepseek")
        if not service.is_configured:
            print("  服务未配置（API Key 为空），check_connection 返回:")
            result = service.check_connection()
            print_result("", result)
    except ValueError as e:
        print(f"  获取服务失败: {e}")

    # 显示错误类型层次
    print("\n错误类型层次结构:")
    errors = [
        ("AIError", "所有 AI 服务异常的基类"),
        ("  AIServiceError", "服务端错误（5xx）"),
        ("  AIAuthenticationError", "认证失败（401）"),
        ("  AIRateLimitError", "请求频率过高（429）"),
        ("  AITimeoutError", "请求超时"),
        ("  AIInvalidResponseError", "响应格式异常"),
    ]
    for name, desc in errors:
        print(f"  {name}: {desc}")

    # 异常捕获示例
    print("\n典型错误处理模式:")
    code = '''
    try:
        result = service.generate_text("Hello")
    except AIAuthenticationError:
        # 检查 API Key 是否正确
        print("API Key 无效，请检查配置")
    except AIRateLimitError:
        # 稍后重试
        print("请求过于频繁，请稍后再试")
    except AITimeoutError:
        # 检查网络连接
        print("请求超时，请检查网络")
    except AIInvalidResponseError:
        # 响应异常
        print("服务返回了异常响应")
    except AIServiceError:
        # 服务端问题
        print("AI 服务暂时不可用")
    '''
    print(code)


# =========================================================================
# 示例 6: 完整工作流
# =========================================================================


def demo_workflow() -> None:
    """演示完整的 AI 服务使用工作流。"""
    print_section("示例 6: 完整工作流")

    config = AIServiceConfig.from_env()
    factory = AIServiceFactory(config)

    # 步骤 1: 检查连接
    print("步骤 1: 连接检查")
    results = factory.check_all_connections()
    for name, result in results.items():
        status = "✓" if result["ok"] else "✗"
        print(f"  [{status}] {name}: {result['message']}")

    # 步骤 2: 获取可用服务
    print("\n步骤 2: 创建已启用服务实例")
    services = factory.create_all_enabled()
    if not services:
        print("  没有已启用的服务，请配置 DEEPSEEK_API_KEY 或 HONGDIE_API_KEY")
        return

    for name in services:
        service = services[name]
        if not service.is_configured:
            print(f"  - {name}: 已配置但缺少 API Key")
            continue

        print(f"\n  使用 {name} 服务进行分析:")

        try:
            # 分析股票
            analysis = service.generate_text(
                "请分析 A 股市场当前的主要风险因素",
                system_prompt="你是专业的 A 股市场分析师，回答应当数据驱动、客观理性。",
                temperature=0.3,
                max_tokens=500,
                use_cache=False,
            )
            print(f"    分析结果:\n    {analysis[:200]}...")
        except Exception as e:
            print(f"    分析失败: {e}")


# =========================================================================
# 示例 7: 不同模型的切换
# =========================================================================


def demo_models() -> None:
    """演示不同模型的切换。"""
    print_section("示例 7: 模型切换演示")

    # 查看支持哪些模型
    print("DeepSeek 支持的模型:")
    for m in DeepSeekService.get_supported_models():
        print(f"  - {m}")

    print("\n红蝶AI 支持的模型:")
    for m in HongdieService.get_supported_models():
        print(f"  - {m}")

    # 编程式创建 DeepSeek 服务并切换模型
    print("\n创建 DeepSeek 服务（deepseek-v4-flash 模型）:")
    config = AIServiceConfig()
    config.deepseek.enabled = True
    config.deepseek.api_key = os.getenv("DEEPSEEK_API_KEY", "")
    config.deepseek.model = "deepseek-v4-flash"

    factory = AIServiceFactory(config)
    try:
        service = factory.get_service("deepseek")
        if service.is_configured:
            print("  服务已配置，可以调用 generate_text()")
            # 可在单个调用中临时覆盖模型
            print("  调用时可通过 model 参数临时切换模型:")
            print('  service.generate_text("Hello", model="deepseek-chat")')
    except ValueError as e:
        print(f"  服务未配置: {e}")

    # 查看默认配置
    print(f"\n默认 base_url:")
    print(f"  DeepSeek: https://api.deepseek.com")
    print(f"  红蝶AI:   {HongdieService.get_default_base_url()}")
    print(f"  红蝶AI 官网: https://tokento.vip")


# =========================================================================
# 主入口
# =========================================================================


def main() -> None:
    """主函数。"""
    print(f"\n{'=' * 70}")
    print(f"  AI 服务适配层 - 使用示例")
    print(f"  DeepSeek + 红蝶AI 统一接口演示")
    print(f"{'=' * 70}\n")

    # 检查 DEMO_MODE
    if os.getenv("DEMO_MODE"):
        print(">>> DEMO_MODE 已启用（仅展示 API 用法，不实际调用 AI 服务）\n")

    # 示例 1: 配置
    demo_config()

    # 示例 2: 工厂
    demo_factory()

    # 示例 5: 错误处理
    demo_error_handling()

    # 示例 7: 模型信息
    demo_models()

    # 示例 3, 4, 6: 需要实际 API 调用（DEMO_MODE 或缺少 API Key 时跳过）
    config = AIServiceConfig.from_env()
    has_api_key = bool(config.deepseek.api_key or config.hongdie.api_key)
    is_demo_mode = os.getenv("DEMO_MODE")

    if is_demo_mode:
        print(f"\n>>> DEMO_MODE: 跳过实际 API 调用")
    elif not has_api_key:
        print(f"\n>>> 未检测到 API Key，跳过实际调用演示")
        print(f"    设置 DEEPSEEK_API_KEY 或 HONGDIE_API_KEY 环境变量后重试")
        print(f"    或运行 DEMO_MODE=1 python scripts/demo_ai_services.py")
    else:
        factory = AIServiceFactory(config)

        # 尝试 DeepSeek
        if config.deepseek.enabled and config.deepseek.api_key:
            try:
                service = factory.get_service("deepseek")
                demo_generate_text(service, "DeepSeek")
                demo_check_connection(service, "DeepSeek")
            except Exception as e:
                print(f"\n  DeepSeek 服务调用失败: {e}")

        # 尝试红蝶AI
        if config.hongdie.enabled and config.hongdie.api_key:
            try:
                factory2 = AIServiceFactory(config)
                service = factory2.get_service("hongdie")
                demo_generate_text(service, "红蝶AI")
                demo_check_connection(service, "红蝶AI")
            except Exception as e:
                print(f"\n  红蝶AI 服务调用失败: {e}")

        # 完整工作流
        demo_workflow()

    print(f"\n{'=' * 70}")
    print(f"  演示完成")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
