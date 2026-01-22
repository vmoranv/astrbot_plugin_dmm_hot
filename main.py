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

from bs4 import BeautifulSoup
import aiohttp

QUERY_TERM_MAP = {
    "daily": "日榜",
    "weekly": "周榜",
    "monthly": "月榜",
}

HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

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
        options = {"quality": 95, "device_scale_factor_level": "ultra", "viewport_width": 505}
        img_result = await self.html_render(self.html_template, context_data, options=options)
        return img_result


    async def fetch_dmm_top(self, session,query_term:str = "daily") -> List[Dict]:
        """
        抓取DMM 热榜
        :param session:
        :param query_term: daily 日榜, weekly 周榜, monthly 月榜
        :return:List[Dict:{title,src,id}]
        """
        url = f"https://www.dmm.co.jp/digital/videoa/-/ranking/=/term={query_term}/"
        # 需要为cookies 设置 age_check_done=1，否则会返回年龄检查页面
        try:
            async with session.get(url, headers=HEADERS,cookies={"age_check_done": "1"}) as resp:
                # 获取网页内容文本
                html_content = await resp.text()
                logger.info(f"DMM热榜：开始抓取: {url}")
                #解析 HTML
                soup = BeautifulSoup(html_content, 'html.parser')
                # 结果列表
                results = []

                # DMM的排名通常位于 class="work" 的 table 内
                # 每一个排名项通常在一个 td 中，且包含 class="rank"
                # 我们先找到所有的 rank 标签，然后向上查找其父容器
                rank_items = soup.select('.area-rank table.work .rank')

                print(f"检测到 {len(rank_items)} 个排名作品。\n")
                print(f"{'排名':<5} {'出演者':<20} {'标题'}")
                print("-" * 80)

                for rank_item in rank_items:
                    # 获取排名数字
                    rank = rank_item.get_text(strip=True)

                    # 获取该排名所在的容器 (td)
                    container = rank_item.find_parent('td')

                    if not container:
                        continue

                    # --- 提取封面和标题 ---
                    # 这里的图片通常包含封面URL(src)和标题(alt)
                    img_tag = container.find('img')
                    if img_tag:
                        cover_url = img_tag.get('src')
                        title = img_tag.get('alt')
                    else:
                        cover_url = "未找到图片"
                        title = "未找到标题"


                    # 原本cover url格式为 https://pics.dmm.co.jp/digital/video/sone00846/sone00846pt.jpg
                    # 详情页的cover url格式为https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/sone00846/sone00846jp-1.jpg
                    #                     https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/cawd00891/cawd00891pl.jpg?f=webp
                    # 抓取链接中倒数第二个目录为番号
                    javid = cover_url.split("/")[-2]

                    # 根据番号生成新的cover url
                    # new_cover_url = f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{javid}/{javid}jp-1.jpg"
                    new_cover_url = f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{javid}/{javid}pl.jpg"
                    performers = []
                    data_div = container.select_one('.data')
                    bus_no = javid.replace("00", "-", 1)

                    if data_div:
                        # 方法：查找所有链接中包含 'actress' 字样的 a 标签
                        actress_links = data_div.select('a[href*="actress"]')
                        if actress_links:
                            for a in actress_links:
                                performers.append(a.get_text(strip=True))
                        else:
                            # 如果没有链接，可能显示为 "----" 或文本
                            # 检查 data_div 的纯文本内容
                            text_content = data_div.get_text()
                            if "出演者：----" in text_content:
                                performers.append("----")
                            else:
                                # 尝试简单的文本分割作为备选方案
                                pass

                    if not performers:
                        performers = ["未公开/未知"]

                    results.append({
                        "jav_id": bus_no ,
                        "rank": rank,
                        "title": title,
                        "performers": performers,
                        "cover_url": await self._url_to_base64(session,new_cover_url,"")
                    })

                return results
        except Exception as e:
            logger.exception(f"DMM热榜：获取DMM数据失败: {e}")
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
