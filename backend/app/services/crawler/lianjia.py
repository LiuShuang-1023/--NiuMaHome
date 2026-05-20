"""链家租房采集器（v2，继承 BaseCrawler）"""
import re
import uuid
from typing import Optional

from loguru import logger

from app.core.config import settings
from app.models import Listing, Platform
from app.services.crawler.base import BaseCrawler, COMMON_CITY_CODE, PRICE_RP

CITY_CODE = COMMON_CITY_CODE


class LianjiaCrawler(BaseCrawler):
    PLATFORM = Platform.LIANJIA

    def __init__(self):
        super().__init__(cookie_str=settings.LIANJIA_COOKIE)

    async def _warmup(self, city: str):
        city_code = CITY_CODE.get(city, "gz")
        try:
            r = await self.client.get(f"https://{city_code}.lianjia.com/", timeout=10)
            logger.debug(f"链家预热: {r.status_code}")
        except Exception as e:
            logger.debug(f"链家预热失败 (可忽略): {e}")

    def _build_url(self, city: str, district_py: str = "",
                   max_price: Optional[int] = None, page: int = 1) -> str:
        city_code = CITY_CODE.get(city, "gz")
        base = f"https://{city_code}.lianjia.com/zufang"
        parts = [base]
        if district_py:
            parts.append(district_py)
        if max_price:
            for (lo, hi), rp in PRICE_RP.items():
                if max_price <= hi:
                    parts.append(rp)
                    break
        url = "/".join(parts) + "/"
        if page > 1:
            url += f"pg{page}/"
        return url

    def _list_selector(self) -> str:
        return "div.content__list--item"

    def _diagnose_response(self, html: str, url: str):
        size = len(html)
        if size < 1000:
            logger.error(f"⚠️ 链家响应过短 ({size}字符)，疑似被反爬: {url}")
            return
        if "验证" in html and ("captcha" in html.lower() or "verify" in html.lower()):
            logger.error("⚠️ 链家触发验证码！请填入 LIANJIA_COOKIE 或稍后重试")
        if 'content__list--item' not in html:
            logger.warning(f"⚠️ 链家响应中未找到房源容器，大小 {size} 字符，可能被反爬")

    def _parse_item(self, item, city: str) -> Optional[Listing]:
        title_tag = item.select_one(".content__list--item--title a")
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not href:
            return None
        city_code = CITY_CODE.get(city, "gz")
        url = f"https://{city_code}.lianjia.com{href}" if href.startswith("/") else href

        m = re.search(r"/zufang/(\w+)\.html", url)
        platform_id = m.group(1) if m else str(uuid.uuid4())[:8]

        price_tag = item.select_one(".content__list--item-price em")
        price_base, price_range = 0, None
        if price_tag:
            price_base, price_range = self._extract_price(price_tag.get_text(strip=True))

        desc_tag = item.select_one(".content__list--item--des")
        layout = area = floor = orientation = community = district_name = biz_area = ""
        area = None

        if desc_tag:
            desc_text = desc_tag.get_text(" ", strip=True)
            area = self._extract_area(desc_text)
            layout = self._extract_layout(desc_text, title)
            orientation = self._extract_orientation(desc_text, title)
            floor = self._extract_floor(desc_text)
            links = [a for a in desc_tag.find_all("a", href=True)
                     if "/zufang/" in a.get("href", "") or "/c" in a.get("href", "")]
            if len(links) >= 1:
                district_name = links[0].get_text(strip=True)
            if len(links) >= 2:
                biz_area = links[1].get_text(strip=True)
            if len(links) >= 3:
                community = links[2].get_text(strip=True)
            elif links:
                community = links[-1].get_text(strip=True)

        rental_type_tag = self._extract_rental_type(title)

        img_tag = item.select_one("img.lazyload") or item.select_one(".content__list--item--aside img")
        images = []
        if img_tag:
            src = (img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("src", ""))
            if src and "default" not in src and "250-182.png" not in src:
                images.append(src)

        address_parts = [p for p in [district_name, biz_area, community] if p]
        full_address = " ".join(address_parts) if address_parts else community

        missing = []
        if not price_base:
            missing.append("价格")
        if not area:
            missing.append("面积")
        if not layout:
            missing.append("户型")
        if not images:
            missing.append("图片")

        raw: dict = {}
        if price_range:
            raw["price_range"] = price_range
        if biz_area:
            raw["biz_area"] = biz_area
        if district_name:
            raw["district"] = district_name

        return Listing(
            id=f"lianjia_{platform_id}",
            platform=Platform.LIANJIA,
            platform_id=platform_id,
            url=url,
            title=title,
            price_base=price_base,
            area=area,
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


lianjia_crawler = LianjiaCrawler()
