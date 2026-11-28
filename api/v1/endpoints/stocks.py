# -*- coding: utf-8 -*-
"""
===================================
股票数据接口
===================================

职责：
1. POST /api/v1/stocks/extract-from-image 从图片提取股票代码
2. POST /api/v1/stocks/parse-import 解析 CSV/Excel/剪贴板
3. GET /api/v1/stocks/{code}/quote 实时行情接口
4. GET /api/v1/stocks/{code}/history 历史行情接口
"""

import logging
from typing import Optional
import re

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends

from api.deps import get_system_config_service
from api.v1.errors import api_error

from api.v1.schemas.stocks import (
    ExtractFromImageResponse,
    ExtractItem,
    KLineData,
    StockHistoryResponse,
    StockProfileResponse,
    StockQuote,
)
from api.v1.schemas.history import WatchlistRequest, WatchlistResponse
from api.v1.schemas.common import ErrorResponse
from data_provider.us_index_mapping import normalize_us_hyphen_symbol
from src.services.image_stock_extractor import (
    ALLOWED_MIME,
    MAX_SIZE_BYTES,
    extract_stock_codes_from_image,
)
from src.services.import_parser import (
    MAX_FILE_BYTES,
    parse_import_from_bytes,
    parse_import_from_text,
)
from src.services.stock_service import StockService
from src.services.stock_profile_service import InvalidStockProfileCode, StockProfileService
from src.services.run_diagnostics import sanitize_diagnostic_text
from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from src.services.system_config_service import ConfigConflictError, SystemConfigService
from src.services.watchlist_service import canonicalize_watchlist_code, edit_watchlist, watchlist_match_key

logger = logging.getLogger(__name__)

router = APIRouter()

# 须在 /{stock_code} 路由之前定义
ALLOWED_MIME_STR = ", ".join(ALLOWED_MIME)


# Stock code validation patterns (aligned with frontend validateStockCode)
_STOCK_CODE_RE = re.compile(
    r"^(?:\d{6}"                              # A-share 6-digit
    r"|(?:SH|SZ|BJ)\d{6}"                     # exchange-prefixed A-share
    r"|\d{6}\.(?:SH|SZ|SS|BJ)"                # exchange-suffixed A-share
    r"|\d{1,5}\.HK"                           # HK suffix format
    r"|HK\d{1,5}"                             # HK prefix format
    r"|\d{5}"                                 # bare 5-digit HK code
    r"|\d{4,5}\.T"                            # Japan Yahoo suffix format
    r"|\d{6}\.(?:KS|KQ)"                     # Korea Yahoo suffix format
    r"|\d{4,6}\.(?:TW|TWO)"                  # Taiwan Yahoo suffix format
    r"|[A-Z]{1,5}(?:\.(?:US|[A-Z]))?"         # US ticker
    r")$",
    re.IGNORECASE,
)


def _validate_stock_code(code: str, *, allow_watchlist_aliases: bool = False) -> str:
    """Validate a stock code, accepting supported aliases in the watchlist."""

    stripped = code.strip()
    if not stripped:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "股票代码不能为空"},
        )
    if _STOCK_CODE_RE.fullmatch(stripped):
        return stripped
    us_symbol = normalize_us_hyphen_symbol(stripped)
    if us_symbol:
        return us_symbol
    if allow_watchlist_aliases:
        if parse_analysis_target(stripped).asset_type == ParseStatus.INDEX:
            return stripped
        normalized = canonicalize_watchlist_code(stripped)
        if _STOCK_CODE_RE.fullmatch(normalized):
            return normalized
    raise HTTPException(
        status_code=400,
        detail={
            "error": "invalid_stock_code",
            "message": f"'{stripped}' 不是合法的股票代码格式",
        },
    )


@router.post(
    "/extract-from-image",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "提取的股票代码"},
        400: {"description": "图片无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从图片提取股票代码",
    description="上传截图/图片，通过 Vision LLM 提取股票代码。支持 JPEG、PNG、WebP、GIF，最大 5MB。",
)
def extract_from_image(
    file: Optional[UploadFile] = File(None, description="图片文件（表单字段名 file）"),
    include_raw: bool = Query(False, description="是否在结果中包含原始 LLM 响应"),
) -> ExtractFromImageResponse:
    """
    从上传的图片中提取股票代码（使用 Vision LLM）。

    表单字段请使用 file 上传图片。优先级：Gemini / Anthropic / OpenAI（首个可用）。
    """
    if not file or not file.filename:
        raise HTTPException(
            status_code=400,
            detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file 上传图片"},
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_type",
                "message": f"不支持的类型: {content_type}。允许: {ALLOWED_MIME_STR}",
            },
        )

    try:
        # 先读取限定大小，再检查是否还有剩余（语义清晰：超出则拒绝）
        data = file.file.read(MAX_SIZE_BYTES)
        if file.file.read(1):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"图片超过 {MAX_SIZE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to read uploaded file: {e}")
        raise HTTPException(
            status_code=400,
            detail={"error": "read_failed", "message": "读取上传文件失败"},
        )

    try:
        items, raw_text = extract_stock_codes_from_image(data, content_type)
        extract_items = [
            ExtractItem(code=code, name=name, confidence=conf) for code, name, conf in items
        ]
        codes = [i.code for i in extract_items]
        return ExtractFromImageResponse(
            codes=codes,
            items=extract_items,
            raw_text=raw_text if include_raw else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "extract_failed", "message": str(e)})
    except Exception as e:
        logger.error(f"Image extraction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "图片提取失败"},
        )


@router.post(
    "/parse-import",
    response_model=ExtractFromImageResponse,
    responses={
        200: {"description": "解析结果"},
        400: {"description": "未提供数据或解析失败", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="解析 CSV/Excel/剪贴板",
    description="上传 CSV/Excel 文件或粘贴文本，自动解析股票代码。文件上限 2MB，文本上限 100KB。",
)
async def parse_import(request: Request) -> ExtractFromImageResponse:
    """
    解析 CSV/Excel 文件或剪贴板文本。

    - multipart/form-data + file: 上传文件
    - application/json + {"text": "..."}: 粘贴文本
    - 优先使用 file，若同时提供则忽略 text
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as e:
            logger.warning("[parse_import] JSON parse failed: %s", e)
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_json", "message": f"JSON 解析失败: {e}"},
            )
        text = body.get("text") if isinstance(body, dict) else None
        if not text or not isinstance(text, str):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供 text，请使用 {\"text\": \"...\"}"},
            )
        try:
            items = parse_import_from_text(text)
        except ValueError as e:
            text_bytes = len(text.encode("utf-8"))
            logger.warning(
                "[parse_import] parse_import_from_text failed: text_bytes=%d, error=%s",
                text_bytes,
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    elif "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(
                status_code=400,
                detail={"error": "bad_request", "message": "未提供文件，请使用表单字段 file"},
            )
        file_size = getattr(file, "size", None)
        if isinstance(file_size, int) and file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "file_too_large",
                    "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                },
            )
        try:
            data = file.file.read(MAX_FILE_BYTES)
            if file.file.read(1):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "file_too_large",
                        "message": f"文件超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 限制",
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            filename = getattr(file, "filename", None) or ""
            size = getattr(file, "size", None)
            logger.warning(
                "[parse_import] file read failed: filename=%r, size=%s, error=%s",
                filename,
                size,
                e,
            )
            raise HTTPException(
                status_code=400,
                detail={"error": "read_failed", "message": "读取文件失败"},
            )
        filename = getattr(file, "filename", None) or ""
        try:
            items = parse_import_from_bytes(data, filename=filename)
        except ValueError as e:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            logger.warning(
                "[parse_import] parse_import_from_bytes failed: filename=%r, ext=%r, bytes=%d, error=%s",
                filename,
                ext,
                len(data),
                e,
            )
            raise HTTPException(status_code=400, detail={"error": "parse_failed", "message": str(e)})
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "bad_request",
                "message": "请使用 multipart/form-data 上传文件，或 application/json 提交 {\"text\": \"...\"}",
            },
        )

    extract_items = [
        ExtractItem(code=code, name=name, confidence=conf)
        for code, name, conf in items
    ]
    codes = list(dict.fromkeys(i.code for i in extract_items if i.code))
    return ExtractFromImageResponse(codes=codes, items=extract_items, raw_text=None)


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "当前自选队列"},
        409: {"description": "配置版本冲突", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取自选队列",
    description="返回当前 STOCK_LIST 配置中的所有股票代码。",
)
def get_watchlist(
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        codes, _ = service.get_watchlist_snapshot()
        return WatchlistResponse(stock_codes=codes, message=f"当前自选 {len(codes)} 只股票")
    except ConfigConflictError as exc:
        raise api_error(409, "config_conflict", str(exc)) from exc
    except Exception as e:
        logger.error(f"Failed to get watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"获取自选队列失败: {str(e)}"},
        )


@router.post(
    "/watchlist/add",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已加入自选"},
        400: {"description": "参数错误", "model": ErrorResponse},
        409: {"description": "配置版本冲突", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="加入自选队列",
    description="将指定股票代码加入 STOCK_LIST。",
)
def add_to_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        code = _validate_stock_code(request.stock_code, allow_watchlist_aliases=True)
        requested_key = watchlist_match_key(code)

        def append_code(codes: list[str]) -> None:
            if not any(watchlist_match_key(existing) == requested_key for existing in codes):
                codes.append(code)

        codes, _ = edit_watchlist(service, append_code)
        return WatchlistResponse(stock_codes=codes, message=f"已加入 {code}")
    except HTTPException:
        raise
    except ConfigConflictError as exc:
        raise api_error(409, "config_conflict", str(exc)) from exc
    except Exception as e:
        logger.error(f"Failed to add to watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"加入自选失败: {str(e)}"},
        )


@router.post(
    "/watchlist/remove",
    response_model=WatchlistResponse,
    responses={
        200: {"description": "已从自选删除"},
        400: {"description": "参数错误", "model": ErrorResponse},
        409: {"description": "配置版本冲突", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="从自选队列删除",
    description="从 STOCK_LIST 中移除指定股票代码。",
)
def remove_from_watchlist(
    request: WatchlistRequest,
    service: SystemConfigService = Depends(get_system_config_service),
) -> WatchlistResponse:
    try:
        code = _validate_stock_code(request.stock_code, allow_watchlist_aliases=True)
        requested_key = watchlist_match_key(code)

        def remove_code(codes: list[str]) -> None:
            for index, existing in enumerate(codes):
                if watchlist_match_key(existing) == requested_key:
                    codes.pop(index)
                    break

        codes, _ = edit_watchlist(service, remove_code)
        return WatchlistResponse(stock_codes=codes, message=f"已移除 {code}")
    except HTTPException:
        raise
    except ConfigConflictError as exc:
        raise api_error(409, "config_conflict", str(exc)) from exc
    except Exception as e:
        logger.error(f"Failed to remove from watchlist: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"从自选删除失败: {str(e)}"},
        )


@router.get(
    "/{stock_code}/profile",
    response_model=StockProfileResponse,
    responses={
        400: {"description": "股票代码无效", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取个股研究聚合档案",
    description="按独立质量状态聚合行情、历史、研究产物、资讯、持仓关系和监控规则。",
)
def get_stock_profile(
    stock_code: str,
    history_days: int = Query(60, ge=1, le=365, description="日线历史天数"),
) -> StockProfileResponse:
    """Return partial profile data without failing on one optional block."""
    _validate_stock_code(stock_code)
    try:
        return StockProfileResponse(
            **StockProfileService().get_profile(stock_code, history_days=history_days)
        )
    except InvalidStockProfileCode:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_stock_code", "message": "股票代码与交易所不匹配"},
        )
    except Exception as exc:
        sanitized = sanitize_diagnostic_text(str(exc), max_length=300) or "internal profile error"
        logger.error("Failed to get stock profile: %s", sanitized)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "获取个股研究聚合档案失败"},
        )


@router.get(
    "/{stock_code}/quote",
    response_model=StockQuote,
    responses={
        200: {"description": "行情数据"},
        404: {"description": "股票不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票实时行情",
    description="获取指定股票的最新行情数据"
)
def get_stock_quote(stock_code: str) -> StockQuote:
    """
    获取股票实时行情
    
    获取指定股票的最新行情数据
    
    Args:
        stock_code: 股票代码（如 600519、00700、AAPL）
        
    Returns:
        StockQuote: 实时行情数据
        
    Raises:
        HTTPException: 404 - 股票不存在
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_realtime_quote(stock_code)
        
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": f"未找到股票 {stock_code} 的行情数据"
                }
            )
        
        return StockQuote(
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            current_price=result.get("current_price", 0.0),
            change=result.get("change"),
            change_percent=result.get("change_percent"),
            open=result.get("open"),
            high=result.get("high"),
            low=result.get("low"),
            prev_close=result.get("prev_close"),
            volume=result.get("volume"),
            amount=result.get("amount"),
            update_time=result.get("update_time")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get realtime quote: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取实时行情失败: {str(e)}"
            }
        )


@router.get(
    "/{stock_code}/history",
    response_model=StockHistoryResponse,
    responses={
        200: {"description": "历史行情数据"},
        422: {"description": "不支持的周期参数", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取股票历史行情",
    description="获取指定股票的历史 K 线数据"
)
def get_stock_history(
    stock_code: str,
    period: str = Query("daily", description="K 线周期", pattern="^(daily|weekly|monthly)$"),
    days: int = Query(30, ge=1, le=365, description="获取天数")
) -> StockHistoryResponse:
    """
    获取股票历史行情
    
    获取指定股票的历史 K 线数据
    
    Args:
        stock_code: 股票代码
        period: K 线周期 (daily/weekly/monthly)
        days: 获取天数
        
    Returns:
        StockHistoryResponse: 历史行情数据
    """
    try:
        service = StockService()
        
        # 使用 def 而非 async def，FastAPI 自动在线程池中执行
        result = service.get_history_data(
            stock_code=stock_code,
            period=period,
            days=days
        )
        
        # 转换为响应模型
        data = [
            KLineData(
                date=item.get("date"),
                open=item.get("open"),
                high=item.get("high"),
                low=item.get("low"),
                close=item.get("close"),
                volume=item.get("volume"),
                amount=item.get("amount"),
                change_percent=item.get("change_percent")
            )
            for item in result.get("data", [])
        ]
        
        return StockHistoryResponse(
            stock_code=stock_code,
            stock_name=result.get("stock_name"),
            period=period,
            data=data,
            price_adjustment=result.get("price_adjustment"),
            ohlc_synthesized=result.get("ohlc_synthesized"),
        )
    
    except ValueError as e:
        # period 参数不支持的错误（如 weekly/monthly）
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_period",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to get historical data: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"获取历史行情失败: {str(e)}"
            }
        )
