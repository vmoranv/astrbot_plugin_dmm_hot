import asyncio
import datetime
import os
from typing import List, Dict
import base64

from aiohttp import ClientTimeout
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import Image

import aiohttp

QUERY_TERM_MAP = {
    "daily": "日榜",
    "weekly": "周榜",
    "monthly": "月榜",
}

API_URL = "https://api.video.dmm.co.jp/graphql"

# GraphQL 查询
RANKING_QUERY = """
query ContentRankingPage($limit: Int!, $offset: Int!, $filter: PPVContentRankingFilterInput, $isAmateur: Boolean = false) {
  ppvContentRanking(limit: $limit, offset: $offset, filter: $filter) {
    items {
      id
      rank
      content {
        title
        releaseStatus
        packageImage {
          mediumUrl
          largeUrl
          __typename
        }
        wishlistCount
        isExclusiveDelivery
        actresses @skip(if: $isAmateur) {
          id
          name
          __typename
        }
        sampleImages {
          number
          largeImageUrl
          __typename
        }
        hasSampleMovie
        review {
          average
          total
          __typename
        }
        __typename
      }
      __typename
    }
    ... on PPVContentTrendingRanking {
      targetWindowEndAt
      __typename
    }
    __typename
  }
}
"""

HEADERS = {
    "accept": "application/graphql-response+json, application/graphql+json, application/json, text/event-stream, multipart/mixed",
    "accept-language": "zh-CN",
    "content-type": "application/json",
    "fanza-device": "BROWSER",
    "origin": "https://video.dmm.co.jp",
    "referer": "https://video.dmm.co.jp/av/ranking/",
    "sec-ch-ua": '"Microsoft Edge";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

TERM_FILTER_MAP = {
    "daily": {"daily": {"floor": "AV"}},
    "weekly": {"weekly": {"floor": "AV"}},
    "monthly": {"monthly": {"floor": "AV"}},
}


def parse_javid(content_id: str) -> str:
    """从 content.id 提取番号，如 ofje00512 -> ofje-512"""
    return content_id.replace("00", "-", 1)


def get_cover_url(package_image: dict) -> str:
    """获取封面图 URL，优先 largeUrl"""
    if package_image and package_image.get("largeUrl"):
        return package_image["largeUrl"]
    if package_image and package_image.get("mediumUrl"):
        return package_image["mediumUrl"]
    return ""

@register("DmmHot", "Kazuki", "Dmm热榜数据查询", "1.0.0")
class DmmHot(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.html_template = ""

    async def initialize(self):
        # 本地读取模板文件
        current_dir = os.path.dirname(os.path.abspath(__file__))
        template_path = os.path.join(current_dir, "templates", "report.html")
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                self.html_template = f.read()
            logger.info(f"DMM热榜：成功加载模板: {template_path}")
        except FileNotFoundError:
            logger.error(f"DMM热榜：未找到模板文件: {template_path}")
            # 设置一个简单的兜底模板，防止崩溃
            self.html_template = "<h1>Template Not Found</h1>"

        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

    @filter.command("dmm周榜")
    async def dmm_weekly_report(self, event: AstrMessageEvent):
        img_result = await self.generate_html(query_term="weekly")
        yield event.image_result(img_result)

    @filter.llm_tool(name="dmm_weekly")
    async def llm_weekly_report(self, event: AstrMessageEvent):
        """
        发送这周的或者几天的dmm热榜


        """
        img_result = await self.generate_html(query_term="weekly")
        yield event.image_result(img_result)


    @filter.command("dmm月榜")
    async def dmm_monthly_report(self, event: AstrMessageEvent):
        img_result = await self.generate_html(query_term="monthly")
        yield event.image_result(img_result)

    @filter.llm_tool(name="dmm_monthly")
    async def llm_monthly_report(self, event: AstrMessageEvent):
        """
        发送这个月的dmm热榜


        """
        img_result = await self.generate_html(query_term="monthly")
        yield event.image_result(img_result)

    @filter.command("dmm日榜")
    async def dmm_daily_report(self, event: AstrMessageEvent):
        img_result = await self.generate_html(query_term="daily")
        yield event.image_result(img_result)

    @filter.llm_tool(name="dmm_daily")
    async def llm_daily_report(self, event: AstrMessageEvent):
        """
        发送今天的dmm热榜


        """
        img_result = await self.generate_html(query_term="daily")
        yield event.image_result(img_result)

    async def generate_html(self,query_term:str = "daily") -> Image:
        logger.info(f"DMM热榜：开始生成HTML,参数: {query_term}")
        """聚合数据并渲染HTML"""
        # 创建一个异步会话（走代理）
        async with aiohttp.ClientSession(trust_env=True,timeout=ClientTimeout(30)) as sessionProxy:
            # 并发执行所有抓取任务
            dmm_top_list = await asyncio.gather(
                self.fetch_dmm_top(sessionProxy,query_term=query_term),
            )

        # 整理常规数据
        context_data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %A"),
            "term": QUERY_TERM_MAP[query_term],
            "dmm_list": dmm_top_list[0],
        }
        logger.info(f"DMM热榜：渲染数据: {context_data}")
        options = {"quality": 95, "device_scale_factor_level": "ultra"}
        img_result = await self.html_render(self.html_template, context_data, options=options)
        return img_result


    async def fetch_dmm_top(self, session, query_term: str = "daily") -> List[Dict]:
        """通过 GraphQL API 获取 DMM 排名数据"""
        filter_val = TERM_FILTER_MAP.get(query_term, TERM_FILTER_MAP["weekly"])
        payload = {
            "operationName": "ContentRankingPage",
            "query": RANKING_QUERY,
            "variables": {
                "filter": filter_val,
                "isAmateur": False,
                "limit": 100,
                "offset": 0,
            },
        }

        logger.info(f"DMM热榜：正在请求 GraphQL API, term={query_term}")
        try:
            async with session.post(
                API_URL,
                headers=HEADERS,
                json=payload
            ) as resp:
                if resp.status != 200:
                    logger.error(f"DMM热榜：GraphQL 请求失败, status={resp.status}")
                    data = await resp.json()
                    logger.error(f"DMM热榜：错误详情: {data}")
                    return []

                data = await resp.json()
                items = data.get("data", {}).get("ppvContentRanking", {}).get("items", [])
                logger.info(f"DMM热榜：获取到 {len(items)} 个排名作品")

                results = []
                index = 0
                for item in items:
                    index = index + 1
                    if index > 20:
                        break
                    rank = item.get("rank", "")
                    content = item.get("content", {})
                    title = content.get("title", "未找到标题")
                    content_id = item.get("id", "")

                    # 封面图 URL
                    cover_url = get_cover_url(content.get("packageImage"))

                    # 番号
                    jav_id = parse_javid(content_id) if content_id else ""

                    # 出演者
                    performers = []
                    actresses = content.get("actresses", [])
                    if actresses:
                        for actress in actresses:
                            performers.append(actress.get("name", ""))
                    if not performers:
                        performers = ["未公开/未知"]

                    # 下载封面并转为 base64
                    b64_cover = await self._url_to_base64(session, cover_url, "")

                    results.append({
                        "jav_id": jav_id,
                        "rank": str(rank),
                        "title": title,
                        "performers": performers,
                        "cover_url": b64_cover,
                    })

                return results
        except Exception as e:
            logger.exception(f"DMM热榜：获取 DMM 数据失败: {e}")
            return []

    async def _url_to_base64(self, session, url: str, referer: str = "", width: int = 0) -> str:
        """辅助方法：下载图片并转为 Base64 (支持本地缩放)"""
        if not url:
            return ""

        headers = HEADERS.copy()
        if referer:
            headers["Referer"] = referer

        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    mime_type = resp.headers.get("Content-Type", "image/jpeg")
                    b64_str = base64.b64encode(content).decode("utf-8")
                    return f"data:{mime_type};base64,{b64_str}"
        except Exception as e:
            logger.warning(f"DMM热榜：图片下载失败 {url}: {e}")

        return ""

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
