"""安居客租房采集器（v2，修正域名和选择器）

正确结构（2025）:
  URL 格式: https://{abbr}.zu.anjuke.com/              ← 独立租房子域
  容器:     div.zu-itemmod                              ← 注意是 div 不是 li
  标题:     h3 > a
  价格:     strong.price
  户型/面积: p.details-item.tag（含 <b> 数字 + 文字）
  地址:     address.details-item
  图片:     img.thumbnail 的 lazy_src 属性（优先）或 src
  详情URL:  div.zu-itemmod[link] 属性 或 a.img[href]

城市缩写：sh=上海 bj=北京 gz=广州 sz=深圳 hz=杭州 等
"""
import asyncio
import re
import uuid
from typing import Optional

from loguru import logger

from app.core.config import settings
from app.models import Listing, Platform
from app.services.crawler.base import BaseCrawler, COMMON_CITY_CODE

# 安居客租房子域城市缩写（{abbr}.zu.anjuke.com）
# 与链家城市代码略有不同
ANJUKE_ZU_ABBR: dict[str, str] = {
    "北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz",
    "杭州": "hz", "南京": "nj", "苏州": "su", "武汉": "wh",
    "成都": "cd", "西安": "xa", "天津": "tj", "重庆": "cq",
    "郑州": "zz", "长沙": "cs", "青岛": "qd", "大连": "dl",
    "宁波": "nb", "厦门": "xm", "济南": "jn", "合肥": "hf",
    "福州": "fz", "昆明": "km", "哈尔滨": "hrb", "沈阳": "sy",
    "长春": "cc", "南昌": "nc", "贵阳": "gy", "南宁": "nn",
    "太原": "ty", "石家庄": "sjz", "乌鲁木齐": "wlmq",
}


class AnjukeCrawler(BaseCrawler):
    """安居客租房列表页爬虫（v2）"""

    PLATFORM = Platform.ANJUKE
    REQUEST_INTERVAL = 2.5

    def __init__(self):
        super().__init__(cookie_str=settings.ANJUKE_COOKIE)

    def _get_abbr(self, city: str) -> str:
        return ANJUKE_ZU_ABBR.get(city, COMMON_CITY_CODE.get(city, "sh"))

    async def _warmup(self, abbr: str):
        """先访问主站，让 Cookie/Session 生效"""
        try:
            await self.client.get(
                "https://www.anjuke.com/",
                headers={"Referer": ""},
                timeout=10,
            )
            await self.client.get(
                f"https://{abbr}.zu.anjuke.com/",
                headers={"Referer": "https://www.anjuke.com/"},
                timeout=10,
            )
        except Exception as e:
            logger.debug(f"安居客预热失败（可忽略）: {e}")

    def _build_url(
        self,
        abbr: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        page: int = 1,
    ) -> str:
        """构造列表页 URL
        基础: https://{abbr}.zu.anjuke.com/fangyuan/
        区域: https://{abbr}.zu.anjuke.com/fangyuan/{district}/
        价格: ?price=0-3000
        翻页: ?page=2
        """
        if district_py:
            base = f"https://{abbr}.zu.anjuke.com/fangyuan/{district_py}/"
        else:
            base = f"https://{abbr}.zu.anjuke.com/fangyuan/"

        params: list[str] = []
        if max_price:
            params.append(f"price=0-{max_price}")
        if page > 1:
            params.append(f"page={page}")

        return base + ("?" + "&".join(params) if params else "")

    def _list_selector(self) -> str:
        # 保留父类接口兼容，实际在 _parse_list 里 override
        return "div.zu-itemmod"

    def _diagnose_response(self, html: str, url: str):
        if len(html) < 2000:
            logger.error(f"⚠️ 安居客响应过短 ({len(html)}字)，疑似反爬: {url}")
        elif "captcha" in html.lower() or "anzhi.anjuke" in html:
            logger.error("⚠️ 安居客触发验证码，请填入 ANJUKE_COOKIE")
        elif "zu-itemmod" not in html:
            logger.warning(f"⚠️ 安居客未找到房源容器 (len={len(html)})")

    async def search(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        max_pages: int = 2,
    ) -> list[Listing]:
        abbr = self._get_abbr(city)
        await self._warmup(abbr)

        all_listings: list[Listing] = []
        prev_url = f"https://{abbr}.zu.anjuke.com/"

        for page in range(1, max_pages + 1):
            url = self._build_url(abbr, district_py, max_price, page)
            logger.info(f"抓取 anjuke p{page}: {url}")
            try:
                r = await self.client.get(url, headers={"Referer": prev_url})
                logger.debug(f"安居客 p{page} => {r.status_code}, len={len(r.text)}")

                if r.status_code != 200 or len(r.text) < 3000:
                    self._diagnose_response(r.text, url)
                    break

                if "zu-itemmod" not in r.text:
                    self._diagnose_response(r.text, url)
                    break

                listings = self._parse_list(r.text, city)
                logger.info(f"安居客 p{page} 解析到 {len(listings)} 条")
                if not listings:
                    break

                all_listings.extend(listings)
                prev_url = url

                if page < max_pages:
                    await asyncio.sleep(self.REQUEST_INTERVAL)
            except Exception as e:
                logger.warning(f"安居客 p{page} 异常: {e}")
                break

        if not all_listings:
            logger.warning(
                f"⚠️ 安居客未抓到房源（城市={city}, abbr={abbr}）"
                f"\n  建议：在 .env.local 中填入 ANJUKE_COOKIE"
            )
        return all_listings

    def _parse_list(self, html: str, city: str) -> list[Listing]:
        """直接用 BeautifulSoup 解析 div.zu-itemmod"""
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # 安居客是 div.zu-itemmod，不是 li
        items = soup.select("div.zu-itemmod")
        results = []
        for item in items:
            try:
                listing = self._parse_item(item, city)
                if listing and listing.price_base > 0:
                    results.append(listing)
            except Exception as e:
                logger.debug(f"安居客解析单条失败: {e}")
        return results

    def _parse_item(self, item, city: str) -> Optional[Listing]:
        # ── URL（div[link] 属性最可靠）────────────────────────
        href = item.get("link", "")
        if not href:
            a_tag = item.select_one("a.img") or item.select_one("h3 a")
            href = a_tag.get("href", "") if a_tag else ""
        if not href:
            return None
        url = href if href.startswith("http") else f"https://www.anjuke.com{href}"

        # 从 URL 提取平台 ID
        m = re.search(r"/fangyuan/(\d+)", url)
        platform_id = m.group(1) if m else str(uuid.uuid4())[:8]

        # ── 标题 ──────────────────────────────────────────────
        h3 = item.select_one("h3")
        title = h3.get_text(strip=True) if h3 else ""
        if not title:
            a = item.select_one("a.img")
            title = a.get("alt", "") if a else ""
        if not title:
            return None

        # ── 价格（strong.price > 文字数字）────────────────────
        price_base = 0
        price_tag = item.select_one("strong.price")
        if price_tag:
            # strong.price 内是纯数字，span.unit 是"元/月"
            num_text = ""
            for child in price_tag.children:
                t = getattr(child, "get_text", lambda **kw: str(child))(strip=True)
                if re.search(r"\d{3,}", t):
                    num_text = t
                    break
            if not num_text:
                num_text = price_tag.get_text(strip=True)
            price_base, _ = self._extract_price(num_text)

        # 备用：从 zu-side div 取
        if not price_base:
            side = item.select_one("div.zu-side")
            if side:
                price_base, _ = self._extract_price(side.get_text(strip=True))

        # ── 户型 / 面积 / 楼层（p.details-item.tag）──────────
        layout = ""
        area_val: Optional[float] = None
        floor = ""
        orientation = ""

        detail_tag = item.select_one("p.details-item.tag")
        if detail_tag:
            detail_text = detail_tag.get_text(" ", strip=True)
            # 户型：X室X厅
            layout = self._extract_layout(detail_text, title) or ""
            area_val = self._extract_area(detail_text)
            floor = self._extract_floor(detail_text)
            orientation = self._extract_orientation(detail_text, title)

        # ── 地址（address.details-item）──────────────────────
        community = ""
        district_name = ""
        biz_area = ""
        full_address = ""

        addr_tag = item.select_one("address.details-item")
        if addr_tag:
            # 结构通常是：城区 > 商圈 > 街道
            addr_text = addr_tag.get_text(" ", strip=True)
            full_address = addr_text
            # 尝试拆分
            parts = [p.strip() for p in re.split(r"[-–\s·]+", addr_text) if p.strip()]
            if parts:
                community = parts[-1]
            if len(parts) >= 2:
                biz_area = parts[-2]
            if len(parts) >= 3:
                district_name = parts[0]

        # ── 图片（img.thumbnail 的 lazy_src 优先）────────────
        images: list[str] = []
        img_tag = item.select_one("img.thumbnail") or item.select_one("a.img img") or item.select_one("img")
        if img_tag:
            src = (
                img_tag.get("lazy_src") or
                img_tag.get("data-src") or
                img_tag.get("data-original") or
                img_tag.get("src", "")
            )
            if src and src.startswith("//"):
                src = "https:" + src
            # 排除占位图（58cdn 的 n_v2... 是占位，ajkimg 才是真实图）
            PLACEHOLDER_MARKS = ["nowater/fangfe/n_v2", "nopic", "no-pic", "blank.png", "placeholder", "default.gif"]
            if src and src.startswith("http") and not any(m in src for m in PLACEHOLDER_MARKS):
                images.append(src)

        # ── 租住形态 ─────────────────────────────────────────
        rental_type = self._extract_rental_type(title)

        missing = []
        if not price_base:
            missing.append("价格")
        if not area_val:
            missing.append("面积")
        if not layout:
            missing.append("户型")
        if not images:
            missing.append("图片")

        raw: dict = {}
        if biz_area:
            raw["biz_area"] = biz_area
        if district_name:
            raw["district"] = district_name

        return Listing(
            id=f"anjuke_{platform_id}",
            platform=Platform.ANJUKE,
            platform_id=platform_id,
            url=url,
            title=title,
            price_base=price_base,
            area=area_val,
            layout=layout,
            floor=floor,
            orientation=orientation,
            rental_type_tag=rental_type,
            community=community,
            address=full_address,
            images=images,
            raw_data=raw,
            missing_fields=missing,
        )


anjuke_crawler = AnjukeCrawler()
