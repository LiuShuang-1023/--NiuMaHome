"""详情页二次抓取 & 解析（链家 / 贝壳共用）

链家与贝壳详情页 DOM 结构几乎完全一致，用统一解析器处理。

可提取字段（列表页抓不到的增量字段）：
  - deposit_type     押付方式  e.g. "押一付一" "押一付三"
  - heating_type     供暖方式  e.g. "自供暖" "集中供暖"
  - water_type       用水类型  e.g. "民水" "商水"
  - electricity_type 用电类型  e.g. "民电" "商电"
  - gas_type         燃气     e.g. "天然气" "无"
  - elevator         电梯     bool（详情页 li.floor 中含"有电梯"/"无电梯"）
  - move_in          入住时间  e.g. "随时入住" "2024-06-01"
  - facilities       配套设施  list[str]  e.g. ["洗衣机","空调","冰箱"]
  - images           图片列表  list[str]  （补全列表页只有缩略图的情况）
  - description      房东/中介文字描述
"""
import asyncio
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.core.config import settings

# ─── 复用相同的 Header ─────────────────────────────────────────
_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}

# 配套设施关键词（li.fl.oneline 里有这些文字 = 已有该设施）
_FACILITY_KEYWORDS = [
    "洗衣机", "空调", "冰箱", "热水器", "天然气",
    "暖气", "宽带", "床", "衣柜", "沙发",
    "电视", "微波炉", "油烟机",
]

# 押付方式正则
_DEPOSIT_RE = re.compile(r"押[一二三六十\d]+付[一二三六十\d]+|押金[^，。\s]{0,10}")


class ListingDetail:
    """详情页抓取结果（仅存放增量字段）"""
    __slots__ = [
        "deposit_type", "heating_type", "water_type", "electricity_type",
        "gas_type", "elevator", "move_in", "facilities", "images", "description",
    ]

    def __init__(self):
        self.deposit_type: Optional[str] = None
        self.heating_type: Optional[str] = None
        self.water_type: Optional[str] = None
        self.electricity_type: Optional[str] = None
        self.gas_type: Optional[str] = None
        self.elevator: Optional[bool] = None
        self.move_in: Optional[str] = None
        self.facilities: list[str] = []
        self.images: list[str] = []
        self.description: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "deposit_type": self.deposit_type,
            "heating_type": self.heating_type,
            "water_type": self.water_type,
            "electricity_type": self.electricity_type,
            "gas_type": self.gas_type,
            "elevator": self.elevator,
            "move_in": self.move_in,
            "facilities": self.facilities,
            "images": self.images,
            "description": self.description,
        }


def parse_detail_html(html: str, platform: str = "lianjia") -> ListingDetail:
    """从详情页 HTML 解析增量字段（链家/贝壳共用）"""
    detail = ListingDetail()
    soup = BeautifulSoup(html, "lxml")

    # ── 1. 基本信息 li 列表 ───────────────────────────────────────
    # DOM: ul > li.fl.oneline，文字格式 "字段名：值" 或直接是配套设施名
    for li in soup.select("li.fl.oneline"):
        text = li.get_text(" ", strip=True)
        has_no = "facility_no" in " ".join(li.get("class", []))

        # 供暖
        if text.startswith("供暖"):
            detail.heating_type = _after_colon(text)
        # 用水
        elif text.startswith("用水"):
            detail.water_type = _after_colon(text)
        # 用电
        elif text.startswith("用电"):
            detail.electricity_type = _after_colon(text)
        # 燃气
        elif text.startswith("燃气"):
            detail.gas_type = _after_colon(text)
        # 入住
        elif text.startswith("入住"):
            detail.move_in = _after_colon(text)
        # 楼层（补充电梯信息）
        elif text.startswith("楼层") or "电梯" in text:
            if "有电梯" in text:
                detail.elevator = True
            elif "无电梯" in text:
                detail.elevator = False
        # 配套设施
        for kw in _FACILITY_KEYWORDS:
            if kw in text:
                if not has_no:
                    if kw not in detail.facilities:
                        detail.facilities.append(kw)
                break

    # ── 2. 押付方式 ──────────────────────────────────────────────
    # 来源1：i.content__item__tag--deposit_xxx
    deposit_tag = soup.select_one("i[class*='deposit']")
    if deposit_tag:
        detail.deposit_type = deposit_tag.get_text(strip=True)
    # 来源2：备用正则兜底（从 aside 区域找）
    if not detail.deposit_type:
        aside = soup.select_one("div.content__aside")
        if aside:
            aside_text = aside.get_text(" ", strip=True)
            m = _DEPOSIT_RE.search(aside_text)
            if m:
                detail.deposit_type = m.group()

    # ── 3. 图片 ──────────────────────────────────────────────────
    # 详情页图片比列表页多，src 域名：image1.ljcdn.com / ke-image.ljcdn.com
    seen: set[str] = set()
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original"):
            src = img.get(attr, "")
            if src and src not in seen:
                if any(d in src for d in ("ljcdn.com/lease-image", "ke-image.ljcdn.com")):
                    # 去掉缩略图后缀，保留原图
                    src_clean = re.sub(r"\.\d+x\d+\.jpg$", ".jpg", src)
                    detail.images.append(src_clean)
                    seen.add(src)
    detail.images = detail.images[:20]  # 最多20张

    # ── 4. 房东描述（可选，给 AI 点评用） ─────────────────────────
    desc_el = soup.select_one("div.content__article--desc")
    if not desc_el:
        desc_el = soup.select_one("div.description")
    if desc_el:
        detail.description = desc_el.get_text(" ", strip=True)[:500]

    return detail


def _after_colon(text: str) -> Optional[str]:
    """提取 '字段名：值' 中的值部分"""
    for sep in ("：", ":"):
        if sep in text:
            return text.split(sep, 1)[1].strip() or None
    return text.strip() or None


# ─── HTTP 客户端（单例，全局复用）──────────────────────────────────
class DetailFetcher:
    """详情页异步抓取器（链家/贝壳共用同一个 httpx 连接池）"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _make_client(self, cookie_lj: str, cookie_bk: str) -> httpx.AsyncClient:
        # 注意：链家和贝壳 cookie 域不同，这里只做 User-Agent 级别的公共 header
        # cookie 在每次请求时按 URL 动态注入
        return httpx.AsyncClient(
            headers=_BASE_HEADERS,
            timeout=15.0,
            follow_redirects=True,
        )

    async def fetch(self, url: str) -> Optional[str]:
        """抓取一个详情页，返回 HTML 字符串；失败返回 None"""
        # 按 URL 判断平台，注入对应 cookie
        if "lianjia.com" in url:
            cookie = settings.LIANJIA_COOKIE or ""
            referer = "https://gz.lianjia.com/zufang/"
        elif "ke.com" in url:
            cookie = settings.BEIKE_COOKIE or ""
            referer = "https://gz.zu.ke.com/zufang/"
        else:
            cookie = ""
            referer = url

        headers = {"Referer": referer}
        if cookie:
            headers["Cookie"] = cookie

        try:
            async with httpx.AsyncClient(
                headers=_BASE_HEADERS, timeout=15, follow_redirects=True
            ) as client:
                r = await client.get(url, headers=headers)
                if r.status_code != 200:
                    logger.warning(f"[detail] {r.status_code} {url}")
                    return None
                if len(r.text) < 3000:
                    logger.warning(f"[detail] 响应过短 ({len(r.text)}字符): {url}")
                    return None
                return r.text
        except Exception as e:
            logger.warning(f"[detail] 请求失败 {url}: {e}")
            return None

    async def fetch_and_parse(self, url: str, platform: str = "lianjia") -> Optional[ListingDetail]:
        """抓取 + 解析，返回 ListingDetail 或 None"""
        html = await self.fetch(url)
        if not html:
            return None
        return parse_detail_html(html, platform)


# 单例
detail_fetcher = DetailFetcher()
