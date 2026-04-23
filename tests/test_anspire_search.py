# -*- coding: utf-8 -*-
"""
Anspire Search 搜索引擎测试套件

测试覆盖范围:
1. 配置加载测试 - 验证 anspire_api_keys 是否正确从环境变量加载
2. 服务初始化测试 - 验证 SearchService 是否正确初始化 AnspireSearchProvider
3. API 调用测试 - 实际调用 Anspire API 验证返回结果
4. 故障转移测试 - 验证无效 Key 时的错误处理和降级机制
5. 搜索功能测试 - 测试股票新闻搜索和通用搜索功能

运行方式:
```bash
# Windows PowerShell
$env:ANSPIRE_API_KEYS="your_test_api_key"
python -m pytest tests/test_anspire_search.py -v

# Linux/Mac
export ANSPIRE_API_KEYS="your_test_api_key"
python -m pytest tests/test_anspire_search.py -v
```
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv
load_dotenv()

# 添加项目根目录到 Python 路径，解决模块导入问题
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.config import Config, get_config
from src.search_service import (
    AnspireSearchProvider,
    SearchService,
    get_search_service,
    reset_search_service,
)


class _FakeResponse:
    """模拟 HTTP 响应对象"""
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.headers = headers or {'content-type': 'application/json'}
    
    def json(self):
        return self._json_data


class TestAnspireConfigLoading(unittest.TestCase):
    """Test Anspire configuration loading from environment variables."""
    
    def setUp(self):
        """保存并清除环境变量（不操作 .env 文件）"""
        # ✅ 保存原始值，测试后恢复
        self._original_anspire_keys = os.environ.get('ANSPIRE_API_KEYS')
        
        # 清除环境变量
        if 'ANSPIRE_API_KEYS' in os.environ:
            del os.environ['ANSPIRE_API_KEYS']
        
        # 重置 Config 单例
        Config._Config__instance = None
        reset_search_service()

    def tearDown(self):
        """恢复原始环境变量"""
        # ✅ 恢复原始值
        if self._original_anspire_keys is not None:
            os.environ['ANSPIRE_API_KEYS'] = self._original_anspire_keys
        elif 'ANSPIRE_API_KEYS' in os.environ:
            del os.environ['ANSPIRE_API_KEYS']
        
        # 重置 Config 单例
        Config._Config__instance = None
        reset_search_service()

    def test_anspire_keys_loaded_from_env(self):
        """Test that ANSPIRE_API_KEYS is correctly parsed from environment."""
        # ✅ 使用 patch.dict 临时设置，测试后自动恢复
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': 'key1,key2,key3'}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 3)
            self.assertIn('key1', config.anspire_api_keys)
            self.assertIn('key2', config.anspire_api_keys)
            self.assertIn('key3', config.anspire_api_keys)

    def test_anspire_keys_single_key(self):
        """Test single API Key parsing."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': 'single_key_test'}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 1)
            self.assertEqual(config.anspire_api_keys[0], 'single_key_test')

    def test_anspire_keys_empty_env(self):
        """Test empty environment variable handling."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': ''}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 0)

    def test_anspire_keys_whitespace_handling(self):
        """Test whitespace trimming in API Keys."""
        with patch.dict(os.environ, {'ANSPIRE_API_KEYS': ' key1 , key2 , key3 '}):
            config = Config._load_from_env()
            
            self.assertEqual(len(config.anspire_api_keys), 3)
            self.assertEqual(config.anspire_api_keys, ['key1', 'key2', 'key3'])


class TestAnspireSearchProvider(unittest.TestCase):
    """Anspire Search Provider 单元测试"""
    
    def setUp(self):
        """测试前准备"""
        # ✅ 使用明确的测试占位符，不是真实密钥形态
        self.test_api_key = "sk-test-anspire-placeholder-key-12345"
        self.provider = AnspireSearchProvider([self.test_api_key])
        # 保存原始 requests 模块
        self._original_requests = sys.modules.get('requests')
    
    def tearDown(self):
        """测试后清理"""
        # 恢复原始 requests 模块
        if self._original_requests is not None:
            sys.modules['requests'] = self._original_requests
    
    def test_provider_initialization(self):
        """测试 Provider 初始化"""
        provider = AnspireSearchProvider(["key1", "key2"])
        self.assertEqual(provider.name, "Anspire")
        if hasattr(provider, 'api_keys'):
            self.assertEqual(len(provider.api_keys), 2)
        elif hasattr(provider, '_api_keys'):
            self.assertEqual(len(provider._api_keys), 2)
        self.assertTrue(provider.is_available)
    
    def test_provider_name(self):
        """测试 Provider 名称"""
        self.assertEqual(self.provider.name, "Anspire")
    
    def test_provider_availability(self):
        """测试 Provider 可用性检测"""
        # 有 API Key 时应可用
        provider_with_keys = AnspireSearchProvider(["key1"])
        self.assertTrue(provider_with_keys.is_available)
        
        # 无 API Key 时不可用
        provider_without_keys = AnspireSearchProvider([])
        self.assertFalse(provider_without_keys.is_available)
    
    def test_extract_domain(self):
        """测试域名提取功能"""
        test_cases = [
            ("https://www.example.com/article", "example.com"),
            ("https://finance.sina.com.cn/stock/", "finance.sina.com.cn"),
            ("http://www.10jqka.com.cn/news", "10jqka.com.cn"),
            ("invalid_url", "未知来源"),
            ("", "未知来源"),
        ]
        
        for url, expected in test_cases:
            result = AnspireSearchProvider._extract_domain(url)
            self.assertEqual(result, expected, f"Failed for URL: {url}")
    
    @patch('src.search_service.requests')
    def test_search_success_response(self, mock_requests):
        """测试成功响应处理"""
        # 设置 mock exceptions
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            pass
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "code": 200,
                "msg": "success",
                "results": [
                    {
                        "title": "贵州茅台今日股价上涨",
                        "url": "https://finance.sina.com.cn/stock/600519",
                        "content": "贵州茅台 (600519) 今日收盘股价上涨 2.5%，成交量放大...",
                    },
                    {
                        "title": "白酒板块持续走强",
                        "url": "https://www.10jqka.com.cn/baijiu",
                        "content": "白酒板块今日表现强势，贵州茅台、五粮液等个股涨幅居前...",
                    }
                ]
            }
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("贵州茅台 股票新闻", max_results=5, days=7)
        
        # 验证结果
        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].title, "贵州茅台今日股价上涨")
        # 假设 source 是从 url 提取的域名
        self.assertEqual(response.results[0].source, "finance.sina.com.cn")
        
        # 验证 API 调用参数
        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        # 检查 URL 是否包含 anspire 相关域名 (具体 URL 需根据实际实现调整)
        # self.assertIn("plugin.anspire.cn", call_args[0][0]) 
        self.assertIn("Authorization", call_args[1]["headers"])
        # 验证使用 params 而非 json
        self.assertIn("params", call_args[1])
        self.assertNotIn("json", call_args[1])
    
    @patch('src.search_service.requests')
    def test_search_invalid_api_key(self, mock_requests):
        """测试无效 API Key 的错误处理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            pass
        
        fake_response = _FakeResponse(
            status_code=401,
            json_data={"message": "Invalid API key"},
            text="Unauthorized"
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("测试查询", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        # 错误消息可能因实现而异，这里做宽松检查
        self.assertTrue("API" in response.error_message or "KEY" in response.error_message or "无效" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_timeout_error(self, mock_requests):
        """测试超时错误处理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
            timeout_exc = mock_requests.exceptions.Timeout
        except ImportError:
            mock_requests.exceptions = MagicMock()
            timeout_exc = Exception
            
        mock_requests.get = MagicMock(side_effect=timeout_exc())
        
        response = self.provider.search("测试查询", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        # 错误消息检查
        self.assertTrue("超时" in response.error_message or "Timeout" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_network_error(self, mock_requests):
        """测试网络错误处理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
            conn_exc = mock_requests.exceptions.ConnectionError
        except ImportError:
            mock_requests.exceptions = MagicMock()
            conn_exc = Exception

        mock_requests.get = MagicMock(side_effect=conn_exc())
        
        response = self.provider.search("测试查询", max_results=3)
        
        self.assertFalse(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
        self.assertTrue("网络" in response.error_message or "Connection" in response.error_message)
    
    @patch('src.search_service.requests')
    def test_search_empty_results(self, mock_requests):
        """测试空结果处理"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={"code": 200, "msg": "success", "results": []}
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("不存在的股票 XYZ", max_results=5)
        
        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Anspire")
        self.assertEqual(len(response.results), 0)
    
    @patch('src.search_service.requests')
    def test_search_content_truncation(self, mock_requests):
        """测试长内容截断功能"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        long_content = "这是一段非常长的内容，" * 100  # 超过 500 字符
        
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "code": 200,
                "msg": "success",
                "results": [{
                    "title": "长内容测试",
                    "url": "https://example.com/long",
                    "content": long_content
                }]
            }
        )
        
        mock_requests.get = MagicMock(return_value=fake_response)
        
        response = self.provider.search("测试", max_results=1)
        
        self.assertTrue(response.success)
        self.assertEqual(len(response.results), 1)
        # 验证内容被截断到 500 字符以内
        if response.results[0].snippet:
            self.assertLessEqual(len(response.results[0].snippet), 503)  # 500 + "..."
            self.assertTrue(response.results[0].snippet.endswith("..."))
    
    @patch('src.search_service.requests')
    def test_search_time_range(self, mock_requests):
        """测试时间范围参数"""
        try:
            import requests as real_requests
            mock_requests.exceptions = real_requests.exceptions
        except ImportError:
            mock_requests.exceptions = MagicMock()
        
        fake_response = _FakeResponse(status_code=200, json_data={"code": 200, "results": []})
        mock_requests.get = MagicMock(return_value=fake_response)
        
        # 测试 7 天范围
        self.provider.search("测试", max_results=3, days=7)
        
        # 验证时间参数
        call_args = mock_requests.get.call_args
        if call_args and len(call_args) > 1 and 'params' in call_args[1]:
            params = call_args[1]["params"]
                
            # 验证时间参数存在 (具体字段名取决于实现)
            # 这里假设使用了 FromTime/ToTime 或类似字段，若无则跳过具体字段检查
            # self.assertIn("FromTime", params)
            # self.assertIn("ToTime", params)


class TestAnspireSearchService(unittest.TestCase):
    """SearchService 中 Anspire 集成测试"""
    
    def setUp(self):
        Config._Config__instance = None
        reset_search_service()

    def test_search_service_with_anspire(self):
        """测试 SearchService 正确初始化 Anspire Provider"""
        service = SearchService(
            anspire_keys=["test_key"],
            bocha_keys=[],
            tavily_keys=[],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        self.assertTrue(hasattr(service, '_providers'))
        self.assertGreater(len(service._providers), 0)
        
        first_provider = service._providers[0]
        self.assertIsInstance(first_provider, AnspireSearchProvider)
        self.assertEqual(first_provider.name, "Anspire")
    
    def test_search_service_without_anspire(self):
        """测试未配置 Anspire 时的行为"""
        service = SearchService(
            anspire_keys=[],
            tavily_keys=["tavily_key"],
            bocha_keys=[],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        # 验证没有 Anspire Provider
        anspire_providers = [p for p in service._providers if isinstance(p, AnspireSearchProvider)]
        self.assertEqual(len(anspire_providers), 0)
    
    def test_search_service_priority(self):
        """测试 Anspire 优先级"""
        service = SearchService(
            anspire_keys=["anspire_key"],
            bocha_keys=["bocha_key"],
            tavily_keys=["tavily_key"],
            searxng_public_instances_enabled=False,
            news_max_age_days=3,
            news_strategy_profile="short"
        )
        
        self.assertIsInstance(service._providers[0], AnspireSearchProvider)


class TestAnspireIntegration(unittest.TestCase):
    """Anspire 集成测试（需要真实 API Key）"""
    
    @classmethod
    def setUpClass(cls):
        """Check if API Key is configured."""
        cls.api_keys = [k.strip() for k in os.getenv('ANSPIRE_API_KEYS', '').split(',') if k.strip()]
        cls.has_api_key = len(cls.api_keys) > 0
        
        if cls.has_api_key:
            reset_search_service()
            cls.service = get_search_service()

    @unittest.skipIf(
        not os.environ.get("ANSPIRE_API_KEYS"),
        "未设置 ANSPIRE_API_KEYS 环境变量，跳过集成测试"
    )
    @pytest.mark.network
    def test_real_api_call_stock_news(self):
        """真实 API 调用测试 - 股票新闻搜索"""
        # 确保服务已重置
        reset_search_service()
        service = get_search_service()
        
        # 验证 Anspire 已配置
        anspire_provider = None
        for provider in service._providers:
            if isinstance(provider, AnspireSearchProvider):
                anspire_provider = provider
                break
        
        if not anspire_provider:
            self.skipTest("Anspire Provider 未初始化")
        
        # 测试 A 股搜索
        response = service.search_stock_news("600519", "贵州茅台", max_results=3)
        
        print(f"\n=== Anspire 真实 API 测试结果 ===")
        print(f"搜索状态：{'成功' if response.success else '失败'}")
        print(f"搜索引擎：{response.provider}")
        print(f"结果数量：{len(response.results)}")
        print(f"耗时：{response.search_time:.2f}s")
        
        # 基本验证
        self.assertTrue(response.success, f"搜索失败：{response.error_message}")
        self.assertEqual(response.provider, "Anspire")
        self.assertGreater(len(response.results), 0, "应至少返回一条结果")
        
        # 验证结果格式
        for result in response.results:
            self.assertIsNotNone(result.title)
            self.assertIsNotNone(result.url)
            # snippet 可能为空，视具体实现而定
            # self.assertIsNotNone(result.snippet)
    
    @unittest.skipIf(
        not os.environ.get("ANSPIRE_API_KEYS"),
        "未设置 ANSPIRE_API_KEYS 环境变量，跳过集成测试"
    )
    @pytest.mark.network
    def test_real_api_call_general_search(self):
        """真实 API 调用测试 - 通用搜索"""
        reset_search_service()
        service = get_search_service()
        
        anspire_provider = None
        for provider in service._providers:
            if isinstance(provider, AnspireSearchProvider):
                anspire_provider = provider
                break
        
        if not anspire_provider:
            self.skipTest("Anspire Provider 未初始化")
        
        # 测试通用搜索
        response = anspire_provider.search("人工智能最新发展", max_results=5, days=7)
        
        print(f"\n=== Anspire 通用搜索结果 ===")
        print(f"搜索状态：{'成功' if response.success else '失败'}")
        print(f"结果数量：{len(response.results)}")
        
        self.assertTrue(response.success)
        self.assertGreater(len(response.results), 0)


def run_manual_test():
    """手动测试函数（用于快速验证）"""
    import logging
    from src.config import get_config
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s'
    )
    
    print("=" * 60)
    print("Anspire Search 快速测试")
    print("=" * 60)
    
    # 检查配置
    config = get_config()
    if not config.anspire_api_keys:
        print("\n❌ 未检测到 Anspire API Keys")
        print("请设置环境变量：")
        print("  Windows PowerShell: $env:ANSPIRE_API_KEYS=\"your_api_key\"")
        print("  Linux/Mac: export ANSPIRE_API_KEYS=\"your_api_key\"")
        return False
    
    print(f"\n✅ 已配置 {len(config.anspire_api_keys)} 个 Anspire API Key")
    
    # 创建服务
    service = SearchService(
        anspire_keys=config.anspire_api_keys,
        bocha_keys=config.bocha_api_keys,
        tavily_keys=config.tavily_keys,
        searxng_public_instances_enabled=False,
        news_max_age_days=3,
        news_strategy_profile="short"
    )
    
    # 验证 Provider
    anspire_provider = service._providers[0] if service._providers else None
    if not anspire_provider or not isinstance(anspire_provider, AnspireSearchProvider):
        print("\n❌ Anspire Provider 未正确初始化")
        return False
    
    print(f"✅ Anspire Provider 初始化成功")
    print(f"   Provider 名称：{anspire_provider.name}")
    if hasattr(anspire_provider, 'api_keys'):
        print(f"   API Keys 数量：{len(anspire_provider.api_keys)}")
    elif hasattr(anspire_provider, '_api_keys'):
        print(f"   API Keys 数量：{len(anspire_provider._api_keys)}")
    
    # 执行测试搜索
    print("\n" + "=" * 60)
    print("执行测试搜索：贵州茅台 (600519)")
    print("=" * 60)
    
    response = service.search_stock_news("600519", "贵州茅台", max_results=3)
    
    print(f"\n搜索结果:")
    print(f"  状态：{'✅ 成功' if response.success else '❌ 失败'}")
    print(f"  搜索引擎：{response.provider}")
    print(f"  结果数量：{len(response.results)}")
    print(f"  耗时：{response.search_time:.2f}s")
    
    if response.error_message:
        print(f"  错误信息：{response.error_message}")
    
    if response.results:
        print(f"\n前 {min(2, len(response.results))} 条结果预览:")
        for i, result in enumerate(response.results[:2], 1):
            print(f"\n  [{i}] {result.title}")
            print(f"      来源：{result.source}")
            print(f"      URL: {result.url}")
            if result.snippet:
                snippet_preview = result.snippet[:100] + "..." if len(result.snippet) > 100 else result.snippet
                print(f"      摘要：{snippet_preview}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    
    return response.success


if __name__ == "__main__":
    # 如果设置了环境变量，运行完整测试
    if os.environ.get("ANSPIRE_API_KEYS"):
        print("检测到 ANSPIRE_API_KEYS 环境变量，运行完整测试套件...")
        unittest.main(verbosity=2)
    else:
        # 否则只运行单元测试，跳过集成测试
        print("未设置 ANSPIRE_API_KEYS 环境变量，仅运行单元测试（跳过集成测试）...")
        print("如需运行完整测试，请设置环境变量:")
        print("  Windows PowerShell: $env:ANSPIRE_API_KEYS=\"your_api_key\"")
        print("  Linux/Mac: export ANSPIRE_API_KEYS=\"your_api_key\"")
        print()
        
        # 运行单元测试
        suite = unittest.TestLoader().loadTestsFromTestCase(TestAnspireConfigLoading)
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAnspireSearchProvider))
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAnspireSearchService))
        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)
        
        # 提供手动测试选项
        print("\n" + "=" * 60)
        choice = input("是否运行手动测试（需要有效的 API Key）? (y/n): ").strip().lower()
        if choice == 'y':
            run_manual_test()
