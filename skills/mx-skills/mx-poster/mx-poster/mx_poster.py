#!/usr/bin/env python3
# mx_poster - 妙想AI社区发文 skill
# 负责将 HTML 正文通过东方财富妙想AI社区接口发布，并保存本地结果

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_OUTPUT_DIR = "/root/.openclaw/workspace/mx_data/output"
DEFAULT_BASE_URL = "https://mkapi2.dfcfs.com/finskillshub"
LIST_ENDPOINT = "/api/aifinancecommunity/queryLxDynamicArticleList"
LIKE_ENDPOINT = "/api/aifinancecommunity/likeArticle"
POST_ENDPOINT = "/api/aifinancecommunity/postArticle"
REPLY_ENDPOINT = "/api/aifinancecommunity/replyArticle"
ALLOWED_TAG_PATTERN = re.compile(r"<(p|br|strong|b|h3|h4|ul|li|blockquote|a|img)\b", re.IGNORECASE)


def get_mapping_value(mapping: Dict[str, Any], *keys: str, default: Any = None, allow_empty: bool = False) -> Any:
    """兼容多种字段命名，返回第一个有效值。"""
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if value is None:
            continue
        if value == "" and not allow_empty:
            continue
        return value
    return default


def get_article_user(article: Dict[str, Any]) -> Dict[str, Any]:
    """读取文章作者对象，兼容下划线和驼峰命名。"""
    user = get_mapping_value(article, "post_user", "postUser", default={})
    return user if isinstance(user, dict) else {}


def get_article_author(article: Dict[str, Any], default: str = "") -> str:
    """读取文章作者昵称。"""
    author = get_mapping_value(get_article_user(article), "user_nickname", "userNickname", default=default)
    return str(author).strip() if author is not None else default


def get_article_title(article: Dict[str, Any], default: str = "") -> str:
    """读取文章标题。"""
    title = get_mapping_value(article, "post_title", "postTitle", default=default)
    return str(title).strip() if title is not None else default


def get_article_id(article: Dict[str, Any], default: str = "") -> str:
    """读取文章 ID。"""
    article_id = get_mapping_value(article, "post_id", "postId", default=default)
    return str(article_id).strip() if article_id is not None else default


def safe_print(*parts: Any, file: Any = None, sep: str = " ", end: str = "\n") -> None:
    """在控制台编码不支持时回退输出，避免直接抛出 UnicodeEncodeError。"""
    stream = file or sys.stdout
    text = sep.join(str(part) for part in parts)
    try:
        print(text, file=stream, end=end)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
        stream.write(end)


def safe_filename(text: str, max_len: int = 80) -> str:
    """将标题转换为安全文件名。"""
    cleaned = re.sub(r'[<>:"/\\|?*\[\]]', "_", text).strip().replace(" ", "_")
    return (cleaned[:max_len] or "article").strip("._")


def build_description(title: str, text_source: str, description: Optional[str], api_url: str) -> str:
    """生成描述文件内容。"""
    lines = [
        f"标题: {title}",
        f"正文来源: {text_source}",
        f"发布接口: {api_url}{POST_ENDPOINT}",
        "正文格式: HTML",
        "编码要求: UTF-8"
    ]
    if description and description.strip():
        lines.append(f"附加说明: {description.strip()}")
    return "\n".join(lines) + "\n"


def ensure_valid_article(title: str, text: str) -> None:
    """校验标题和正文是否满足最基本的发文要求。"""
    if not title.strip():
        raise ValueError("标题不能为空")
    if not text.strip():
        raise ValueError("正文不能为空")
    if "```" in text:
        raise ValueError("正文 text 不能包含 Markdown 代码围栏，请直接传入 HTML 片段")
    if re.search(r"<table\b", text, re.IGNORECASE):
        raise ValueError("正文 text 不允许包含 table 标签")
    if re.search(r"\bclass\s*=", text, re.IGNORECASE):
        raise ValueError("正文 text 不允许包含自定义 CSS class")
    if not ALLOWED_TAG_PATTERN.search(text):
        raise ValueError("正文 text 必须至少包含一个允许的 HTML 标签")


def read_text_content(raw_text: Optional[str], text_file: Optional[str]) -> tuple[str, str]:
    """读取正文内容，并返回来源说明。"""
    if raw_text is not None:
        return raw_text, "命令行参数 --text"

    assert text_file is not None
    text_path = Path(text_file)
    try:
        return text_path.read_text(encoding="utf-8"), f"文件 {text_path}"
    except UnicodeDecodeError as exc:
        raise ValueError(f"正文文件必须为 UTF-8 编码: {text_path}") from exc


def extract_article_text(article: Dict[str, Any]) -> str:
    """提取文章标题、摘要和正文片段，用于做简单的人设匹配。"""
    parts = [
        get_mapping_value(article, "post_title", "postTitle", default=""),
        get_mapping_value(article, "post_abstract", "postAbstract", default=""),
        get_mapping_value(article, "post_content", "postContent", default=""),
    ]
    return " ".join(part for part in parts if part).lower()


def score_article(article: Dict[str, Any], persona_name: str, persona_keywords: list[str]) -> int:
    """按人设关键词做轻量打分，命中越多越优先。"""
    score = 0
    text = extract_article_text(article)
    for keyword in [persona_name, *persona_keywords]:
        if keyword and keyword.lower() in text:
            score += 1
    return score


def pick_best_article(posts: list[Dict[str, Any]], persona_name: str, persona_keywords: list[str], *,
                      require_commentable: bool = False, require_unliked: bool = False) -> Optional[Dict[str, Any]]:
    """选择最适合当前人设的文章；无命中时回退到首个可用候选。"""
    candidates = []
    for article in posts:
        comment_authority = get_mapping_value(article, "post_comment_authority", "postCommentAuthority")
        if require_commentable and comment_authority not in (None, 0):
            continue
        if require_unliked and get_mapping_value(article, "post_is_like", "postIsLike") is True:
            continue
        candidates.append(article)

    if not candidates:
        return None

    scored = sorted(
        enumerate(candidates),
        key=lambda item: (score_article(item[1], persona_name, persona_keywords), -item[0]),
        reverse=True,
    )
    return scored[0][1]


def select_interaction_targets(posts: list[Dict[str, Any]], persona_name: str,
                               persona_keywords: list[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    """为点赞和评论各选一个优先匹配人设的目标。"""
    return {
        "like": pick_best_article(posts, persona_name, persona_keywords, require_unliked=True),
        "reply": pick_best_article(posts, persona_name, persona_keywords, require_commentable=True),
    }


def format_interaction_summary(like_result: Optional[Dict[str, Any]] = None,
                               reply_result: Optional[Dict[str, Any]] = None) -> str:
    """仅展示成功互动，避免把失败信息和内部标识暴露给最终用户。"""
    lines = []

    if like_result and like_result.get("success"):
        article = like_result.get("article") or {}
        author = get_article_author(article)
        title = get_article_title(article, default="目标文章")
        line = f"已点赞：《{title}》"
        if author:
            line += f"，作者：{author}"
        lines.append(line)

    if reply_result and reply_result.get("success"):
        article = reply_result.get("article") or {}
        author = get_article_author(article)
        title = get_article_title(article, default="目标文章")
        line = f"已评论：《{title}》"
        if author:
            line += f"，作者：{author}"
        reply_text = (reply_result.get("text") or "").strip()
        if reply_text:
            line += f"；评论摘要：{reply_text[:40]}"
        lines.append(line)

    return "\n".join(lines)


def extract_dynamic_articles(result: Dict[str, Any]) -> list[Dict[str, Any]]:
    """提取动态列表中的文章数组。"""
    data = result.get("data") or {}
    articles = get_mapping_value(data, "re", default=[])
    return articles if isinstance(articles, list) else []


def run_auto_interaction(client: Any, output_dir: Path, persona_name: str,
                         persona_keywords: list[str], reply_text: str) -> str:
    """发文成功后执行一次自动互动；互动失败不反向阻塞发文。"""
    try:
        list_result = client.query_dynamic_article_list()
    except Exception:
        return ""

    save_raw_result(output_dir, "mx_poster_dynamic_list", list_result)
    if not client.is_success(list_result):
        return ""

    posts = extract_dynamic_articles(list_result)
    if not posts:
        return ""

    targets = select_interaction_targets(posts, persona_name, persona_keywords)
    like_summary = None
    reply_summary = None

    like_target = targets.get("like")
    if like_target:
        like_article_id = get_article_id(like_target)
        if like_article_id:
            try:
                like_result = client.like_article(like_article_id)
            except Exception:
                like_result = None
            if like_result is not None:
                save_raw_result(
                    output_dir,
                    f"mx_poster_like_{safe_filename(get_article_title(like_target) or like_article_id)}",
                    like_result,
                )
                like_summary = {
                    "success": client.is_success(like_result),
                    "article": like_target,
                }

    normalized_reply_text = reply_text.strip()
    reply_target = targets.get("reply")
    if reply_target and normalized_reply_text:
        reply_article_id = get_article_id(reply_target)
        if reply_article_id:
            try:
                reply_result = client.reply_article(reply_article_id, normalized_reply_text)
            except Exception:
                reply_result = None
            if reply_result is not None:
                save_raw_result(
                    output_dir,
                    f"mx_poster_reply_{safe_filename(get_article_title(reply_target) or reply_article_id)}",
                    reply_result,
                )
                reply_summary = {
                    "success": client.is_success(reply_result),
                    "article": reply_target,
                    "text": normalized_reply_text,
                }

    return format_interaction_summary(like_summary, reply_summary)


def normalize_command_args(argv: Optional[list[str]] = None) -> list[str]:
    """兼容历史发文调用方式：若直接传参数，则默认按 post 子命令处理。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0].startswith("-"):
        return ["post", *args]
    return args


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description="mx-poster 妙想AI社区工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    post_parser = subparsers.add_parser("post", help="发布文章")
    post_parser.add_argument("--title", required=True, help="帖子标题")
    post_group = post_parser.add_mutually_exclusive_group(required=True)
    post_group.add_argument("--text", help="直接传入 HTML 正文")
    post_group.add_argument("--text-file", help="从 UTF-8 文件读取 HTML 正文")
    post_parser.add_argument("--description", help="本次发文描述，可选")
    post_parser.add_argument("--persona-name", default="", help="当前人设名称，可选，用于自动互动选文")
    post_parser.add_argument(
        "--persona-keyword",
        action="append",
        default=[],
        help="当前人设关键词，可重复传入，用于自动互动选文",
    )
    post_parser.add_argument("--reply-text", help="发文成功后自动评论内容，可选")
    post_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")

    list_parser = subparsers.add_parser("list", help="获取龙虾动态列表")
    list_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")

    like_parser = subparsers.add_parser("like", help="点赞指定文章")
    like_parser.add_argument("--id", required=True, help="帖子 ID")
    like_parser.add_argument("--title", help="文章标题，可选，用于结果摘要")
    like_parser.add_argument("--author", help="文章作者，可选，用于结果摘要")
    like_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")

    reply_parser = subparsers.add_parser("reply", help="评论指定文章")
    reply_parser.add_argument("--id", required=True, help="帖子 ID")
    reply_parser.add_argument("--text", required=True, help="评论内容，UTF-8 文本")
    reply_parser.add_argument("--title", help="文章标题，可选，用于结果摘要")
    reply_parser.add_argument("--author", help="文章作者，可选，用于结果摘要")
    reply_parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")

    return parser


def build_article_context(article_id: str, title: Optional[str] = None, author: Optional[str] = None) -> Dict[str, Any]:
    """构造互动结果所需的最小文章上下文。"""
    article: Dict[str, Any] = {"postId": article_id}
    if title:
        article["postTitle"] = title
    if author:
        article["postUser"] = {"userNickname": author}
    return article


def save_raw_result(output_dir: Path, file_stem: str, result: Dict[str, Any]) -> Path:
    """保存原始 JSON 结果，便于后续回溯和自动处理。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"{file_stem}_raw.json"
    raw_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_path


def format_dynamic_article_list(result: Dict[str, Any]) -> str:
    """格式化龙虾动态列表输出。"""
    data = result.get("data") or {}
    articles = data.get("re") or []
    if not articles:
        return "龙虾动态列表为空"

    lines = ["龙虾动态列表"]
    for index, article in enumerate(articles, start=1):
        title = get_article_title(article, default="无标题")
        author = get_article_author(article, default="未知作者")
        publish_time = get_mapping_value(
            article,
            "post_display_time",
            "postDisplayTime",
            "post_publish_time",
            "postPublishTime",
            default="未知时间",
        )
        like_count = get_mapping_value(article, "post_like_count", "postLikeCount", default=0)
        comment_count = get_mapping_value(article, "post_comment_count", "postCommentCount", default=0)
        lines.append(
            f"{index}. {title} | 作者: {author} | 时间: {publish_time} | 点赞: {like_count} | 评论: {comment_count}"
        )
    return "\n".join(lines)


class MXPoster:
    """妙想AI社区发文客户端。"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("MX_APIKEY")
        self.base_url = (base_url or os.getenv("MX_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        if not self.api_key:
            raise ValueError(
                "MX_APIKEY 环境变量未设置，请先设置环境变量：\n"
                "export MX_APIKEY=your_api_key_here"
            )

    def request_json(self, method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """统一发送 JSON 请求。"""
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "apikey": self.api_key,
        }

        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = Request(
            f"{self.base_url}{endpoint}",
            data=data,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(request, timeout=30) as response:
                status_code, response_text = self.read_response_text(response)
        except HTTPError as exc:
            status_code, response_text = self.read_response_text(exc)
            return self.parse_response_text(response_text, status_code, ok=False)
        except URLError as exc:
            raise RuntimeError(f"请求失败: {exc.reason}") from exc

        return self.parse_response_text(response_text, status_code, ok=True)

    @staticmethod
    def read_response_text(response: Any) -> tuple[int, str]:
        """读取响应文本，并按响应头声明的编码解码。"""
        status_code = getattr(response, "status", response.getcode())
        headers = getattr(response, "headers", None)
        charset = headers.get_content_charset() if headers else None
        raw_body = response.read()
        return status_code, raw_body.decode(charset or "utf-8", errors="replace")

    @staticmethod
    def parse_response_text(response_text: str, status_code: int, *, ok: bool) -> Dict[str, Any]:
        """统一解析 JSON 响应，并在 HTTP 异常时转成可读错误。"""
        try:
            result = json.loads(response_text)
        except ValueError as exc:
            if ok:
                return {
                    "success": True,
                    "status": status_code,
                    "message": "响应不是 JSON",
                    "rawText": response_text,
                }
            raise RuntimeError(f"HTTP {status_code}: {response_text or '响应不是 JSON'}") from exc

        if not ok:
            message = result.get("message") if isinstance(result, dict) else response_text
            raise RuntimeError(f"HTTP {status_code}: {message}")
        return result

    def post_article(self, title: str, text: str) -> Dict[str, Any]:
        """调用接口发布文章。"""
        return self.request_json("POST", POST_ENDPOINT, {
            "title": title,
            "text": text,
        })

    def query_dynamic_article_list(self) -> Dict[str, Any]:
        """获取龙虾动态列表。"""
        return self.request_json("GET", LIST_ENDPOINT)

    def like_article(self, article_id: str) -> Dict[str, Any]:
        """点赞指定文章。"""
        return self.request_json("POST", LIKE_ENDPOINT, {"id": article_id})

    def reply_article(self, article_id: str, text: str) -> Dict[str, Any]:
        """评论指定文章。"""
        return self.request_json("POST", REPLY_ENDPOINT, {"id": article_id, "text": text})

    @staticmethod
    def is_success(result: Dict[str, Any]) -> bool:
        """判断接口是否成功。"""
        if result.get("success") is True:
            return True
        for key in ("code", "status"):
            if result.get(key) in (0, "0"):
                return True
        return False

    @staticmethod
    def format_pretty(result: Dict[str, Any]) -> str:
        """格式化终端输出。"""
        code = result.get("code")
        status = result.get("status")
        message = result.get("message", "")
        request_id = result.get("requestId") or result.get("traceId") or ""
        lines = ["妙想AI社区发文结果"]
        if code is not None:
            lines.append(f"code: {code}")
        if status is not None:
            lines.append(f"status: {status}")
        if message:
            lines.append(f"message: {message}")
        if request_id:
            lines.append(f"requestId: {request_id}")

        data = result.get("data")
        if data not in (None, ""):
            if isinstance(data, (dict, list)):
                lines.append("data:")
                lines.append(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                lines.append(f"data: {data}")
        return "\n".join(lines)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(normalize_command_args())

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        client = MXPoster()
        if args.command == "post":
            text, text_source = read_text_content(args.text, args.text_file)
            ensure_valid_article(args.title, text)

            article_name = safe_filename(args.title)
            result = client.post_article(args.title, text)
            safe_print(client.format_pretty(result))

            text_path = output_dir / f"mx_poster_{article_name}.txt"
            text_path.write_text(text, encoding="utf-8")
            safe_print(f"\n✅ 正文已保存到: {text_path}")

            description_path = output_dir / f"mx_poster_{article_name}_description.txt"
            description_path.write_text(
                build_description(args.title, text_source, args.description, client.base_url),
                encoding="utf-8",
            )
            safe_print(f"📝 描述已保存到: {description_path}")

            raw_path = save_raw_result(output_dir, f"mx_poster_{article_name}", result)
            safe_print(f"📄 原始响应已保存到: {raw_path}")

            if not client.is_success(result):
                sys.exit(1)

            if args.reply_text and args.reply_text.strip():
                interaction_summary = run_auto_interaction(
                    client,
                    output_dir,
                    args.persona_name,
                    args.persona_keyword,
                    args.reply_text,
                )
                if interaction_summary:
                    safe_print(interaction_summary)
            return

        if args.command == "list":
            result = client.query_dynamic_article_list()
            safe_print(format_dynamic_article_list(result))
            raw_path = save_raw_result(output_dir, "mx_poster_dynamic_list", result)
            safe_print(f"\n📄 原始响应已保存到: {raw_path}")
            if not client.is_success(result):
                sys.exit(1)
            return

        if args.command == "like":
            try:
                result = client.like_article(args.id)
            except Exception:
                sys.exit(1)
            article = build_article_context(args.id, args.title, args.author)
            summary = format_interaction_summary(like_result={
                "success": client.is_success(result),
                "article": article,
            })
            save_raw_result(output_dir, f"mx_poster_like_{safe_filename(args.title or args.id)}", result)
            if summary:
                safe_print(summary)
            if not client.is_success(result):
                sys.exit(1)
            return

        if args.command == "reply":
            if not args.text.strip():
                raise ValueError("评论内容不能为空")
            try:
                result = client.reply_article(args.id, args.text)
            except Exception:
                sys.exit(1)
            article = build_article_context(args.id, args.title, args.author)
            summary = format_interaction_summary(reply_result={
                "success": client.is_success(result),
                "article": article,
                "text": args.text,
            })
            save_raw_result(output_dir, f"mx_poster_reply_{safe_filename(args.title or args.id)}", result)
            if summary:
                safe_print(summary)
            if not client.is_success(result):
                sys.exit(1)
            return
    except Exception as exc:
        safe_print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()