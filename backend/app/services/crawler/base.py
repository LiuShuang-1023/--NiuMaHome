"""爬虫抽象基类

所有平台爬虫继承此类，只需重写：
  - BASE_DOMAIN  : 平台域名前缀（如 "lianjia.com"）
  - PLATFORM     : Platform 枚举值（如 Platform.LIANJIA）
  - CITY_CODE    : 城市→子域/路径映射
  - _build_url() : 构造列表页 URL
  - _parse_item(): 解析单条房源 HTML 元素

通用流程（search / _warmup / _parse_list）由基类实现。
"""
import asyncio
import re
import uuid
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.models import Listing, Platform

# 模拟真实 Chrome 124 完整 Header（所有平台共用）
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# 城市名 → 通用子域拼音（链家/贝壳/安居客 / 58 均用此表）
COMMON_CITY_CODE: dict[str, str] = {
    "北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz",
    "杭州": "hz", "成都": "cd", "南京": "nj", "武汉": "wh",
    "西安": "xa", "苏州": "su", "天津": "tj", "重庆": "cq",
    "厦门": "xm", "长沙": "cs", "福州": "fz", "郑州": "zz",
    "合肥": "hf", "济南": "jn", "昆明": "km", "沈阳": "sy",
    "青岛": "qd", "大连": "dl", "哈尔滨": "hrb", "长春": "cc",
}

# 价格档位（链家/贝壳共用）
PRICE_RP: dict[tuple[int, int], str] = {
    (0, 1500): "rp1",
    (1500, 2000): "rp2",
    (2000, 3000): "rp3",
    (3000, 5000): "rp4",
    (5000, 8000): "rp5",
    (8000, 99999): "rp6",
}


class BaseCrawler(ABC):
    """租房平台采集器基类"""

    # 子类必须设置
    PLATFORM: Platform
    REQUEST_INTERVAL: float = 1.8  # 每页请求间隔（秒）

    def __init__(self, cookie_str: str = ""):
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=20.0,
            follow_redirects=True,
        )
        self.has_cookie = bool(cookie_str)
        if cookie_str:
            self.client.headers["Cookie"] = cookie_str
            logger.info(f"✅ {self.PLATFORM.value} Cookie 已注入")
        else:
            logger.warning(
                f"⚠️ {self.PLATFORM.value} Cookie 未配置，可能被反爬。"
                "如多次抓不到，请在 .env.local 填入对应 Cookie。"
            )

    async def close(self):
        await self.client.aclose()

    # ── 子类必须实现 ──────────────────────────────────────────────

    @abstractmethod
    def _build_url(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        page: int = 1,
    ) -> str:
        """构造列表页 URL"""
        ...

    @abstractmethod
    def _parse_item(self, item, city: str) -> Optional[Listing]:
        """解析单条房源 BeautifulSoup 元素"""
        ...

    # ── 子类可选覆盖 ──────────────────────────────────────────────

    def _list_selector(self) -> str:
        """列表页房源容器 CSS 选择器"""
        return "div.content__list--item"

    async def _warmup(self, city: str):
        """预热：先访问首页拿 Cookie，模拟真实用户。子类可覆盖。"""
        pass

    def _diagnose_response(self, html: str, url: str):
        """反爬诊断。子类可覆盖以自定义检测逻辑。"""
        size = len(html)
        if size < 1000:
            logger.error(f"⚠️ {self.PLATFORM.value} 响应过短 ({size}字符)，疑似被反爬: {url}")

    # ── 通用流程（子类不需要覆盖）──────────────────────────────────

    async def search(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        max_pages: int = 2,
    ) -> list[Listing]:
        """搜索房源列表（通用翻页流程）"""
        await self._warmup(city)
        all_listings: list[Listing] = []
        prev_url = self._build_url(city)

        for page in range(1, max_pages + 1):
            url = self._build_url(city, district_py, max_price, page)
            logger.info(f"抓取 {self.PLATFORM.value}: {url}")
            try:
                r = await self.client.get(url, headers={"Referer": prev_url})
                if r.status_code != 200:
                    logger.warning(f"{self.PLATFORM.value} 返回 {r.status_code}, url={url}")
                    break
                self._diagnose_response(r.text, url)
                listings = self._parse_list(r.text, city)
                if not listings:
                    logger.info(f"第 {page} 页无房源，停止")
                    break
                all_listings.extend(listings)
                prev_url = url
                await asyncio.sleep(self.REQUEST_INTERVAL)
            except Exception as e:
                logger.exception(f"{self.PLATFORM.value} 抓取失败: {e}")
                break

        return all_listings

    def _parse_list(self, html: str, city: str) -> list[Listing]:
        """解析列表页 HTML，返回 Listing 列表"""
        soup = BeautifulSoup(html, "lxml")
        items = soup.select(self._list_selector())
        logger.debug(f"{self.PLATFORM.value} 找到 {len(items)} 个候选元素")
        results: list[Listing] = []
        for item in items:
            try:
                listing = self._parse_item(item, city)
                if listing:
                    results.append(listing)
            except Exception as e:
                logger.debug(f"解析单条失败: {e}")
        return results

    # ── 通用解析工具函数（供子类复用）────────────────────────────────

    @staticmethod
    def _extract_price(text: str) -> tuple[int, Optional[str]]:
        """从价格文本提取 (price_base, price_range_str)"""
        text = text.strip()
        range_m = re.match(r"(\d+)\s*-\s*(\d+)", text)
        if range_m:
            return int(range_m.group(1)), f"{range_m.group(1)}-{range_m.group(2)}"
        num_m = re.search(r"\d+", text)
        return (int(num_m.group()), None) if num_m else (0, None)

    @staticmethod
    def _extract_area(text: str) -> Optional[float]:
        m = re.search(r"(\d+(?:\.\d+)?)\s*㎡", text)
        return float(m.group(1)) if m else None

    @staticmethod
    def _extract_layout(text: str, title: str = "") -> str:
        m = re.search(r"(\d+室\d+厅(?:\d+卫)?)", text)
        if m:
            return m.group(1)
        if "开间" in text or "开间" in title:
            return "开间"
        return ""

    @staticmethod
    def _extract_orientation(text: str, title: str = "") -> str:
        for d in ["东南", "西南", "东北", "西北", "东", "南", "西", "北"]:
            if f" {d} " in text or f"/{d}/" in text:
                return d
        m = re.search(r"\b([东南西北]{1,2})\b", title)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_floor(text: str) -> str:
        m = re.search(r"(高楼层|中楼层|低楼层)", text)
        floor = m.group(1) if m else ""
        m_total = re.search(r"（(\d+)层）|共(\d+)层", text)
        if m_total and floor:
            total = m_total.group(1) or m_total.group(2)
            floor = f"{floor}/共{total}层"
        return floor

    @staticmethod
    def _extract_rental_type(title: str) -> str:
        if "合租" in title:
            return "合租"
        if "整租" in title:
            return "整租"
        if "独栋" in title or "公寓" in title:
            return "公寓"
        return ""

    @staticmethod
    def _make_id(platform: str, platform_id: str) -> str:
        return f"{platform}_{platform_id}"

    @staticmethod
    def _random_id() -> str:
        return str(uuid.uuid4())[:8]
