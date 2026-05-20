"""58同城租房采集器（继承 BaseCrawler）

58同城列表页结构（2024）:
  URL 格式: https://{city}.58.com/zufang/
  房源元素: li[class*="house-cell"]
  标题:     a[class*="house-title"]
  价格:     b[class*="c_ff552e"] 或 .price-common
  户型/面积: .room, .area
  地址/区域: .region > a, .add > a
  图片:     img.lazy（data-original）
"""
import re
import uuid
from typing import Optional

from loguru import logger

from app.core.config import settings
from app.models import Listing, Platform
from app.services.crawler.base import BaseCrawler, COMMON_CITY_CODE

WUBA_CITY_CODE: dict[str, str] = {
    **COMMON_CITY_CODE,
    # 58同城特殊城市代码覆盖
    "北京": "bj",
    "上海": "sh",
    "广州": "gz",
    "深圳": "sz",
    "重庆": "cq",
    "哈尔滨": "haerbin",
}

# 58同城价格筛选（query 参数）
WUBA_PRICE_MAP: list[tuple[int, int, str, str]] = [
    (0,    1500, "0",    "1500"),
    (1500, 2000, "1500", "2000"),
    (2000, 3000, "2000", "3000"),
    (3000, 5000, "3000", "5000"),
    (5000, 8000, "5000", "8000"),
    (8000, 99999, "8000", "0"),
]


class WubaCrawler(BaseCrawler):
    """58同城租房列表页爬虫"""

    PLATFORM = Platform.WUBA
    REQUEST_INTERVAL = 2.2

    def __init__(self):
        super().__init__(cookie_str=settings.WUBA_COOKIE)

    async def _warmup(self, city: str):
        city_code = WUBA_CITY_CODE.get(city, "sh")
        try:
            r = await self.client.get(
                f"https://{city_code}.58.com/",
                headers={"Referer": "https://www.58.com/"},
                timeout=10,
            )
            logger.debug(f"58同城预热: {r.status_code}")
        except Exception as e:
            logger.debug(f"58同城预热失败 (可忽略): {e}")

    def _build_url(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        page: int = 1,
    ) -> str:
        city_code = WUBA_CITY_CODE.get(city, "sh")
        # 58同城地区路径：整租 pn_整租 / 合租 pn_合租
        base = f"https://{city_code}.58.com/zufang/"

        if district_py:
            base = f"https://{city_code}.58.com/{district_py}/zufang/"

        params: list[str] = []
        if max_price:
            for lo, hi, price_lo, price_hi in WUBA_PRICE_MAP:
                if max_price <= hi:
                    params.append(f"minprice={price_lo}")
                    if price_hi != "0":
                        params.append(f"maxprice={price_hi}")
                    break

        if page > 1:
            params.append(f"page={page}")

        url = base
        if params:
            url = base + "?" + "&".join(params)

        return url

    def _list_selector(self) -> str:
        # 58同城使用多种容器，尝试通用选择器
        return "li.house-cell, li[class*=\"house-cell\"], .list-long-rent li"

    async def search(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        max_pages: int = 2,
    ) -> list[Listing]:
        """58同城搜索，无Cookie时提前跳过（JS渲染站点，无Cookie必返回空壳页）"""
        if not self.has_cookie:
            logger.warning(
                "⚠️ 58同城未配置 WUBA_COOKIE，跳过抓取。"
                "58同城页面为 JS 渲染 + 指纹检测，无有效 Cookie 无法获取真实房源。"
                "请在 .env.local 填入 WUBA_COOKIE（从浏览器登录后复制 Cookie 头）。"
            )
            return []
        return await super().search(city, district_py, max_price, max_pages)

    def _diagnose_response(self, html: str, url: str):
        size = len(html)
        if size < 2000:
            logger.error(f"⚠️ 58同城响应过短 ({size}字符)，疑似被反爬: {url}")
            return
        if "passport.58.com" in html or "captcha" in html.lower():
            logger.error("⚠️ 58同城触发验证/登录墙，请填入 WUBA_COOKIE 或稍后重试")
        if "house-cell" not in html and "list-long-rent" not in html:
            logger.warning(f"⚠️ 58同城未找到房源容器，大小 {size} 字符")

    def _parse_item(self, item, city: str) -> Optional[Listing]:
        # ── 标题 + URL ──────────────────────────────────────────
        title_tag = (
            item.select_one("h2 a.strongbox") or        # 新版 58（2025+）
            item.select_one("h2 a") or
            item.select_one("a[class*='house-title']") or
            item.select_one(".house-title") or
            item.select_one("h3 a")
        )
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not href:
            return None
        url = href if href.startswith("http") else f"https://www.58.com{href}"

        # 平台 ID（从 URL 提取数字 ID）
        m = re.search(r"/(\d{8,})\.html", url)
        platform_id = m.group(1) if m else str(uuid.uuid4())[:8]

        # ── 价格 ─────────────────────────────────────────────────
        price_base = 0
        price_tag = (
            item.select_one("b.strongbox") or           # 新版 58（2025+）
            item.select_one("b[class*='strongbox']") or
            item.select_one("b[class*='c_ff552e']") or  # 旧版兼容
            item.select_one(".price-common b") or
            item.select_one(".price b") or
            item.select_one(".house-price b") or
            item.select_one(".house-price")
        )
        if price_tag:
            price_base, _ = self._extract_price(price_tag.get_text(strip=True))

        # ── 户型 / 面积 ────────────────────────────────────────
        layout = ""
        area_val: Optional[float] = None

        room_tag = item.select_one(".room")
        area_tag = item.select_one(".area")
        floor_tag = item.select_one(".fl")

        room_text = room_tag.get_text(strip=True) if room_tag else ""
        area_text = area_tag.get_text(strip=True) if area_tag else ""
        floor_text = floor_tag.get_text(strip=True) if floor_tag else ""
        combined = f"{room_text} {area_text} {floor_text}"

        area_val = self._extract_area(combined) or self._extract_area(area_text)
        layout = self._extract_layout(room_text, title) or self._extract_layout(combined, title)
        floor = self._extract_floor(floor_text) or self._extract_floor(combined)
        orientation = self._extract_orientation(combined, title)

        # ── 地区 / 小区 ──────────────────────────────────────────
        community = ""
        district_name = ""
        biz_area = ""

        # 58同城地址格式：.region > a（区）+ .add > a（商圈/小区）
        region_tag = item.select_one(".region")
        add_tag = item.select_one(".add")

        if region_tag:
            links = region_tag.find_all("a")
            if links:
                district_name = links[0].get_text(strip=True)
            if len(links) >= 2:
                biz_area = links[1].get_text(strip=True)

        if add_tag:
            add_links = add_tag.find_all("a")
            if add_links:
                community = add_links[-1].get_text(strip=True)

        if not community and not district_name:
            # 兜底：找包含地址信息的 span
            for tag in item.select("span, em"):
                txt = tag.get_text(strip=True)
                if re.search(r"[区路街道弄号]", txt) and len(txt) < 30:
                    community = txt
                    break

        address_parts = [p for p in [district_name, biz_area, community] if p]
        full_address = " ".join(address_parts) if address_parts else community

        # ── 图片 ─────────────────────────────────────────────────
        images = []
        # 58同城图片常见选择器（按常见度排序）
        img_tag = (
            item.select_one("img.lazy") or
            item.select_one("img[data-original]") or
            item.select_one(".pic img") or
            item.select_one(".house-img img") or
            item.select_one(".img-wrap img") or
            item.select_one(".list-img img") or
            item.select_one("img[class*='lazy']") or
            item.select_one("img")
        )
        if img_tag:
            src = (img_tag.get("data-original") or img_tag.get("data-src")
                   or img_tag.get("src", ""))
            # 排除明显无效的URL（占位图、base64、相对路径等）
            if src and src.startswith("http") and "placeholder" not in src:
                # 58同城部分图片URL可能以 // 开头（协议相对URL）
                if not src.startswith("http"):
                    src = "https:" + src
                # 过滤掉常见占位图特征
                if not any(x in src for x in ["noimg", "nopic", "default.gif", "no-pic"]):
                    images.append(src)

        # ── 租住形态 ─────────────────────────────────────────────
        rental_type_tag = self._extract_rental_type(title)
        if not rental_type_tag:
            for tag_el in item.select(".house-tag span, .tags span"):
                t = tag_el.get_text(strip=True)
                if "整租" in t:
                    rental_type_tag = "整租"
                    break
                if "合租" in t:
                    rental_type_tag = "合租"
                    break

        # ── 缺失字段 ─────────────────────────────────────────────
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
        if combined.strip():
            raw["house_info"] = combined.strip()

        return Listing(
            id=f"wuba_{platform_id}",
            platform=Platform.WUBA,
            platform_id=platform_id,
            url=url,
            title=title,
            price_base=price_base,
            area=area_val,
            layout=layout,
            floor=floor,
            orientation=orientation,
            rental_type_tag=rental_type_tag,
            community=community,
            address=full_address,
            images=images,
            raw_data=raw,
            missing_fields=missing,
        )


wuba_crawler = WubaCrawler()
