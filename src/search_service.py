# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 搜索服务模块
===================================

职责：
1. 提供统一的新闻搜索接口
2. 支持 Bocha、Tavily、Brave、SerpAPI、SearXNG 多种搜索引擎
3. 多 Key 负载均衡和故障转移
4. 搜索结果缓存和格式化
"""

import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional, Tuple
from itertools import cycle
from urllib.parse import parse_qsl, unquote, urlparse
import requests
from newspaper import Article, Config
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from data_provider.us_index_mapping import is_us_index_code
from src.config import (
    NEWS_STRATEGY_WINDOWS,
    normalize_news_strategy_profile,
    resolve_news_window_days,
)

logger = logging.getLogger(__name__)

# Transient network errors (retryable)
_SEARCH_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_SEARCH_TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _post_with_retry(url: str, *, headers: Dict[str, str], json: Dict[str, Any], timeout: int) -> requests.Response:
    """POST with retry on transient SSL/network errors."""
    return requests.post(url, headers=headers, json=json, timeout=timeout)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(_SEARCH_TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _get_with_retry(
    url: str, *, headers: Dict[str, str], params: Dict[str, Any], timeout: int
) -> requests.Response:
    """GET with retry on transient SSL/network errors."""
    return requests.get(url, headers=headers, params=params, timeout=timeout)


def fetch_url_content(url: str, timeout: int = 5) -> str:
    """
    获取 URL 网页正文内容 (使用 newspaper3k)
    """
    try:
        # 配置 newspaper3k
        config = Config()
        config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        config.request_timeout = timeout
        config.fetch_images = False  # 不下载图片
        config.memoize_articles = False # 不缓存

        article = Article(url, config=config, language='zh') # 默认中文，但也支持其他
        article.download()
        article.parse()

        # 获取正文
        text = article.text.strip()

        # 简单的后处理，去除空行
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        return text[:1500]  # 限制返回长度（比 bs4 稍微多一点，因为 newspaper 解析更干净）
    except Exception as e:
        logger.debug(f"Fetch content failed for {url}: {e}")

    return ""


@dataclass
class SearchResult:
    """搜索结果数据类"""
    title: str
    snippet: str  # 摘要
    url: str
    source: str  # 来源网站
    published_date: Optional[str] = None
    
    def to_text(self) -> str:
        """转换为文本格式"""
        date_str = f" ({self.published_date})" if self.published_date else ""
        return f"【{self.source}】{self.title}{date_str}\n{self.snippet}"


@dataclass 
class SearchResponse:
    """搜索响应"""
    query: str
    results: List[SearchResult]
    provider: str  # 使用的搜索引擎
    success: bool = True
    error_message: Optional[str] = None
    search_time: float = 0.0  # 搜索耗时（秒）
    
    def to_context(self, max_results: int = 5) -> str:
        """将搜索结果转换为可用于 AI 分析的上下文"""
        if not self.success or not self.results:
            return f"搜索 '{self.query}' 未找到相关结果。"
        
        lines = [f"【{self.query} 搜索结果】（来源：{self.provider}）"]
        for i, result in enumerate(self.results[:max_results], 1):
            lines.append(f"\n{i}. {result.to_text()}")
        
        return "\n".join(lines)


class BaseSearchProvider(ABC):
    """搜索引擎基类"""
    
    def __init__(self, api_keys: List[str], name: str):
        """
        初始化搜索引擎
        
        Args:
            api_keys: API Key 列表（支持多个 key 负载均衡）
            name: 搜索引擎名称
        """
        self._api_keys = api_keys
        self._name = name
        self._key_cycle = cycle(api_keys) if api_keys else None
        self._key_usage: Dict[str, int] = {key: 0 for key in api_keys}
        self._key_errors: Dict[str, int] = {key: 0 for key in api_keys}
        self._state_lock = threading.RLock()
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def is_available(self) -> bool:
        """检查是否有可用的 API Key"""
        return bool(self._api_keys)
    
    def _get_next_key(self) -> Optional[str]:
        """
        获取下一个可用的 API Key（负载均衡）
        
        策略：轮询 + 跳过错误过多的 key
        """
        with self._state_lock:
            if not self._key_cycle:
                return None
            
            # 最多尝试所有 key
            for _ in range(len(self._api_keys)):
                key = next(self._key_cycle)
                # 跳过错误次数过多的 key（超过 3 次）
                if self._key_errors.get(key, 0) < 3:
                    return key
            
            # 所有 key 都有问题，重置错误计数并返回第一个
            logger.warning(f"[{self._name}] 所有 API Key 都有错误记录，重置错误计数")
            self._key_errors = {key: 0 for key in self._api_keys}
            return self._api_keys[0] if self._api_keys else None
    
    def _record_success(self, key: str) -> None:
        """记录成功使用"""
        with self._state_lock:
            self._key_usage[key] = self._key_usage.get(key, 0) + 1
            # 成功后减少错误计数
            if key in self._key_errors and self._key_errors[key] > 0:
                self._key_errors[key] -= 1
    
    def _record_error(self, key: str) -> None:
        """记录错误"""
        with self._state_lock:
            self._key_errors[key] = self._key_errors.get(key, 0) + 1
            error_count = self._key_errors[key]
        logger.warning(f"[{self._name}] API Key {key[:8]}... 错误计数: {error_count}")
    
    @abstractmethod
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        """执行搜索（子类实现）"""
        pass
    
    def _execute_search(
        self,
        query: str,
        *,
        max_results: int = 5,
        days: int = 7,
        api_key: Optional[str] = None,
        **search_kwargs: Any,
    ) -> SearchResponse:
        """Run the shared search flow with an optional preselected API key."""
        api_key = api_key or self._get_next_key()
        if not api_key:
            return SearchResponse(
                query=query,
                results=[],
                provider=self._name,
                success=False,
                error_message=f"{self._name} 未配置 API Key"
            )

        start_time = time.time()
        try:
            response = self._do_search(query, api_key, max_results, days=days, **search_kwargs)
            response.search_time = time.time() - start_time

            if response.success:
                self._record_success(api_key)
                logger.info(f"[{self._name}] 搜索 '{query}' 成功，返回 {len(response.results)} 条结果，耗时 {response.search_time:.2f}s")
            else:
                self._record_error(api_key)

            return response

        except Exception as e:
            self._record_error(api_key)
            elapsed = time.time() - start_time
            logger.error(f"[{self._name}] 搜索 '{query}' 失败: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self._name,
                success=False,
                error_message=str(e),
                search_time=elapsed
            )

    def search(self, query: str, max_results: int = 5, days: int = 7) -> SearchResponse:
        """
        执行搜索
        
        Args:
            query: 搜索关键词
            max_results: 最大返回结果数
            days: 搜索最近几天的时间范围（默认7天）
            
        Returns:
            SearchResponse 对象
        """
        return self._execute_search(query, max_results=max_results, days=days)


class TavilySearchProvider(BaseSearchProvider):
    """
    Tavily 搜索引擎
    
    特点：
    - 专为 AI/LLM 优化的搜索 API
    - 免费版每月 1000 次请求
    - 返回结构化的搜索结果
    
    文档：https://docs.tavily.com/
    """
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Tavily")
    
    def _do_search(
        self,
        query: str,
        api_key: str,
        max_results: int,
        days: int = 7,
        topic: Optional[str] = None,
    ) -> SearchResponse:
        """执行 Tavily 搜索"""
        try:
            from tavily import TavilyClient
        except ImportError:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="tavily-python 未安装，请运行: pip install tavily-python"
            )
        
        try:
            client = TavilyClient(api_key=api_key)
            
            # 执行搜索（优化：使用advanced深度、限制最近几天）
            search_kwargs: Dict[str, Any] = {
                "query": query,
                "search_depth": "advanced",  # advanced 获取更多结果
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "days": days,  # 搜索最近天数的内容
            }
            if topic is not None:
                search_kwargs["topic"] = topic

            response = client.search(
                **search_kwargs,
            )
            
            # 记录原始响应到日志
            logger.info(f"[Tavily] 搜索完成，query='{query}', 返回 {len(response.get('results', []))} 条结果")
            logger.debug(f"[Tavily] 原始响应: {response}")
            
            # 解析结果
            results = []
            for item in response.get('results', []):
                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=item.get('content', '')[:500],  # 截取前500字
                    url=item.get('url', ''),
                    source=self._extract_domain(item.get('url', '')),
                    published_date=item.get('published_date') or item.get('publishedDate'),
                ))
            
            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True,
            )
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是配额问题
            if 'rate limit' in error_msg.lower() or 'quota' in error_msg.lower():
                error_msg = f"API 配额已用尽: {error_msg}"
            
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )

    def search(
        self,
        query: str,
        max_results: int = 5,
        days: int = 7,
        topic: Optional[str] = None,
    ) -> SearchResponse:
        """执行 Tavily 搜索，可按调用方选择是否启用新闻 topic。"""
        if topic is None:
            return super().search(query, max_results=max_results, days=days)

        api_key = self._get_next_key()
        if not api_key:
            return SearchResponse(
                query=query,
                results=[],
                provider=self._name,
                success=False,
                error_message=f"{self._name} 未配置 API Key"
            )

        start_time = time.time()
        try:
            response = self._do_search(query, api_key, max_results, days=days, topic=topic)
            response.search_time = time.time() - start_time

            if response.success:
                self._record_success(api_key)
                logger.info(f"[{self._name}] 搜索 '{query}' 成功，返回 {len(response.results)} 条结果，耗时 {response.search_time:.2f}s")
            else:
                self._record_error(api_key)

            return response

        except Exception as e:
            self._record_error(api_key)
            elapsed = time.time() - start_time
            logger.error(f"[{self._name}] 搜索 '{query}' 失败: {e}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self._name,
                success=False,
                error_message=str(e),
                search_time=elapsed
            )
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名作为来源"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain or '未知来源'
        except Exception:
            return '未知来源'


class SerpAPISearchProvider(BaseSearchProvider):
    """
    SerpAPI 搜索引擎
    
    特点：
    - 支持 Google、Bing、百度等多种搜索引擎
    - 免费版每月 100 次请求
    - 返回真实的搜索结果
    
    文档：https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis
    """

    _ORGANIC_CONTENT_FETCH_LIMIT = 1
    _ORGANIC_CONTENT_FETCH_RANK_LIMIT = 2
    _ORGANIC_CONTENT_FETCH_TIMEOUT = 2
    _ORGANIC_SNIPPET_SUFFICIENT_LENGTH = 140
    _ORGANIC_FETCHED_PREVIEW_LENGTH = 320
    _SKIPPED_CONTENT_FETCH_SUFFIXES = (
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".svg",
        ".webp",
        ".zip",
        ".rar",
        ".7z",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".csv",
    )
    _SKIPPED_CONTENT_FETCH_QUERY_KEYS = {
        "attachment",
        "attachment_file",
        "doc",
        "document",
        "download",
        "download_file",
        "file",
        "file_name",
        "filename",
        "file_path",
        "filepath",
        "resource",
        "resource_file",
    }
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "SerpAPI")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        """执行 SerpAPI 搜索"""
        try:
            from serpapi import GoogleSearch
        except ImportError:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="google-search-results 未安装，请运行: pip install google-search-results"
            )
        
        try:
            # 确定时间范围参数 tbs
            tbs = "qdr:w"  # 默认一周
            if days <= 1:
                tbs = "qdr:d"  # 过去24小时
            elif days <= 7:
                tbs = "qdr:w"  # 过去一周
            elif days <= 30:
                tbs = "qdr:m"  # 过去一月
            else:
                tbs = "qdr:y"  # 过去一年

            # 使用 Google 搜索 (获取 Knowledge Graph, Answer Box 等)
            params = {
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "google_domain": "google.com.hk", # 使用香港谷歌，中文支持较好
                "hl": "zh-cn",  # 中文界面
                "gl": "cn",     # 中国地区偏好
                "tbs": tbs,     # 时间范围限制
                "num": max_results # 请求的结果数量，注意：Google API有时不严格遵守
            }
            
            search = GoogleSearch(params)
            response = search.get_dict()
            
            # 记录原始响应到日志
            logger.debug(f"[SerpAPI] 原始响应 keys: {response.keys()}")
            
            # 解析结果
            results = []
            
            # 1. 解析 Knowledge Graph (知识图谱)
            kg = response.get('knowledge_graph', {})
            if kg:
                title = kg.get('title', '知识图谱')
                desc = kg.get('description', '')
                
                # 提取额外属性
                details = []
                for key in ['type', 'founded', 'headquarters', 'employees', 'ceo']:
                    val = kg.get(key)
                    if val:
                        details.append(f"{key}: {val}")
                        
                snippet = f"{desc}\n" + " | ".join(details) if details else desc
                
                results.append(SearchResult(
                    title=f"[知识图谱] {title}",
                    snippet=snippet,
                    url=kg.get('source', {}).get('link', ''),
                    source="Google Knowledge Graph"
                ))
                
            # 2. 解析 Answer Box (精选回答/行情卡片)
            ab = response.get('answer_box', {})
            if ab:
                ab_title = ab.get('title', '精选回答')
                ab_snippet = ""
                
                # 财经类回答
                if ab.get('type') == 'finance_results':
                    stock = ab.get('stock', '')
                    price = ab.get('price', '')
                    currency = ab.get('currency', '')
                    movement = ab.get('price_movement', {})
                    mv_val = movement.get('percentage', 0)
                    mv_dir = movement.get('movement', '')
                    
                    ab_title = f"[行情卡片] {stock}"
                    ab_snippet = f"价格: {price} {currency}\n涨跌: {mv_dir} {mv_val}%"
                    
                    # 提取表格数据
                    if 'table' in ab:
                        table_data = []
                        for row in ab['table']:
                            if 'name' in row and 'value' in row:
                                table_data.append(f"{row['name']}: {row['value']}")
                        if table_data:
                            ab_snippet += "\n" + "; ".join(table_data)
                            
                # 普通文本回答
                elif 'snippet' in ab:
                    ab_snippet = ab.get('snippet', '')
                    list_items = ab.get('list', [])
                    if list_items:
                        ab_snippet += "\n" + "\n".join([f"- {item}" for item in list_items])
                
                elif 'answer' in ab:
                    ab_snippet = ab.get('answer', '')
                    
                if ab_snippet:
                    results.append(SearchResult(
                        title=f"[精选回答] {ab_title}",
                        snippet=ab_snippet,
                        url=ab.get('link', '') or ab.get('displayed_link', ''),
                        source="Google Answer Box"
                    ))

            # 3. 解析 Related Questions (相关问题)
            rqs = response.get('related_questions', [])
            for rq in rqs[:3]: # 取前3个
                question = rq.get('question', '')
                snippet = rq.get('snippet', '')
                link = rq.get('link', '')
                
                if question and snippet:
                     results.append(SearchResult(
                        title=f"[相关问题] {question}",
                        snippet=snippet,
                        url=link,
                        source="Google Related Questions"
                     ))

            # 4. 解析 Organic Results (自然搜索结果)
            organic_results = response.get('organic_results', [])
            organic_content_fetch_attempts = 0

            for rank, item in enumerate(organic_results[:max_results]):
                link = item.get('link', '')
                rich_extensions = self._extract_rich_snippet_extensions(item)
                snippet = self._build_organic_snippet(item, rich_extensions=rich_extensions)

                if self._should_fetch_organic_content(
                    link=link,
                    snippet=snippet,
                    rank=rank,
                    fetched_count=organic_content_fetch_attempts,
                    has_structured_summary=bool(rich_extensions),
                ):
                    organic_content_fetch_attempts += 1
                    try:
                        fetched_content = fetch_url_content(
                            link,
                            timeout=self._ORGANIC_CONTENT_FETCH_TIMEOUT,
                        )
                        if fetched_content:
                            snippet = self._merge_organic_snippet_with_content(
                                snippet,
                                fetched_content,
                            )
                    except Exception as e:
                        logger.debug(f"[SerpAPI] Fetch content failed: {e}")

                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=snippet[:1000], # 限制总长度
                    url=link,
                    source=item.get('source', self._extract_domain(link)),
                    published_date=item.get('date'),
                ))

            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True,
            )
            
        except Exception as e:
            error_msg = str(e)
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名"""
        try:
            parsed = urlparse(url)
            return parsed.netloc.replace('www.', '') or '未知来源'
        except Exception:
            return '未知来源'

    @classmethod
    def _normalize_organic_text(cls, value: Any) -> str:
        """标准化 SerpAPI organic 文本字段。"""
        text = "" if value is None else str(value)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _extract_rich_snippet_extensions(cls, item: Dict[str, Any]) -> List[str]:
        """提取 rich_snippet 中已有的结构化摘要，优先复用 API 原始返回。"""
        rich_snippet = item.get("rich_snippet")
        if not isinstance(rich_snippet, dict):
            return []

        extensions: List[str] = []
        seen: set[str] = set()

        for section in ("top", "bottom"):
            section_data = rich_snippet.get(section)
            if not isinstance(section_data, dict):
                continue

            raw_extensions = section_data.get("extensions")
            if isinstance(raw_extensions, (list, tuple, set)):
                for raw_value in raw_extensions:
                    value = cls._normalize_organic_text(raw_value)
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    extensions.append(value)

            for raw_value in cls._flatten_rich_snippet_values(
                section_data.get("detected_extensions")
            ):
                if raw_value in seen:
                    continue
                seen.add(raw_value)
                extensions.append(raw_value)

        return extensions

    @classmethod
    def _flatten_rich_snippet_values(
        cls,
        value: Any,
        *,
        label: Optional[str] = None,
        allow_unlabeled_scalar: bool = False,
    ) -> List[str]:
        """把 rich_snippet.detected_extensions 展平为可读文本。"""
        if isinstance(value, dict):
            flattened: List[str] = []
            for key, nested_value in value.items():
                flattened.extend(
                    cls._flatten_rich_snippet_values(
                        nested_value,
                        label=cls._normalize_organic_text(str(key)).replace("_", " "),
                    )
                )
            return flattened

        if isinstance(value, (list, tuple, set)):
            flattened: List[str] = []
            for nested_value in value:
                flattened.extend(
                    cls._flatten_rich_snippet_values(
                        nested_value,
                        label=label,
                        allow_unlabeled_scalar=True,
                    )
                )
            return flattened

        text = cls._normalize_organic_text(value)
        if not text:
            return []

        if label:
            return [f"{label}: {text}"]

        if allow_unlabeled_scalar:
            return [text]

        return []

    @classmethod
    def _build_organic_snippet(
        cls,
        item: Dict[str, Any],
        *,
        rich_extensions: Optional[List[str]] = None,
    ) -> str:
        """构建 organic result 摘要，尽量先消费 SerpAPI 已返回的信息。"""
        snippet = cls._normalize_organic_text(item.get("snippet", ""))
        if rich_extensions is None:
            rich_extensions = cls._extract_rich_snippet_extensions(item)

        if rich_extensions:
            rich_text = " | ".join(rich_extensions)
            if rich_text and rich_text not in snippet:
                snippet = f"{snippet}\n{rich_text}".strip() if snippet else rich_text

        return snippet

    @classmethod
    def _matches_skipped_content_fetch_suffix(cls, value: Any) -> bool:
        """判断链接片段是否指向附件或其他非 HTML 资源。"""
        normalized_value = cls._normalize_organic_text(value).lower()
        if not normalized_value:
            return False

        decoded_value = unquote(normalized_value)
        if decoded_value.endswith(cls._SKIPPED_CONTENT_FETCH_SUFFIXES):
            return True

        return urlparse(decoded_value).path.lower().endswith(
            cls._SKIPPED_CONTENT_FETCH_SUFFIXES
        )

    @classmethod
    def _matches_skipped_content_fetch_query_param(
        cls, key: Any, value: Any
    ) -> bool:
        """仅对少数显式附件参数跳过正文抓取，避免误伤普通 HTML 页面。"""
        normalized_key = cls._normalize_organic_text(key)
        if not normalized_key:
            return False

        snake_key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized_key)
        canonical_key = re.sub(r"[^a-z0-9]+", "_", snake_key.lower()).strip("_")
        if canonical_key not in cls._SKIPPED_CONTENT_FETCH_QUERY_KEYS:
            return False

        return cls._matches_skipped_content_fetch_suffix(value)

    @classmethod
    def _should_fetch_organic_content(
        cls,
        *,
        link: Any,
        snippet: str,
        rank: int,
        fetched_count: int,
        has_structured_summary: bool,
    ) -> bool:
        """仅对极少量高位且摘要明显不足的结果补抓正文。"""
        if fetched_count >= cls._ORGANIC_CONTENT_FETCH_LIMIT:
            return False

        if rank >= cls._ORGANIC_CONTENT_FETCH_RANK_LIMIT:
            return False

        if has_structured_summary:
            return False

        if len(snippet) >= cls._ORGANIC_SNIPPET_SUFFICIENT_LENGTH:
            return False

        if not isinstance(link, str):
            return False

        if not link or not link.startswith(("http://", "https://")):
            return False

        parsed_link = urlparse(link)
        if parsed_link.scheme not in {"http", "https"}:
            return False

        if cls._matches_skipped_content_fetch_suffix(parsed_link.path):
            return False

        for key, value in parse_qsl(parsed_link.query, keep_blank_values=True):
            if cls._matches_skipped_content_fetch_query_param(key, value):
                return False

        return True

    @classmethod
    def _merge_organic_snippet_with_content(cls, snippet: str, content: str) -> str:
        """用较短正文预览补强 snippet，避免拉长单次搜索耗时和返回体积。"""
        normalized = cls._normalize_organic_text(content)
        if not normalized:
            return snippet

        preview = normalized[:cls._ORGANIC_FETCHED_PREVIEW_LENGTH]
        if len(normalized) > cls._ORGANIC_FETCHED_PREVIEW_LENGTH:
            preview = f"{preview}..."

        if snippet:
            return f"{snippet}\n\n【网页详情】\n{preview}"

        return f"【网页详情】\n{preview}"


class BochaSearchProvider(BaseSearchProvider):
    """
    博查搜索引擎
    
    特点：
    - 专为AI优化的中文搜索API
    - 结果准确、摘要完整
    - 支持时间范围过滤和AI摘要
    - 兼容Bing Search API格式
    
    文档：https://bocha-ai.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK
    """
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Bocha")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        """执行博查搜索"""
        try:
            import requests
        except ImportError:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="requests 未安装，请运行: pip install requests"
            )
        
        try:
            # API 端点
            url = "https://api.bocha.cn/v1/web-search"
            
            # 请求头
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            # 确定时间范围
            freshness = "oneWeek"
            if days <= 1:
                freshness = "oneDay"
            elif days <= 7:
                freshness = "oneWeek"
            elif days <= 30:
                freshness = "oneMonth"
            else:
                freshness = "oneYear"

            # 请求参数（严格按照API文档）
            payload = {
                "query": query,
                "freshness": freshness,  # 动态时间范围
                "summary": True,  # 启用AI摘要
                "count": min(max_results, 50)  # 最大50条
            }
            
            # 执行搜索（带瞬时 SSL/网络错误重试）
            response = _post_with_retry(url, headers=headers, json=payload, timeout=10)
            
            # 检查HTTP状态码
            if response.status_code != 200:
                # 尝试解析错误信息
                try:
                    if response.headers.get('content-type', '').startswith('application/json'):
                        error_data = response.json()
                        error_message = error_data.get('message', response.text)
                    else:
                        error_message = response.text
                except Exception:
                    error_message = response.text
                
                # 根据错误码处理
                if response.status_code == 403:
                    error_msg = f"余额不足: {error_message}"
                elif response.status_code == 401:
                    error_msg = f"API KEY无效: {error_message}"
                elif response.status_code == 400:
                    error_msg = f"请求参数错误: {error_message}"
                elif response.status_code == 429:
                    error_msg = f"请求频率达到限制: {error_message}"
                else:
                    error_msg = f"HTTP {response.status_code}: {error_message}"
                
                logger.warning(f"[Bocha] 搜索失败: {error_msg}")
                
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            # 解析响应
            try:
                data = response.json()
            except ValueError as e:
                error_msg = f"响应JSON解析失败: {str(e)}"
                logger.error(f"[Bocha] {error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            # 检查响应code
            if data.get('code') != 200:
                error_msg = data.get('msg') or f"API返回错误码: {data.get('code')}"
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            # 记录原始响应到日志
            logger.info(f"[Bocha] 搜索完成，query='{query}'")
            logger.debug(f"[Bocha] 原始响应: {data}")
            
            # 解析搜索结果
            results = []
            web_pages = data.get('data', {}).get('webPages', {})
            value_list = web_pages.get('value', [])
            
            for item in value_list[:max_results]:
                # 优先使用summary（AI摘要），fallback到snippet
                snippet = item.get('summary') or item.get('snippet', '')
                
                # 截取摘要长度
                if snippet:
                    snippet = snippet[:500]
                
                results.append(SearchResult(
                    title=item.get('name', ''),
                    snippet=snippet,
                    url=item.get('url', ''),
                    source=item.get('siteName') or self._extract_domain(item.get('url', '')),
                    published_date=item.get('datePublished'),  # UTC+8格式，无需转换
                ))
            
            logger.info(f"[Bocha] 成功解析 {len(results)} 条结果")
            
            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True,
            )
            
        except requests.exceptions.Timeout:
            error_msg = "请求超时"
            logger.error(f"[Bocha] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {str(e)}"
            logger.error(f"[Bocha] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"[Bocha] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名作为来源"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain or '未知来源'
        except Exception:
            return '未知来源'


class AnspireSearchProvider(BaseSearchProvider):
    """
    Anspire Search 搜索引擎
    
    特点：
    - 面向AI生态的下一代实时智能搜索引擎
    - 结果精准、响应快速
    - 适用于股票新闻和市场情报搜索
    
    文档: https://open.anspire.cn/document/docs/searchApi/
    """
    
    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Anspire")
    
    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        """执行 Anspire 搜索"""
        try:
            import requests
        except ImportError:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="requests 未安装，请运行：pip install requests"
            )
        
        try:
            # API 端点
            url = "https://plugin.anspire.cn/api/ntsearch/search"
            
            # 请求头
            headers = {
                'Authorization': f'Bearer {api_key}'
            }

            # 请求参数
            payload = {
                "query": query,
                "top_k": min(max_results,50), 
                "FromTime": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"),
                "ToTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 执行搜索
            response = _get_with_retry(url, headers=headers, params=payload, timeout=10)
            
            # 检查 HTTP 状态码
            if response.status_code != 200:
                # 尝试解析错误信息
                try:
                    if response.headers.get('content-type', '').startswith('application/json'):
                        error_data = response.json()
                        error_message = error_data.get('message', response.text)
                    else:
                        error_message = response.text
                except Exception:
                    error_message = response.text
                
                # 根据错误码处理
                if response.status_code == 403:
                    error_msg = f"余额不足或权限不足：{error_message}"
                elif response.status_code == 401:
                    error_msg = f"API KEY 无效：{error_message}"
                elif response.status_code == 400:
                    error_msg = f"请求参数错误：{error_message}"
                else:
                    error_msg = f"HTTP {response.status_code}: {error_message}"
                
                logger.warning(f"[Anspire] 搜索失败：{error_msg}")
                
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            # 解析响应
            try:
                data = response.json()
            except ValueError as e:
                error_msg = f"响应 JSON 解析失败：{str(e)}"
                logger.error(f"[Anspire] {error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            if 'code' in data and data.get('code') != 200:
                error_msg = data.get('msg') or f"API 返回错误码：{data.get('code')}"
                logger.warning(f"[Anspire] 搜索失败：{error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            if 'results' not in data:
                error_msg = "响应中缺少 results 字段"
                logger.error(f"[Anspire] {error_msg}，原始响应：{data}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )
            
            # 记录原始响应到日志
            logger.info(f"[Anspire] 搜索完成，query='{query}'")
            logger.debug(f"[Anspire] 原始响应：{data}")
            
            results = []
            value_list = data.get('results', [])
            
            for item in value_list[:max_results]:
                snippet = item.get('content')
                if snippet and isinstance(snippet, str) and len(snippet) > 500:
                    snippet = snippet[:500] + "..."
                
                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=snippet,
                    url=item.get('url', ''),
                    source=self._extract_domain(item.get('url', '')),
                    published_date=item.get('date', '')
                ))
            
            logger.info(f"[Anspire] 成功解析 {len(results)} 条结果")
            
            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True,
            )
            
        except requests.exceptions.Timeout:
            error_msg = "请求超时"
            logger.error(f"[Anspire] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败：{str(e)}"
            logger.error(f"[Anspire] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except Exception as e:
            error_msg = f"未知错误：{str(e)}"
            logger.error(f"[Anspire] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
    
    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名作为来源"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain or '未知来源'
        except Exception:
            return '未知来源'


class MiniMaxSearchProvider(BaseSearchProvider):
    """
    MiniMax Web Search (Coding Plan API)

    Features:
    - Backed by MiniMax Coding Plan subscription
    - Returns structured organic results with title/link/snippet/date
    - No native time-range parameter; time filtering is done via query
      augmentation and client-side date filtering
    - Circuit-breaker protection: 3 consecutive failures -> 300s cooldown

    API endpoint: POST https://api.minimaxi.com/v1/coding_plan/search
    """

    API_ENDPOINT = "https://api.minimaxi.com/v1/coding_plan/search"

    # Circuit-breaker settings
    _CB_FAILURE_THRESHOLD = 3
    _CB_COOLDOWN_SECONDS = 300  # 5 minutes

    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "MiniMax")
        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check availability considering circuit breaker state."""
        with self._state_lock:
            if not self._api_keys:
                return False
            if self._consecutive_failures >= self._CB_FAILURE_THRESHOLD:
                if time.time() < self._circuit_open_until:
                    return False
                # Cooldown expired -> half-open, allow one probe
            return True

    def _record_success(self, key: str) -> None:
        with self._state_lock:
            super()._record_success(key)
            # Reset circuit breaker on success
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0

    def _record_error(self, key: str) -> None:
        warning_message = None
        with self._state_lock:
            super()._record_error(key)
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._CB_FAILURE_THRESHOLD:
                self._circuit_open_until = time.time() + self._CB_COOLDOWN_SECONDS
                warning_message = (
                    f"[MiniMax] Circuit breaker OPEN – "
                    f"{self._consecutive_failures} consecutive failures, "
                    f"cooldown {self._CB_COOLDOWN_SECONDS}s"
                )
        if warning_message:
            logger.warning(warning_message)

    # ------------------------------------------------------------------
    # Time-range helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _time_hint(days: int, is_chinese: bool = True) -> str:
        """Build a time-hint string to append to the search query."""
        if is_chinese:
            if days <= 1:
                return "今天"
            elif days <= 3:
                return "最近三天"
            elif days <= 7:
                return "最近一周"
            else:
                return "最近一个月"
        else:
            if days <= 1:
                return "today"
            elif days <= 3:
                return "past 3 days"
            elif days <= 7:
                return "past week"
            else:
                return "past month"

    @staticmethod
    def _is_within_days(date_str: Optional[str], days: int) -> bool:
        """Check whether *date_str* falls within the last *days* days.

        Accepts common formats: ``2025-06-01``, ``2025/06/01``,
        ``Jun 1, 2025``, ISO-8601 with timezone, etc.
        Returns True when date_str is None or unparseable (keep the result).
        """
        if not date_str:
            return True
        try:
            from dateutil import parser as dateutil_parser
            dt = dateutil_parser.parse(date_str, fuzzy=True)
            from datetime import timedelta, timezone
            now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
            return (now - dt) <= timedelta(days=days + 1)  # +1 buffer
        except Exception:
            return True  # Keep result when date is unparseable

    # ------------------------------------------------------------------

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        """Execute MiniMax web search."""
        try:
            # Detect language hint from query (simple heuristic)
            has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in query)
            time_hint = self._time_hint(days, is_chinese=has_cjk)
            augmented_query = f"{query} {time_hint}"

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'MM-API-Source': 'Minimax-MCP',
            }
            payload = {"q": augmented_query}

            response = _post_with_retry(
                self.API_ENDPOINT, headers=headers, json=payload, timeout=15
            )

            # HTTP error handling
            if response.status_code != 200:
                error_msg = self._parse_http_error(response)
                logger.warning(f"[MiniMax] Search failed: {error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg,
                )

            data = response.json()

            # Check base_resp status
            base_resp = data.get('base_resp', {})
            if base_resp.get('status_code', 0) != 0:
                error_msg = base_resp.get('status_msg', 'Unknown API error')
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg,
                )

            logger.info(f"[MiniMax] Search done, query='{query}'")
            logger.debug(f"[MiniMax] Raw response keys: {list(data.keys())}")

            # Parse organic results
            results: List[SearchResult] = []
            for item in data.get('organic', []):
                date_val = item.get('date')

                # Client-side time filtering
                if not self._is_within_days(date_val, days):
                    continue

                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=(item.get('snippet', '') or '')[:500],
                    url=item.get('link', ''),
                    source=self._extract_domain(item.get('link', '')),
                    published_date=date_val,
                ))

                if len(results) >= max_results:
                    break

            logger.info(f"[MiniMax] Parsed {len(results)} results (after time filter)")

            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True,
            )

        except requests.exceptions.Timeout:
            error_msg = "Request timeout"
            logger.error(f"[MiniMax] {error_msg}")
            return SearchResponse(
                query=query, results=[], provider=self.name,
                success=False, error_message=error_msg,
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {e}"
            logger.error(f"[MiniMax] {error_msg}")
            return SearchResponse(
                query=query, results=[], provider=self.name,
                success=False, error_message=error_msg,
            )
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            logger.error(f"[MiniMax] {error_msg}")
            return SearchResponse(
                query=query, results=[], provider=self.name,
                success=False, error_message=error_msg,
            )

    @staticmethod
    def _parse_http_error(response) -> str:
        """Parse HTTP error response from MiniMax API."""
        try:
            ct = response.headers.get('content-type', '')
            if 'json' in ct:
                err = response.json()
                base_resp = err.get('base_resp', {})
                msg = base_resp.get('status_msg') or err.get('message') or str(err)
                return msg
            return response.text[:200]
        except Exception:
            return f"HTTP {response.status_code}: {response.text[:200]}"

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL as source label."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain or '未知来源'
        except Exception:
            return '未知来源'


class BraveSearchProvider(BaseSearchProvider):
    """
    Brave Search 搜索引擎

    特点：
    - 隐私优先的独立搜索引擎
    - 索引超过300亿页面
    - 免费层可用
    - 支持时间范围过滤

    文档：https://brave.com/search/api/
    """

    API_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_keys: List[str]):
        super().__init__(api_keys, "Brave")

    def _do_search(
        self,
        query: str,
        api_key: str,
        max_results: int,
        days: int = 7,
        search_lang: Optional[str] = None,
        country: Optional[str] = None,
    ) -> SearchResponse:
        """执行 Brave 搜索"""
        try:
            # 请求头
            headers = {
                'X-Subscription-Token': api_key,
                'Accept': 'application/json'
            }

            # 确定时间范围（freshness 参数）
            if days <= 1:
                freshness = "pd"  # Past day (24小时)
            elif days <= 7:
                freshness = "pw"  # Past week
            elif days <= 30:
                freshness = "pm"  # Past month
            else:
                freshness = "py"  # Past year

            # 请求参数
            params = {
                "q": query,
                "count": min(max_results, 20),  # Brave 最大支持20条
                "freshness": freshness,
                "safesearch": "moderate"
            }
            if search_lang:
                params["search_lang"] = search_lang
            if country:
                params["country"] = country

            # 执行搜索（GET 请求）
            response = requests.get(
                self.API_ENDPOINT,
                headers=headers,
                params=params,
                timeout=10
            )

            # 检查HTTP状态码
            if response.status_code != 200:
                error_msg = self._parse_error(response)
                logger.warning(f"[Brave] 搜索失败: {error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )

            # 解析响应
            try:
                data = response.json()
            except ValueError as e:
                error_msg = f"响应JSON解析失败: {str(e)}"
                logger.error(f"[Brave] {error_msg}")
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg
                )

            logger.info(f"[Brave] 搜索完成，query='{query}'")
            logger.debug(f"[Brave] 原始响应: {data}")

            # 解析搜索结果
            results = []
            web_data = data.get('web', {})
            web_results = web_data.get('results', [])

            for item in web_results[:max_results]:
                # 解析发布日期（ISO 8601 格式）
                published_date = None
                age = item.get('age') or item.get('page_age')
                if age:
                    try:
                        # 转换 ISO 格式为简单日期字符串
                        dt = datetime.fromisoformat(age.replace('Z', '+00:00'))
                        published_date = dt.strftime('%Y-%m-%d')
                    except (ValueError, AttributeError):
                        published_date = age  # 解析失败时使用原始值

                results.append(SearchResult(
                    title=item.get('title', ''),
                    snippet=item.get('description', '')[:500],  # 截取到500字符
                    url=item.get('url', ''),
                    source=self._extract_domain(item.get('url', '')),
                    published_date=published_date
                ))

            logger.info(f"[Brave] 成功解析 {len(results)} 条结果")

            return SearchResponse(
                query=query,
                results=results,
                provider=self.name,
                success=True
            )

        except requests.exceptions.Timeout:
            error_msg = "请求超时"
            logger.error(f"[Brave] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {str(e)}"
            logger.error(f"[Brave] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"[Brave] {error_msg}")
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=error_msg
            )

    def _parse_error(self, response) -> str:
        """解析错误响应"""
        try:
            if response.headers.get('content-type', '').startswith('application/json'):
                error_data = response.json()
                # Brave API 返回的错误格式
                if 'message' in error_data:
                    return error_data['message']
                if 'error' in error_data:
                    return error_data['error']
                return str(error_data)
            return response.text[:200]
        except Exception:
            return f"HTTP {response.status_code}: {response.text[:200]}"

    @staticmethod
    def _extract_domain(url: str) -> str:
        """从 URL 提取域名作为来源"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain or '未知来源'
        except Exception:
            return '未知来源'

    def search(
        self,
        query: str,
        max_results: int = 5,
        days: int = 7,
        search_lang: Optional[str] = None,
        country: Optional[str] = None,
    ) -> SearchResponse:
        """执行 Brave 搜索，可按调用方传入区域与语言偏好。"""
        if search_lang is None and country is None:
            return super().search(query, max_results=max_results, days=days)

        return self._execute_search(
            query,
            max_results=max_results,
            days=days,
            search_lang=search_lang,
            country=country,
        )


class SearXNGSearchProvider(BaseSearchProvider):
    """
    SearXNG search engine (self-hosted, no quota).

    Self-hosted instances are used when explicitly configured.
    Otherwise, the provider can lazily discover public instances from
    searx.space and rotate across them with per-request failover.
    """

    PUBLIC_INSTANCES_URL = "https://searx.space/data/instances.json"
    PUBLIC_INSTANCES_CACHE_TTL_SECONDS = 3600
    PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS = 60
    PUBLIC_INSTANCES_POOL_LIMIT = 20
    PUBLIC_INSTANCES_MAX_ATTEMPTS = 3
    PUBLIC_INSTANCES_TIMEOUT_SECONDS = 5
    SELF_HOSTED_TIMEOUT_SECONDS = 10

    _public_instances_cache: Optional[Tuple[float, List[str]]] = None
    _public_instances_stale_retry_after: float = 0.0
    _public_instances_lock = threading.Lock()

    def __init__(self, base_urls: Optional[List[str]] = None, *, use_public_instances: bool = False):
        normalized_base_urls = [url.rstrip("/") for url in (base_urls or []) if url.strip()]
        super().__init__(normalized_base_urls, "SearXNG")
        self._base_urls = normalized_base_urls
        self._use_public_instances = bool(use_public_instances and not self._base_urls)
        self._cursor = 0
        self._cursor_lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        return bool(self._base_urls) or self._use_public_instances

    @classmethod
    def reset_public_instance_cache(cls) -> None:
        """Reset the shared searx.space cache (used by tests)."""
        with cls._public_instances_lock:
            cls._public_instances_cache = None
            cls._public_instances_stale_retry_after = 0.0

    @staticmethod
    def _parse_http_error(response) -> str:
        """Parse HTTP error details for easier diagnostics."""
        try:
            raw_content_type = response.headers.get("content-type", "")
            content_type = raw_content_type if isinstance(raw_content_type, str) else ""
            if "json" in content_type:
                error_data = response.json()
                if isinstance(error_data, dict):
                    message = error_data.get("error") or error_data.get("message")
                    if message:
                        return str(message)
                return str(error_data)
            raw_text = getattr(response, "text", "")
            body = raw_text.strip() if isinstance(raw_text, str) else ""
            return body[:200] if body else f"HTTP {response.status_code}"
        except Exception:
            raw_text = getattr(response, "text", "")
            body = raw_text if isinstance(raw_text, str) else ""
            return f"HTTP {response.status_code}: {body[:200]}"

    @staticmethod
    def _time_range(days: int) -> str:
        if days <= 1:
            return "day"
        if days <= 7:
            return "week"
        if days <= 30:
            return "month"
        return "year"

    @classmethod
    def _search_latency_seconds(cls, instance_data: Dict[str, Any]) -> float:
        timing = (instance_data.get("timing") or {}).get("search") or {}
        all_timing = timing.get("all")
        if isinstance(all_timing, dict):
            for key in ("mean", "median"):
                value = all_timing.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
        return float("inf")

    @classmethod
    def _extract_public_instances(cls, payload: Any) -> List[str]:
        if not isinstance(payload, dict):
            return []

        instances = payload.get("instances")
        if not isinstance(instances, dict):
            return []

        ranked: List[Tuple[float, float, str]] = []
        for raw_url, item in instances.items():
            if not isinstance(raw_url, str) or not isinstance(item, dict):
                continue
            if item.get("network_type") != "normal":
                continue
            http_status = (item.get("http") or {}).get("status_code")
            if http_status != 200:
                continue
            timing = (item.get("timing") or {}).get("search") or {}
            uptime = timing.get("success_percentage")
            if not isinstance(uptime, (int, float)) or float(uptime) <= 0:
                continue

            ranked.append(
                (
                    float(uptime),
                    cls._search_latency_seconds(item),
                    raw_url.rstrip("/"),
                )
            )

        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return [url for _, _, url in ranked[: cls.PUBLIC_INSTANCES_POOL_LIMIT]]

    @classmethod
    def _get_public_instances(cls) -> List[str]:
        now = time.time()
        with cls._public_instances_lock:
            stale_urls: List[str] = []
            if cls._public_instances_cache is None and cls._public_instances_stale_retry_after > now:
                logger.debug(
                    "[SearXNG] 公共实例冷启动刷新退避中，剩余 %.0fs",
                    cls._public_instances_stale_retry_after - now,
                )
                return []
            if cls._public_instances_cache is not None:
                cached_at, cached_urls = cls._public_instances_cache
                if now - cached_at < cls.PUBLIC_INSTANCES_CACHE_TTL_SECONDS:
                    return list(cached_urls)
                stale_urls = list(cached_urls)
                if cls._public_instances_stale_retry_after > now:
                    logger.debug(
                        "[SearXNG] 公共实例刷新退避中，继续使用过期缓存，剩余 %.0fs",
                        cls._public_instances_stale_retry_after - now,
                    )
                    return stale_urls

            try:
                response = requests.get(
                    cls.PUBLIC_INSTANCES_URL,
                    timeout=cls.PUBLIC_INSTANCES_TIMEOUT_SECONDS,
                )
                if response.status_code != 200:
                    logger.warning(
                        "[SearXNG] 拉取公共实例列表失败: HTTP %s",
                        response.status_code,
                    )
                else:
                    urls = cls._extract_public_instances(response.json())
                    if urls:
                        cls._public_instances_cache = (now, list(urls))
                        cls._public_instances_stale_retry_after = 0.0
                        logger.info("[SearXNG] 已刷新公共实例池，共 %s 个候选实例", len(urls))
                        return list(urls)
                    logger.warning("[SearXNG] searx.space 未返回可用公共实例，保留已有缓存")
            except Exception as exc:
                logger.warning("[SearXNG] 拉取公共实例列表失败: %s", exc)

            if stale_urls:
                cls._public_instances_stale_retry_after = (
                    now + cls.PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS
                )
                logger.warning(
                    "[SearXNG] 公共实例刷新失败，继续使用过期缓存，共 %s 个候选实例；"
                    "%.0fs 内不再刷新",
                    len(stale_urls),
                    cls.PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS,
                )
                return stale_urls
            cls._public_instances_stale_retry_after = (
                now + cls.PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS
            )
            logger.warning(
                "[SearXNG] 公共实例冷启动刷新失败，%.0fs 内不再刷新",
                cls.PUBLIC_INSTANCES_STALE_REFRESH_BACKOFF_SECONDS,
            )
            return []

    def _rotate_candidates(self, pool: List[str], *, max_attempts: int) -> List[str]:
        if not pool or max_attempts <= 0:
            return []
        with self._cursor_lock:
            start = self._cursor % len(pool)
            self._cursor = (self._cursor + 1) % len(pool)
        ordered = pool[start:] + pool[:start]
        return ordered[:max_attempts]

    def _do_search(  # type: ignore[override]
        self,
        query: str,
        base_url: str,
        max_results: int,
        days: int = 7,
        *,
        timeout: int,
        retry_enabled: bool,
    ) -> SearchResponse:
        """Execute one SearXNG search against a specific instance."""
        try:
            base = base_url.rstrip("/")
            search_url = base if base.endswith("/search") else base + "/search"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            params = {
                "q": query,
                "format": "json",
                "time_range": self._time_range(days),
                "pageno": 1,
            }

            request_get = _get_with_retry if retry_enabled else requests.get
            response = request_get(search_url, headers=headers, params=params, timeout=timeout)

            if response.status_code != 200:
                error_msg = self._parse_http_error(response)
                if response.status_code == 403:
                    error_msg = (
                        f"{error_msg}；SearXNG 实例可能未启用 JSON 输出（请检查 settings.yml），"
                        "或实例/代理拒绝了本次访问"
                    )
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message=error_msg,
                )

            try:
                data = response.json()
            except Exception:
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message="响应JSON解析失败",
                )

            if not isinstance(data, dict):
                return SearchResponse(
                    query=query,
                    results=[],
                    provider=self.name,
                    success=False,
                    error_message="响应格式无效",
                )

            raw = data.get("results", [])
            if not isinstance(raw, list):
                raw = []

            results = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                url_val = item.get("url")
                if not url_val:
                    continue
                raw_published_date = item.get("publishedDate")

                snippet = (item.get("content") or item.get("description") or "")[:500]
                published_date = None
                if raw_published_date:
                    try:
                        dt = datetime.fromisoformat(raw_published_date.replace("Z", "+00:00"))
                        published_date = dt.strftime("%Y-%m-%d")
                    except (ValueError, AttributeError):
                        published_date = raw_published_date

                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        snippet=snippet,
                        url=url_val,
                        source=self._extract_domain(url_val),
                        published_date=published_date,
                    )
                )
                if len(results) >= max_results:
                    break

            return SearchResponse(query=query, results=results, provider=self.name, success=True)

        except requests.exceptions.Timeout:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message="请求超时",
            )
        except requests.exceptions.RequestException as e:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=f"网络请求失败: {e}",
            )
        except Exception as e:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=f"未知错误: {e}",
            )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL as source label."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            return domain or "未知来源"
        except Exception:
            return "未知来源"

    def search(self, query: str, max_results: int = 5, days: int = 7) -> SearchResponse:
        """Execute SearXNG search with instance rotation and per-request failover."""
        start_time = time.time()
        if self._base_urls:
            candidates = self._rotate_candidates(
                self._base_urls,
                max_attempts=len(self._base_urls),
            )
            retry_enabled = True
            timeout = self.SELF_HOSTED_TIMEOUT_SECONDS
            empty_error = "SearXNG 未配置可用实例"
        elif self._use_public_instances:
            public_instances = self._get_public_instances()
            candidates = self._rotate_candidates(
                public_instances,
                max_attempts=min(len(public_instances), self.PUBLIC_INSTANCES_MAX_ATTEMPTS),
            )
            retry_enabled = False
            timeout = self.PUBLIC_INSTANCES_TIMEOUT_SECONDS
            empty_error = "未获取到可用的公共 SearXNG 实例"
        else:
            candidates = []
            retry_enabled = False
            timeout = self.PUBLIC_INSTANCES_TIMEOUT_SECONDS
            empty_error = "SearXNG 未配置可用实例"

        if not candidates:
            return SearchResponse(
                query=query,
                results=[],
                provider=self.name,
                success=False,
                error_message=empty_error,
                search_time=time.time() - start_time,
            )

        errors: List[str] = []
        for base_url in candidates:
            response = self._do_search(
                query,
                base_url,
                max_results,
                days=days,
                timeout=timeout,
                retry_enabled=retry_enabled,
            )
            response.search_time = time.time() - start_time
            if response.success:
                logger.info(
                    "[%s] 搜索 '%s' 成功，实例=%s，返回 %s 条结果，耗时 %.2fs",
                    self.name,
                    query,
                    base_url,
                    len(response.results),
                    response.search_time,
                )
                return response

            errors.append(f"{base_url}: {response.error_message or '未知错误'}")
            logger.warning("[%s] 实例 %s 搜索失败: %s", self.name, base_url, response.error_message)

        elapsed = time.time() - start_time
        return SearchResponse(
            query=query,
            results=[],
            provider=self.name,
            success=False,
            error_message="；".join(errors[:3]) if errors else empty_error,
            search_time=elapsed,
        )


class SearchService:
    """
    搜索服务
    
    功能：
    1. 管理多个搜索引擎
    2. 自动故障转移
    3. 结果聚合和格式化
    4. 数据源失败时的增强搜索（股价、走势等）
    5. 港股/美股自动使用英文搜索关键词
    """
    
    # 增强搜索关键词模板（A股 中文）
    ENHANCED_SEARCH_KEYWORDS = [
        "{name} 股票 今日 股价",
        "{name} {code} 最新 行情 走势",
        "{name} 股票 分析 走势图",
        "{name} K线 技术分析",
        "{name} {code} 涨跌 成交量",
    ]

    # 增强搜索关键词模板（港股/美股 英文）
    ENHANCED_SEARCH_KEYWORDS_EN = [
        "{name} stock price today",
        "{name} {code} latest quote trend",
        "{name} stock analysis chart",
        "{name} technical analysis",
        "{name} {code} performance volume",
    ]
    NEWS_OVERSAMPLE_FACTOR = 2
    NEWS_OVERSAMPLE_MAX = 10
    FUTURE_TOLERANCE_DAYS = 1
    _CHINESE_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
    _US_STOCK_RE = re.compile(r"^[A-Za-z]{1,5}(\.[A-Za-z])?$")

    def __init__(
        self,
        bocha_keys: Optional[List[str]] = None,
        tavily_keys: Optional[List[str]] = None,
        anspire_keys: Optional[List[str]] = None,
        brave_keys: Optional[List[str]] = None,
        serpapi_keys: Optional[List[str]] = None,
        minimax_keys: Optional[List[str]] = None,
        searxng_base_urls: Optional[List[str]] = None,
        searxng_public_instances_enabled: bool = True,
        news_max_age_days: int = 3,
        news_strategy_profile: str = "short",
    ):
        """
        初始化搜索服务

        Args:
            bocha_keys: 博查搜索 API Key 列表
            tavily_keys: Tavily API Key 列表
            anspire_keys: Anspire Search API Key 列表
            brave_keys: Brave Search API Key 列表
            serpapi_keys: SerpAPI Key 列表
            minimax_keys: MiniMax API Key 列表
            searxng_base_urls: SearXNG 实例地址列表（自建无配额兜底）
            searxng_public_instances_enabled: 未配置自建实例时，是否自动使用公共 SearXNG 实例
            news_max_age_days: 新闻最大时效（天）
            news_strategy_profile: 新闻窗口策略档位（ultra_short/short/medium/long）
        """
        self._providers: List[BaseSearchProvider] = []
        self.news_max_age_days = max(1, news_max_age_days)
        raw_profile = (news_strategy_profile or "short").strip().lower()
        self.news_strategy_profile = normalize_news_strategy_profile(news_strategy_profile)
        if raw_profile != self.news_strategy_profile:
            logger.warning(
                "NEWS_STRATEGY_PROFILE '%s' 无效，已回退为 'short'",
                news_strategy_profile,
            )
        self.news_window_days = resolve_news_window_days(
            news_max_age_days=self.news_max_age_days,
            news_strategy_profile=self.news_strategy_profile,
        )
        self.news_profile_days = NEWS_STRATEGY_WINDOWS.get(
            self.news_strategy_profile,
            NEWS_STRATEGY_WINDOWS["short"],
        )

        # 初始化搜索引擎（按优先级排序）
        # 1. Bocha 优先（中文搜索优化，AI摘要）
        if bocha_keys:
            self._providers.append(BochaSearchProvider(bocha_keys))
            logger.info(f"已配置 Bocha 搜索，共 {len(bocha_keys)} 个 API Key")

        # 2. Tavily（免费额度更多，每月 1000 次）
        if tavily_keys:
            self._providers.append(TavilySearchProvider(tavily_keys))
            logger.info(f"已配置 Tavily 搜索，共 {len(tavily_keys)} 个 API Key")

        # 3. Brave Search（隐私优先，全球覆盖）
        if brave_keys:
            self._providers.append(BraveSearchProvider(brave_keys))
            logger.info(f"已配置 Brave 搜索，共 {len(brave_keys)} 个 API Key")

        # 4. SerpAPI 作为备选（每月 100 次）
        if serpapi_keys:
            self._providers.append(SerpAPISearchProvider(serpapi_keys))
            logger.info(f"已配置 SerpAPI 搜索，共 {len(serpapi_keys)} 个 API Key")

        # 5. MiniMax（Coding Plan Web Search，结构化结果）
        if minimax_keys:
            self._providers.append(MiniMaxSearchProvider(minimax_keys))
            logger.info(f"已配置 MiniMax 搜索，共 {len(minimax_keys)} 个 API Key")

        # 6. SearXNG（自建实例优先；未配置时可自动发现公共实例）
        searxng_provider = SearXNGSearchProvider(
            searxng_base_urls,
            use_public_instances=bool(searxng_public_instances_enabled and not searxng_base_urls),
        )
        if searxng_provider.is_available:
            self._providers.append(searxng_provider)
            if searxng_base_urls:
                logger.info("已配置 SearXNG 搜索，共 %s 个自建实例", len(searxng_base_urls))
            else:
                logger.info("已启用 SearXNG 公共实例自动发现模式")

        # 7. Anspire Search（实时智能搜索优化）
        if anspire_keys:
            self._providers.insert(0, AnspireSearchProvider(anspire_keys))
            logger.info(f"已配置 Anspire Search 搜索，共 {len(anspire_keys)} 个 API Key")
            
        if not self._providers:
            logger.warning("未配置任何搜索能力，新闻搜索功能将不可用")

        # In-memory search result cache: {cache_key: (timestamp, SearchResponse)}
        self._cache: Dict[str, Tuple[float, 'SearchResponse']] = {}
        self._cache_lock = threading.RLock()
        self._cache_inflight: Dict[str, threading.Event] = {}
        # Default cache TTL in seconds (10 minutes)
        self._cache_ttl: int = 600
        logger.info(
            "新闻时效策略已启用: profile=%s, profile_days=%s, NEWS_MAX_AGE_DAYS=%s, effective_window=%s",
            self.news_strategy_profile,
            self.news_profile_days,
            self.news_max_age_days,
            self.news_window_days,
        )
    
    @staticmethod
    def _is_foreign_stock(stock_code: str) -> bool:
        """判断是否为港股或美股"""
        code = stock_code.strip()
        # 美股：1-5个大写字母，可能包含点（如 BRK.B）
        if SearchService._US_STOCK_RE.match(code):
            return True
        # 港股：带 hk 前缀或 5位纯数字
        lower = code.lower()
        if lower.startswith('hk'):
            return True
        if code.isdigit() and len(code) == 5:
            return True
        return False

    @classmethod
    def _contains_chinese_text(cls, value: Optional[str]) -> bool:
        """Return True when the input contains CJK characters."""
        return bool(value and cls._CHINESE_TEXT_RE.search(value))

    @classmethod
    def _is_us_stock(cls, stock_code: str) -> bool:
        """判断是否为美股/美股指数代码。"""
        code = (stock_code or "").strip().upper()
        return bool(cls._US_STOCK_RE.match(code) or is_us_index_code(code))

    @classmethod
    def _should_prefer_chinese_news(
        cls,
        stock_code: str,
        stock_name: str,
        focus_keywords: Optional[List[str]] = None,
    ) -> bool:
        """A 股或中文名称/关键词场景下优先中文资讯。

        Only returns True when there is a positive Chinese signal:
        Chinese characters in keywords/stock_name, or a 6-digit A-stock code.
        Avoids false positives for non-foreign but English contexts like
        ``stock_code="market", stock_name="US market"``.
        """
        if any(cls._contains_chinese_text(keyword) for keyword in (focus_keywords or [])):
            return True
        if cls._contains_chinese_text(stock_name):
            return True
        # Positive A-stock identification: 6-digit numeric codes (e.g. 600519)
        code = (stock_code or "").strip()
        return code.isdigit() and len(code) == 6

    @classmethod
    def _is_chinese_news_result(cls, item: SearchResult) -> bool:
        """Heuristic check for Chinese-language news items."""
        return cls._contains_chinese_text(" ".join(filter(None, [item.title, item.snippet, item.source])))

    @classmethod
    def _prioritize_news_language(
        cls,
        response: SearchResponse,
        *,
        prefer_chinese: bool,
    ) -> Tuple[SearchResponse, int]:
        """Reorder results by preferred language and return preferred-result count."""
        if not prefer_chinese or not response.success or not response.results:
            return response, 0

        chinese_results: List[SearchResult] = []
        other_results: List[SearchResult] = []
        for item in response.results:
            if cls._is_chinese_news_result(item):
                chinese_results.append(item)
            else:
                other_results.append(item)

        return (
            SearchResponse(
                query=response.query,
                results=chinese_results + other_results,
                provider=response.provider,
                success=response.success,
                error_message=response.error_message,
                search_time=response.search_time,
            ),
            len(chinese_results),
        )

    @classmethod
    def _is_better_preferred_news_response(
        cls,
        candidate: SearchResponse,
        *,
        candidate_preferred_count: int,
        best_response: Optional[SearchResponse],
        best_preferred_count: int,
    ) -> bool:
        """Prefer responses with more Chinese items, then more total items."""
        if best_response is None:
            return True
        if candidate_preferred_count != best_preferred_count:
            return candidate_preferred_count > best_preferred_count
        return len(candidate.results) > len(best_response.results)

    @classmethod
    def _brave_search_locale(
        cls,
        stock_code: str,
        *,
        prefer_chinese: bool,
    ) -> Dict[str, str]:
        """Resolve Brave locale hints without forcing US bias onto non-US symbols."""
        if prefer_chinese:
            return {"search_lang": "zh-hans", "country": "CN"}
        if cls._is_us_stock(stock_code):
            return {"search_lang": "en", "country": "US"}
        return {}

    # A-share ETF code prefixes (Shanghai 51/52/56/58, Shenzhen 15/16/18)
    _A_ETF_PREFIXES = ('51', '52', '56', '58', '15', '16', '18')
    _ETF_NAME_KEYWORDS = ('ETF', 'FUND', 'TRUST', 'INDEX', 'TRACKER', 'UNIT')  # US/HK ETF name hints

    @staticmethod
    def is_index_or_etf(stock_code: str, stock_name: str) -> bool:
        """
        Judge if symbol is index-tracking ETF or market index.
        For such symbols, analysis focuses on index movement only, not issuer company risks.
        """
        code = (stock_code or '').strip().split('.')[0]
        if not code:
            return False
        # A-share ETF
        if code.isdigit() and len(code) == 6 and code.startswith(SearchService._A_ETF_PREFIXES):
            return True
        # US index (SPX, DJI, IXIC etc.)
        if is_us_index_code(code):
            return True
        # US/HK ETF: foreign symbol + name contains fund-like keywords
        if SearchService._is_foreign_stock(code):
            name_upper = (stock_name or '').upper()
            return any(kw in name_upper for kw in SearchService._ETF_NAME_KEYWORDS)
        return False

    @property
    def is_available(self) -> bool:
        """检查是否有可用的搜索引擎"""
        return any(p.is_available for p in self._providers)

    def _cache_key(self, query: str, max_results: int, days: int) -> str:
        """Build a cache key from query parameters."""
        return f"{query}|{max_results}|{days}"

    def _get_cached_locked(self, key: str) -> Optional['SearchResponse']:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, response = entry
        if time.time() - ts > self._cache_ttl:
            self._cache.pop(key, None)
            return None
        logger.debug(f"Search cache hit: {key[:60]}...")
        return response

    def _get_cached(self, key: str) -> Optional['SearchResponse']:
        """Return cached SearchResponse if still valid, else None."""
        with self._cache_lock:
            return self._get_cached_locked(key)

    def _get_cached_or_reserve(
        self,
        key: str,
    ) -> Tuple[Optional['SearchResponse'], bool, Optional[threading.Event]]:
        with self._cache_lock:
            cached = self._get_cached_locked(key)
            if cached is not None:
                return cached, False, None

            event = self._cache_inflight.get(key)
            if event is None:
                event = threading.Event()
                self._cache_inflight[key] = event
                return None, True, event
            return None, False, event

    def _release_cache_fill(self, key: str, event: threading.Event) -> None:
        with self._cache_lock:
            current = self._cache_inflight.get(key)
            if current is event:
                self._cache_inflight.pop(key, None)
                event.set()

    def _wait_for_cached(self, key: str, event: threading.Event) -> Optional['SearchResponse']:
        event.wait(timeout=max(1.0, min(float(self._cache_ttl), 30.0)))
        return self._get_cached(key)

    def _put_cache(self, key: str, response: 'SearchResponse') -> None:
        """Store a successful SearchResponse in cache."""
        with self._cache_lock:
            # Hard cap: evict oldest entries when cache exceeds limit
            _MAX_CACHE_SIZE = 500
            if len(self._cache) >= _MAX_CACHE_SIZE:
                now = time.time()
                # First pass: remove expired entries
                expired = [k for k, (ts, _) in self._cache.items() if now - ts > self._cache_ttl]
                for k in expired:
                    self._cache.pop(k, None)
                # Second pass: if still over limit, evict oldest entries (FIFO)
                if len(self._cache) >= _MAX_CACHE_SIZE:
                    excess = len(self._cache) - _MAX_CACHE_SIZE + 1
                    oldest = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])[:excess]
                    for k in oldest:
                        self._cache.pop(k, None)
            self._cache[key] = (time.time(), response)

    def _effective_news_window_days(self) -> int:
        """Resolve effective news window from strategy profile and global max-age."""
        return resolve_news_window_days(
            news_max_age_days=self.news_max_age_days,
            news_strategy_profile=self.news_strategy_profile,
        )

    @classmethod
    def _provider_request_size(cls, max_results: int) -> int:
        """Apply light overfetch before time filtering to avoid sparse outputs."""
        target = max(1, int(max_results))
        return max(target, min(target * cls.NEWS_OVERSAMPLE_FACTOR, cls.NEWS_OVERSAMPLE_MAX))

    @staticmethod
    def _parse_relative_news_date(text: str, now: datetime) -> Optional[date]:
        """Parse common Chinese/English relative-time strings."""
        raw = (text or "").strip()
        if not raw:
            return None

        lower = raw.lower()
        if raw in {"今天", "今日", "刚刚"} or lower in {"today", "just now", "now"}:
            return now.date()
        if raw == "昨天" or lower == "yesterday":
            return (now - timedelta(days=1)).date()
        if raw == "前天":
            return (now - timedelta(days=2)).date()

        zh = re.match(r"^\s*(\d+)\s*(分钟|小时|天|周|个月|月|年)\s*前\s*$", raw)
        if zh:
            amount = int(zh.group(1))
            unit = zh.group(2)
            if unit == "分钟":
                return (now - timedelta(minutes=amount)).date()
            if unit == "小时":
                return (now - timedelta(hours=amount)).date()
            if unit == "天":
                return (now - timedelta(days=amount)).date()
            if unit == "周":
                return (now - timedelta(weeks=amount)).date()
            if unit in {"个月", "月"}:
                return (now - timedelta(days=amount * 30)).date()
            if unit == "年":
                return (now - timedelta(days=amount * 365)).date()

        en = re.match(
            r"^\s*(\d+)\s*(minute|minutes|min|mins|hour|hours|day|days|week|weeks|month|months|year|years)\s*ago\s*$",
            lower,
        )
        if en:
            amount = int(en.group(1))
            unit = en.group(2)
            if unit in {"minute", "minutes", "min", "mins"}:
                return (now - timedelta(minutes=amount)).date()
            if unit in {"hour", "hours"}:
                return (now - timedelta(hours=amount)).date()
            if unit in {"day", "days"}:
                return (now - timedelta(days=amount)).date()
            if unit in {"week", "weeks"}:
                return (now - timedelta(weeks=amount)).date()
            if unit in {"month", "months"}:
                return (now - timedelta(days=amount * 30)).date()
            if unit in {"year", "years"}:
                return (now - timedelta(days=amount * 365)).date()

        return None

    @classmethod
    def _normalize_news_publish_date(cls, value: Any) -> Optional[date]:
        """Normalize provider date value into a date object."""
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                local_tz = datetime.now().astimezone().tzinfo or timezone.utc
                return value.astimezone(local_tz).date()
            return value.date()
        if isinstance(value, date):
            return value

        text = str(value).strip()
        if not text:
            return None
        now = datetime.now()
        local_tz = now.astimezone().tzinfo or timezone.utc

        relative_date = cls._parse_relative_news_date(text, now)
        if relative_date:
            return relative_date

        # Unix timestamp fallback
        if text.isdigit() and len(text) in (10, 13):
            try:
                ts = int(text[:10]) if len(text) == 13 else int(text)
                # Provider timestamps are typically UTC epoch seconds.
                # Normalize to local date to keep window checks aligned with local "today".
                return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(local_tz).date()
            except (OSError, OverflowError, ValueError):
                pass

        iso_candidate = text.replace("Z", "+00:00")
        try:
            parsed_iso = datetime.fromisoformat(iso_candidate)
            if parsed_iso.tzinfo is not None:
                return parsed_iso.astimezone(local_tz).date()
            return parsed_iso.date()
        except ValueError:
            pass

        normalized = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.IGNORECASE)

        try:
            parsed_rfc = parsedate_to_datetime(normalized)
            if parsed_rfc:
                if parsed_rfc.tzinfo is not None:
                    return parsed_rfc.astimezone(local_tz).date()
                return parsed_rfc.date()
        except (TypeError, ValueError):
            pass

        zh_match = re.search(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?", text)
        if zh_match:
            try:
                return date(int(zh_match.group(1)), int(zh_match.group(2)), int(zh_match.group(3)))
            except ValueError:
                pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%Y.%m.%d %H:%M:%S",
            "%Y.%m.%d %H:%M",
            "%Y.%m.%d",
            "%Y%m%d",
            "%b %d, %Y",
            "%B %d, %Y",
            "%d %b %Y",
            "%d %B %Y",
            "%a, %d %b %Y %H:%M:%S %z",
        ):
            try:
                parsed_dt = datetime.strptime(normalized, fmt)
                if parsed_dt.tzinfo is not None:
                    return parsed_dt.astimezone(local_tz).date()
                return parsed_dt.date()
            except ValueError:
                continue

        return None

    def _filter_news_response(
        self,
        response: SearchResponse,
        *,
        search_days: int,
        max_results: int,
        log_scope: str,
    ) -> SearchResponse:
        """Hard-filter results by published_date recency and normalize date strings."""
        if not response.success or not response.results:
            return response

        today = datetime.now().date()
        earliest = today - timedelta(days=max(0, int(search_days) - 1))
        latest = today + timedelta(days=self.FUTURE_TOLERANCE_DAYS)

        filtered: List[SearchResult] = []
        dropped_unknown = 0
        dropped_old = 0
        dropped_future = 0

        for item in response.results:
            published = self._normalize_news_publish_date(item.published_date)
            if published is None:
                dropped_unknown += 1
                continue
            if published < earliest:
                dropped_old += 1
                continue
            if published > latest:
                dropped_future += 1
                continue

            filtered.append(
                SearchResult(
                    title=item.title,
                    snippet=item.snippet,
                    url=item.url,
                    source=item.source,
                    published_date=published.isoformat(),
                )
            )
            if len(filtered) >= max_results:
                break

        if dropped_unknown or dropped_old or dropped_future:
            logger.info(
                "[新闻过滤] %s: provider=%s, total=%s, kept=%s, drop_unknown=%s, drop_old=%s, drop_future=%s, window=[%s,%s]",
                log_scope,
                response.provider,
                len(response.results),
                len(filtered),
                dropped_unknown,
                dropped_old,
                dropped_future,
                earliest.isoformat(),
                latest.isoformat(),
            )

        return SearchResponse(
            query=response.query,
            results=filtered,
            provider=response.provider,
            success=response.success,
            error_message=response.error_message,
            search_time=response.search_time,
        )

    def _normalize_and_limit_response(
        self,
        response: SearchResponse,
        *,
        max_results: int,
    ) -> SearchResponse:
        """Normalize parseable dates without enforcing freshness filtering."""
        if not response.success or not response.results:
            return response

        normalized_results: List[SearchResult] = []
        for item in response.results[:max_results]:
            normalized_date = self._normalize_news_publish_date(item.published_date)
            normalized_results.append(
                SearchResult(
                    title=item.title,
                    snippet=item.snippet,
                    url=item.url,
                    source=item.source,
                    published_date=(
                        normalized_date.isoformat() if normalized_date is not None else item.published_date
                    ),
                )
            )

        return SearchResponse(
            query=response.query,
            results=normalized_results,
            provider=response.provider,
            success=response.success,
            error_message=response.error_message,
            search_time=response.search_time,
        )

    @staticmethod
    def _limit_search_response(
        response: SearchResponse,
        *,
        max_results: int,
    ) -> SearchResponse:
        """Trim response results without changing the rest of the metadata."""
        if not response.success or not response.results:
            return response

        limited_results = response.results[:max_results]
        if len(limited_results) == len(response.results):
            return response

        return SearchResponse(
            query=response.query,
            results=limited_results,
            provider=response.provider,
            success=response.success,
            error_message=response.error_message,
            search_time=response.search_time,
        )

    def search_stock_news(
        self,
        stock_code: str,
        stock_name: str,
        max_results: int = 5,
        focus_keywords: Optional[List[str]] = None
    ) -> SearchResponse:
        """
        搜索股票相关新闻
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            max_results: 最大返回结果数
            focus_keywords: 重点关注的关键词列表
            
        Returns:
            SearchResponse 对象
        """
        # 策略窗口优先：ultra_short/short/medium/long = 1/3/7/30 天，
        # 并统一受 NEWS_MAX_AGE_DAYS 上限约束。
        search_days = self._effective_news_window_days()
        provider_max_results = self._provider_request_size(max_results)
        prefer_chinese = self._should_prefer_chinese_news(
            stock_code,
            stock_name,
            focus_keywords=focus_keywords,
        )

        # 构建搜索查询（优化搜索效果）
        is_foreign = self._is_foreign_stock(stock_code)
        if focus_keywords:
            # 如果提供了关键词，直接使用关键词作为查询
            query = " ".join(focus_keywords)
        elif prefer_chinese:
            query = f"{stock_name} {stock_code} 股票 最新消息"
        elif is_foreign:
            # 港股/美股使用英文搜索关键词
            query = f"{stock_name} {stock_code} stock latest news"
        else:
            # 默认主查询：股票名称 + 核心关键词
            query = f"{stock_name} {stock_code} 股票 最新消息"

        logger.info(
            (
                "搜索股票新闻: %s(%s), query='%s', 时间范围: 近%s天 "
                "(profile=%s, NEWS_MAX_AGE_DAYS=%s, prefer_chinese=%s), 目标条数=%s, provider请求条数=%s"
            ),
            stock_name,
            stock_code,
            query,
            search_days,
            self.news_strategy_profile,
            self.news_max_age_days,
            prefer_chinese,
            max_results,
            provider_max_results,
        )

        cache_key = self._cache_key(
            f"{query}|news_pref={'zh' if prefer_chinese else 'default'}",
            max_results,
            search_days,
        )
        cached, cache_owner, cache_event = self._get_cached_or_reserve(cache_key)
        if cached is not None:
            logger.info(f"使用缓存搜索结果: {stock_name}({stock_code})")
            return cached

        if not cache_owner and cache_event is not None:
            cached = self._wait_for_cached(cache_key, cache_event)
            if cached is not None:
                logger.info(f"使用并发填充后的缓存搜索结果: {stock_name}({stock_code})")
                return cached
            cached, cache_owner, cache_event = self._get_cached_or_reserve(cache_key)
            if cached is not None:
                logger.info(f"使用等待后命中的缓存搜索结果: {stock_name}({stock_code})")
                return cached

        try:
            # 依次尝试各个搜索引擎（若过滤后为空，继续尝试下一引擎）
            had_provider_success = False
            fallback_response: Optional[SearchResponse] = None
            best_preferred_response: Optional[SearchResponse] = None
            best_preferred_count = 0
            for provider in self._providers:
                if not provider.is_available:
                    continue

                search_kwargs: Dict[str, Any] = {}
                if isinstance(provider, TavilySearchProvider):
                    search_kwargs["topic"] = "news"
                elif isinstance(provider, BraveSearchProvider):
                    search_kwargs.update(
                        self._brave_search_locale(
                            stock_code,
                            prefer_chinese=prefer_chinese,
                        )
                    )

                response = provider.search(query, provider_max_results, days=search_days, **search_kwargs)
                filtered_response = self._filter_news_response(
                    response,
                    search_days=search_days,
                    max_results=provider_max_results,
                    log_scope=f"{stock_code}:{provider.name}:stock_news",
                )
                had_provider_success = had_provider_success or bool(response.success)

                if filtered_response.success and filtered_response.results:
                    prioritized_response, preferred_count = self._prioritize_news_language(
                        filtered_response,
                        prefer_chinese=prefer_chinese,
                    )
                    limited_response = self._limit_search_response(
                        prioritized_response,
                        max_results=max_results,
                    )
                    visible_preferred_count = min(preferred_count, len(limited_response.results))

                    if not prefer_chinese:
                        logger.info(f"使用 {provider.name} 搜索成功")
                        self._put_cache(cache_key, limited_response)
                        return limited_response

                    if fallback_response is None:
                        fallback_response = limited_response

                    if visible_preferred_count > 0:
                        logger.info(
                            "%s 搜索成功，识别到 %s/%s 条中文新闻",
                            provider.name,
                            visible_preferred_count,
                            len(limited_response.results),
                        )
                        if self._is_better_preferred_news_response(
                            limited_response,
                            candidate_preferred_count=visible_preferred_count,
                            best_response=best_preferred_response,
                            best_preferred_count=best_preferred_count,
                        ):
                            best_preferred_response = limited_response
                            best_preferred_count = visible_preferred_count

                        if visible_preferred_count >= max_results:
                            self._put_cache(cache_key, limited_response)
                            return limited_response
                    else:
                        logger.info(
                            "%s 搜索成功但结果仍以英文为主，继续尝试下一引擎",
                            provider.name,
                        )
                else:
                    if response.success and not filtered_response.results:
                        logger.info(
                            "%s 搜索成功但过滤后无有效新闻，继续尝试下一引擎",
                            provider.name,
                        )
                    else:
                        logger.warning(
                            "%s 搜索失败: %s，尝试下一个引擎",
                            provider.name,
                            response.error_message,
                        )

            if prefer_chinese:
                best_to_return = best_preferred_response or fallback_response
                if best_to_return is not None:
                    self._put_cache(cache_key, best_to_return)
                    return best_to_return

            if had_provider_success:
                return SearchResponse(
                    query=query,
                    results=[],
                    provider="Filtered",
                    success=True,
                    error_message=None,
                )
            
            # 所有引擎都失败
            return SearchResponse(
                query=query,
                results=[],
                provider="None",
                success=False,
                error_message="所有搜索引擎都不可用或搜索失败"
            )
        finally:
            if cache_owner and cache_event is not None:
                self._release_cache_fill(cache_key, cache_event)
    
    def search_stock_events(
        self,
        stock_code: str,
        stock_name: str,
        event_types: Optional[List[str]] = None
    ) -> SearchResponse:
        """
        搜索股票特定事件（年报预告、减持等）
        
        专门针对交易决策相关的重要事件进行搜索
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            event_types: 事件类型列表
            
        Returns:
            SearchResponse 对象
        """
        if event_types is None:
            if self._is_foreign_stock(stock_code):
                event_types = ["earnings report", "insider selling", "quarterly results"]
            else:
                event_types = ["年报预告", "减持公告", "业绩快报"]
        
        # 构建针对性查询
        event_query = " OR ".join(event_types)
        query = f"{stock_name} ({event_query})"
        
        logger.info(f"搜索股票事件: {stock_name}({stock_code}) - {event_types}")
        
        # 依次尝试各个搜索引擎
        for provider in self._providers:
            if not provider.is_available:
                continue
            
            response = provider.search(query, max_results=5)
            
            if response.success:
                return response
        
        return SearchResponse(
            query=query,
            results=[],
            provider="None",
            success=False,
            error_message="事件搜索失败"
        )
    
    def search_comprehensive_intel(
        self,
        stock_code: str,
        stock_name: str,
        max_searches: int = 3
    ) -> Dict[str, SearchResponse]:
        """
        多维度情报搜索（同时使用多个引擎、多个维度）
        
        搜索维度：
        1. 最新消息 - 近期新闻动态
        2. 风险排查 - 减持、处罚、利空
        3. 业绩预期 - 年报预告、业绩快报
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            max_searches: 最大搜索次数
            
        Returns:
            {维度名称: SearchResponse} 字典
        """
        results = {}
        search_count = 0

        is_foreign = self._is_foreign_stock(stock_code)
        is_index_etf = self.is_index_or_etf(stock_code, stock_name)

        if is_foreign:
            search_dimensions = [
                {
                    'name': 'latest_news',
                    'query': f"{stock_name} {stock_code} latest news events",
                    'desc': '最新消息',
                    'tavily_topic': 'news',
                    'strict_freshness': True,
                },
                {
                    'name': 'market_analysis',
                    'query': f"{stock_name} analyst rating target price report",
                    'desc': '机构分析',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
                {
                    'name': 'risk_check',
                    'query': (
                        f"{stock_name} {stock_code} index performance outlook tracking error"
                        if is_index_etf else f"{stock_name} risk insider selling lawsuit litigation"
                    ),
                    'desc': '风险排查',
                    'tavily_topic': None if is_index_etf else 'news',
                    'strict_freshness': not is_index_etf,
                },
                {
                    'name': 'earnings',
                    'query': (
                        f"{stock_name} {stock_code} index performance composition outlook"
                        if is_index_etf else f"{stock_name} earnings revenue profit growth forecast"
                    ),
                    'desc': '业绩预期',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
                {
                    'name': 'industry',
                    'query': (
                        f"{stock_name} {stock_code} index sector allocation holdings"
                        if is_index_etf else f"{stock_name} industry competitors market share outlook"
                    ),
                    'desc': '行业分析',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
            ]
        else:
            search_dimensions = [
                {
                    'name': 'latest_news',
                    'query': f"{stock_name} {stock_code} 最新 新闻 重大 事件",
                    'desc': '最新消息',
                    'tavily_topic': 'news',
                    'strict_freshness': True,
                },
                {
                    'name': 'market_analysis',
                    'query': f"{stock_name} 研报 目标价 评级 深度分析",
                    'desc': '机构分析',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
                {
                    'name': 'risk_check',
                    'query': (
                        f"{stock_name} 指数走势 跟踪误差 净值 表现"
                        if is_index_etf else f"{stock_name} 减持 处罚 违规 诉讼 利空 风险"
                    ),
                    'desc': '风险排查',
                    'tavily_topic': None if is_index_etf else 'news',
                    'strict_freshness': not is_index_etf,
                },
                {
                    'name': 'announcements',
                    'query': (
                        f"{stock_name} {stock_code} 公告 指数调整 成分变化"
                        if is_index_etf else f"{stock_name} {stock_code} 公司公告 重要公告 上交所 深交所 cninfo"
                    ),
                    'desc': '公司公告',
                    'tavily_topic': 'news',
                    'strict_freshness': True,
                },
                {
                    'name': 'earnings',
                    'query': (
                        f"{stock_name} 指数成分 净值 跟踪表现"
                        if is_index_etf else f"{stock_name} 业绩预告 财报 营收 净利润 同比增长"
                    ),
                    'desc': '业绩预期',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
                {
                    'name': 'industry',
                    'query': (
                        f"{stock_name} 指数成分股 行业配置 权重"
                        if is_index_etf else f"{stock_name} 所在行业 竞争对手 市场份额 行业前景"
                    ),
                    'desc': '行业分析',
                    'tavily_topic': None,
                    'strict_freshness': False,
                },
            ]
        
        search_days = self._effective_news_window_days()
        target_per_dimension = 3
        provider_max_results = self._provider_request_size(target_per_dimension)

        logger.info(
            (
                "开始多维度情报搜索: %s(%s), 时间范围: 近%s天 "
                "(profile=%s, NEWS_MAX_AGE_DAYS=%s), 目标条数=%s, provider请求条数=%s"
            ),
            stock_name,
            stock_code,
            search_days,
            self.news_strategy_profile,
            self.news_max_age_days,
            target_per_dimension,
            provider_max_results,
        )
        
        # 轮流使用不同的搜索引擎
        provider_index = 0
        
        for dim in search_dimensions:
            if search_count >= max_searches:
                break
            
            # 选择搜索引擎（轮流使用）
            available_providers = [p for p in self._providers if p.is_available]
            if not available_providers:
                break
            
            provider = available_providers[provider_index % len(available_providers)]
            provider_index += 1
            
            logger.info(f"[情报搜索] {dim['desc']}: 使用 {provider.name}")

            if isinstance(provider, TavilySearchProvider) and dim.get('tavily_topic'):
                response = provider.search(
                    dim['query'],
                    max_results=provider_max_results,
                    days=search_days,
                    topic=dim['tavily_topic'],
                )
            else:
                response = provider.search(
                    dim['query'],
                    max_results=provider_max_results,
                    days=search_days,
                )
            if dim['strict_freshness']:
                filtered_response = self._filter_news_response(
                    response,
                    search_days=search_days,
                    max_results=target_per_dimension,
                    log_scope=f"{stock_code}:{provider.name}:{dim['name']}",
                )
            else:
                filtered_response = self._normalize_and_limit_response(
                    response,
                    max_results=target_per_dimension,
                )
            results[dim['name']] = filtered_response
            search_count += 1
            
            if response.success:
                logger.info(
                    "[情报搜索] %s: 原始=%s条, 过滤后=%s条",
                    dim['desc'],
                    len(response.results),
                    len(filtered_response.results),
                )
            else:
                logger.warning(f"[情报搜索] {dim['desc']}: 搜索失败 - {response.error_message}")
            
            # 短暂延迟避免请求过快
            time.sleep(0.5)
        
        return results
    
    def format_intel_report(self, intel_results: Dict[str, SearchResponse], stock_name: str) -> str:
        """
        格式化情报搜索结果为报告
        
        Args:
            intel_results: 多维度搜索结果
            stock_name: 股票名称
            
        Returns:
            格式化的情报报告文本
        """
        lines = [f"【{stock_name} 情报搜索结果】"]
        
        # 维度展示顺序
        display_order = ['latest_news', 'announcements', 'market_analysis', 'risk_check', 'earnings', 'industry']

        dim_labels = {
            'latest_news': '📰 最新消息',
            'announcements': '📋 公司公告',
            'market_analysis': '📈 机构分析',
            'risk_check': '⚠️ 风险排查',
            'earnings': '📊 业绩预期',
            'industry': '🏭 行业分析',
        }

        for dim_name in display_order:
            if dim_name not in intel_results:
                continue
                
            resp = intel_results[dim_name]
            
            # 获取维度描述
            dim_desc = dim_labels.get(dim_name, dim_name)
            
            lines.append(f"\n{dim_desc} (来源: {resp.provider}):")
            if resp.success and resp.results:
                # 增加显示条数
                for i, r in enumerate(resp.results[:4], 1):
                    date_str = f" [{r.published_date}]" if r.published_date else ""
                    lines.append(f"  {i}. {r.title}{date_str}")
                    # 如果摘要太短，可能信息量不足
                    snippet = r.snippet[:150] if len(r.snippet) > 20 else r.snippet
                    lines.append(f"     {snippet}...")
            else:
                lines.append("  未找到相关信息")
        
        return "\n".join(lines)
    
    def batch_search(
        self,
        stocks: List[Dict[str, str]],
        max_results_per_stock: int = 3,
        delay_between: float = 1.0
    ) -> Dict[str, SearchResponse]:
        """
        Batch search news for multiple stocks.
        
        Args:
            stocks: List of stocks
            max_results_per_stock: Max results per stock
            delay_between: Delay between searches (seconds)
            
        Returns:
            Dict of results
        """
        results = {}
        
        for i, stock in enumerate(stocks):
            if i > 0:
                time.sleep(delay_between)
            
            code = stock.get('code', '')
            name = stock.get('name', '')
            
            response = self.search_stock_news(code, name, max_results_per_stock)
            results[code] = response
        
        return results

    def search_stock_price_fallback(
        self,
        stock_code: str,
        stock_name: str,
        max_attempts: int = 3,
        max_results: int = 5
    ) -> SearchResponse:
        """
        Enhance search when data sources fail.
        
        When all data sources (efinance, akshare, tushare, baostock, etc.) fail to get
        stock data, use search engines to find stock trends and price info as supplemental data for AI analysis.
        
        Strategy:
        1. Search using multiple keyword templates
        2. Try all available search engines for each keyword
        3. Aggregate and deduplicate results
        
        Args:
            stock_code: Stock Code
            stock_name: Stock Name
            max_attempts: Max search attempts (using different keywords)
            max_results: Max results to return
            
        Returns:
            SearchResponse object with aggregated results
        """

        if not self.is_available:
            return SearchResponse(
                query=f"{stock_name} 股价走势",
                results=[],
                provider="None",
                success=False,
                error_message="未配置搜索能力"
            )
        
        logger.info(f"[增强搜索] 数据源失败，启动增强搜索: {stock_name}({stock_code})")
        
        all_results = []
        seen_urls = set()
        successful_providers = []
        
        # 使用多个关键词模板搜索
        is_foreign = self._is_foreign_stock(stock_code)
        keywords = self.ENHANCED_SEARCH_KEYWORDS_EN if is_foreign else self.ENHANCED_SEARCH_KEYWORDS
        for i, keyword_template in enumerate(keywords[:max_attempts]):
            query = keyword_template.format(name=stock_name, code=stock_code)
            
            logger.info(f"[增强搜索] 第 {i+1}/{max_attempts} 次搜索: {query}")
            
            # 依次尝试各个搜索引擎
            for provider in self._providers:
                if not provider.is_available:
                    continue
                
                try:
                    response = provider.search(query, max_results=3)
                    
                    if response.success and response.results:
                        # 去重并添加结果
                        for result in response.results:
                            if result.url not in seen_urls:
                                seen_urls.add(result.url)
                                all_results.append(result)
                                
                        if provider.name not in successful_providers:
                            successful_providers.append(provider.name)
                        
                        logger.info(f"[增强搜索] {provider.name} 返回 {len(response.results)} 条结果")
                        break  # 成功后跳到下一个关键词
                    else:
                        logger.debug(f"[增强搜索] {provider.name} 无结果或失败")
                        
                except Exception as e:
                    logger.warning(f"[增强搜索] {provider.name} 搜索异常: {e}")
                    continue
            
            # 短暂延迟避免请求过快
            if i < max_attempts - 1:
                time.sleep(0.5)
        
        # 汇总结果
        if all_results:
            # 截取前 max_results 条
            final_results = all_results[:max_results]
            provider_str = ", ".join(successful_providers) if successful_providers else "None"
            
            logger.info(f"[增强搜索] 完成，共获取 {len(final_results)} 条结果（来源: {provider_str}）")
            
            return SearchResponse(
                query=f"{stock_name}({stock_code}) 股价走势",
                results=final_results,
                provider=provider_str,
                success=True,
            )
        else:
            logger.warning(f"[增强搜索] 所有搜索均未返回结果")
            return SearchResponse(
                query=f"{stock_name}({stock_code}) 股价走势",
                results=[],
                provider="None",
                success=False,
                error_message="增强搜索未找到相关信息"
            )

    def search_stock_with_enhanced_fallback(
        self,
        stock_code: str,
        stock_name: str,
        include_news: bool = True,
        include_price: bool = False,
        max_results: int = 5
    ) -> Dict[str, SearchResponse]:
        """
        综合搜索接口（支持新闻和股价信息）
        
        当 include_price=True 时，会同时搜索新闻和股价信息。
        主要用于数据源完全失败时的兜底方案。
        
        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            include_news: 是否搜索新闻
            include_price: 是否搜索股价/走势信息
            max_results: 每类搜索的最大结果数
            
        Returns:
            {'news': SearchResponse, 'price': SearchResponse} 字典
        """
        results = {}
        
        if include_news:
            results['news'] = self.search_stock_news(
                stock_code, 
                stock_name, 
                max_results=max_results
            )
        
        if include_price:
            results['price'] = self.search_stock_price_fallback(
                stock_code,
                stock_name,
                max_attempts=3,
                max_results=max_results
            )
        
        return results

    def format_price_search_context(self, response: SearchResponse) -> str:
        """
        将股价搜索结果格式化为 AI 分析上下文
        
        Args:
            response: 搜索响应对象
            
        Returns:
            格式化的文本，可直接用于 AI 分析
        """
        if not response.success or not response.results:
            return "【股价走势搜索】未找到相关信息，请以其他渠道数据为准。"
        
        lines = [
            f"【股价走势搜索结果】（来源: {response.provider}）",
            "⚠️ 注意：以下信息来自网络搜索，仅供参考，可能存在延迟或不准确。",
            ""
        ]
        
        for i, result in enumerate(response.results, 1):
            date_str = f" [{result.published_date}]" if result.published_date else ""
            lines.append(f"{i}. 【{result.source}】{result.title}{date_str}")
            lines.append(f"   {result.snippet[:200]}...")
            lines.append("")
        
        return "\n".join(lines)


# === 便捷函数 ===
_search_service: Optional[SearchService] = None
_search_service_lock = threading.Lock()


def get_search_service() -> SearchService:
    """获取搜索服务单例"""
    global _search_service
    
    if _search_service is None:
        with _search_service_lock:
            if _search_service is None:
                from src.config import get_config
                config = get_config()
                
                _search_service = SearchService(
                    bocha_keys=config.bocha_api_keys,
                    tavily_keys=config.tavily_api_keys,
                    anspire_keys=config.anspire_api_keys,
                    brave_keys=config.brave_api_keys,
                    serpapi_keys=config.serpapi_keys,
                    minimax_keys=config.minimax_api_keys,
                    searxng_base_urls=config.searxng_base_urls,
                    searxng_public_instances_enabled=config.searxng_public_instances_enabled,
                    news_max_age_days=config.news_max_age_days,
                    news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
                )
    
    return _search_service


def reset_search_service() -> None:
    """重置搜索服务（用于测试）"""
    global _search_service
    with _search_service_lock:
        _search_service = None


if __name__ == "__main__":
    # 测试搜索服务
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
    )
    
    # 手动测试（需要配置 API Key）
    service = get_search_service()
    
    if service.is_available:
        print("=== 测试股票新闻搜索 ===")
        response = service.search_stock_news("300389", "艾比森")
        print(f"搜索状态: {'成功' if response.success else '失败'}")
        print(f"搜索引擎: {response.provider}")
        print(f"结果数量: {len(response.results)}")
        print(f"耗时: {response.search_time:.2f}s")
        print("\n" + response.to_context())
    else:
        print("未配置搜索能力，跳过测试")
