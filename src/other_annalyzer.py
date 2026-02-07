import logging
import re
from datetime import datetime, date
from typing import Any

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)


def get_last_article_text() -> str:
    id = get_last_article_id()
    return fetch_article_txt(id)


def get_last_article_id() -> Any | None:
    """
    获取九哥的头条
    Returns: 最新一篇推文的 ID

    """
    url = "https://www.toutiao.com/api/pc/list/feed"

    # 将参数拆分出来，方便后续维护
    params = {
        "category": "pc_profile_ugc",
        "token": "MS4wLjABAAAADLJbX9HGg4JV5O--WsgXPEXZjKqKAstBMKslffNNdA413X6rJArWdE7kzPWlZ3AD",
        "max_behot_time": 0,
        "entrance_gid": "",
        "aid": 24,
        "app_name": "toutiao_web",
        "msToken": "aR3C1QwV5UmFnysy-HoHL0JIJrcrODOLp9YICuxRD7Yn2gtPq7hkLmXaDYDhHii3UzwAtS57rrlso5f822EYu_Ej1WBTPzJENV72Of2_9M5fyW82RkdvOoKjv86KH2Y=",
        "a_bogus": "mv8ZQmzkdkgTvfWp5-nLfY3qVXF3YmHu0t9bMDhqOV3t9y39HMO39exYPSvvgJgjEs/8IeSjy4hbYrCgrQCyM1wf7Wsx/2CZmyh0t-P2so0j53intL6mE0hN-Jj3SFlm5XNAEOJ0y75bKYi0AIK95kIlO6ZCcHgOEisnOHL=",
    }

    headers = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0"
        ),
    }

    resp = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10
    )

    resp.raise_for_status()
    try:
        data = resp.json()
        items = data["data"]
        if items.__len__() == 0:
            return None
        last_id = items[0]["id"]
        logger.info("获取九哥最新推文ID：{}".format(last_id))
        return last_id
    except Exception as e:
        print(f"解析失败: {e}")


def fetch_article_txt(id: str) -> str:
    url = f"https://www.toutiao.com/w/{id}"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
    }

    cookies = {
        "ttwid": "1|HRgWdbcpP8M_-3_mZ9l3vLLTxtwFBzq90xzTlgFaQgs|1770477387|1e86b1d160c645f1a3ece21faa31013ca5e07a348796bfb3c04c55fbdb8fdce4",
    }

    resp = requests.get(url, headers=headers, cookies=cookies, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # 1️⃣ 定位文章正文
    content_div = soup.select_one("article .weitoutiao-html")
    if not content_div:
        raise ValueError("未找到文章正文")

    # 2️⃣ <br> 转换为换行
    for br in content_div.find_all("br"):
        br.replace_with("\n")

    # 3️⃣ 提取纯文本
    text = content_div.get_text()

    # 4️⃣ 清洗多余空行 / 空格
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def is_today(timestamp: int) -> bool:
    """
    判断时间戳是否为当天（本地时间）
    """
    dt = datetime.fromtimestamp(timestamp)  # 本地时间
    return dt.date() == date.today()

if __name__ == '__main__':
    print(get_last_article_text())
