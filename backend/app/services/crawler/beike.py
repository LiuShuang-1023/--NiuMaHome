"""贝壳找房租房采集器

贝壳是链家母公司，URL 模式：
https://{城市拼音}.zu.ke.com/zufang/{区域拼音}/

字段结构与链家几乎一致，但反爬策略略不同，作为链家备份。
"""
import asyncio
import re
import uuid
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.core.config import settings
from app.models import Listing, Platform


CITY_CODE = {
    "北京": "bj", "上海": "sh", "广州": "gz", "深圳": "sz",
    "杭州": "hz", "成都": "cd", "南京": "nj", "武汉": "wh",
    "西安": "xa", "苏州": "su", "天津": "tj", "重庆": "cq",
}

PRICE_RP = {
    (0, 1500): "rp1",
    (1500, 2000): "rp2",
    (2000, 3000): "rp3",
    (3000, 5000): "rp4",
    (5000, 8000): "rp5",
    (8000, 99999): "rp6",
}

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


class BeikeCrawler:
    """贝壳找房采集器"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=20.0,
            follow_redirects=True,
        )
        if settings.BEIKE_COOKIE:
            self.client.headers["Cookie"] = settings.BEIKE_COOKIE
            logger.info("✅ 贝壳 Cookie 已注入")

    async def close(self):
        await self.client.aclose()

    def _build_url(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        page: int = 1,
    ) -> str:
        city_code = CITY_CODE.get(city, "gz")
        # 贝壳租房域名
        base = f"https://{city_code}.zu.ke.com/zufang"
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

    async def _warmup(self, city: str):
        city_code = CITY_CODE.get(city, "gz")
        try:
            r = await self.client.get(f"https://{city_code}.zu.ke.com/", timeout=10)
            logger.debug(f"贝壳预热: {r.status_code}")
        except Exception as e:
            logger.debug(f"贝壳预热失败: {e}")

    async def search(
        self,
        city: str,
        district_py: str = "",
        max_price: Optional[int] = None,
        max_pages: int = 2,
    ) -> list[Listing]:
        await self._warmup(city)

        all_listings: list[Listing] = []
        prev_url = f"https://{CITY_CODE.get(city, 'gz')}.zu.ke.com/"

        for page in range(1, max_pages + 1):
            url = self._build_url(city, district_py, max_price, page)
            logger.info(f"抓取贝壳: {url}")
            try:
                r = await self.client.get(url, headers={"Referer": prev_url})
                if r.status_code != 200:
                    logger.warning(f"贝壳返回 {r.status_code}")
                    break

                if len(r.text) < 1000:
                    logger.error(f"⚠️ 贝壳响应过短 ({len(r.text)}字符)")
                    break

                listings = self._parse_list(r.text, city)
                if not listings:
                    logger.info(f"贝壳第 {page} 页无房源，停止")
                    break

                all_listings.extend(listings)
                prev_url = url
                await asyncio.sleep(1.8)
            except Exception as e:
                logger.exception(f"贝壳抓取失败: {e}")
                break

        return all_listings

    def _parse_list(self, html: str, city: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        # 贝壳和链家用同样的 class
        items = soup.select("div.content__list--item")
        logger.debug(f"贝壳找到 {len(items)} 个候选元素")

        results: list[Listing] = []
        for item in items:
            try:
                listing = self._parse_item(item, city)
                if listing:
                    results.append(listing)
            except Exception as e:
                logger.debug(f"贝壳解析单条失败: {e}")
                continue
        return results

    def _parse_item(self, item, city: str) -> Optional[Listing]:
        title_tag = item.select_one(".content__list--item--title a")
        if not title_tag:
            return None
        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        if not href:
            return None
        if href.startswith("/"):
            city_code = CITY_CODE.get(city, "gz")
            url = f"https://{city_code}.zu.ke.com{href}"
        else:
            url = href

        m = re.search(r"/zufang/(\w+)\.html", url)
        platform_id = m.group(1) if m else str(uuid.uuid4())[:8]

        # ===== 价格（含区间处理）=====
        price_tag = item.select_one(".content__list--item-price em")
        price_base = 0
        price_range = None
        if price_tag:
            price_text = price_tag.get_text(strip=True)
            range_m = re.match(r"(\d+)\s*-\s*(\d+)", price_text)
            if range_m:
                price_base = int(range_m.group(1))
                price_range = f"{range_m.group(1)}-{range_m.group(2)}"
            else:
                num_m = re.search(r"\d+", price_text)
                if num_m:
                    price_base = int(num_m.group())

        # ===== 描述区域 =====
        desc_tag = item.select_one(".content__list--item--des")
        layout = ""
        area = None
        floor = ""
        orientation = ""
        community = ""
        district_name = ""
        biz_area = ""

        if desc_tag:
            desc_text = desc_tag.get_text(" ", strip=True)
            m = re.search(r"(\d+(?:\.\d+)?)\s*㎡", desc_text)
            if m:
                area = float(m.group(1))
            m = re.search(r"(\d+室\d+厅(?:\d+卫)?)", desc_text)
            if m:
                layout = m.group(1)
            elif "开间" in desc_text or "开间" in title:
                layout = "开间"
            for d in ["东南", "西南", "东北", "西北", "东", "南", "西", "北"]:
                if f" {d} " in desc_text or f"/{d}/" in desc_text or f"/ {d} /" in desc_text:
                    orientation = d
                    break
            if not orientation:
                title_orient = re.search(r"\b([东南西北]{1,2})\b", title)
                if title_orient:
                    orientation = title_orient.group(1)
            m = re.search(r"(高楼层|中楼层|低楼层)", desc_text)
            if m:
                floor = m.group(1)
            m_total = re.search(r"（(\d+)层）", desc_text)
            if m_total and floor:
                floor = f"{floor}/共{m_total.group(1)}层"

            links = desc_tag.find_all("a", href=True)
            zufang_links = [a for a in links if "/zufang/" in a.get("href", "") or "/c" in a.get("href", "")]
            if len(zufang_links) >= 1:
                district_name = zufang_links[0].get_text(strip=True)
            if len(zufang_links) >= 2:
                biz_area = zufang_links[1].get_text(strip=True)
            if len(zufang_links) >= 3:
                community = zufang_links[2].get_text(strip=True)
            elif len(zufang_links) >= 1:
                community = zufang_links[-1].get_text(strip=True)

        # ===== 整租/合租/独栋 =====
        rental_type_tag = ""
        if "合租" in title:
            rental_type_tag = "合租"
        elif "整租" in title:
            rental_type_tag = "整租"
        elif "独栋" in title or "公寓" in title:
            rental_type_tag = "公寓"

        # ===== 图片 =====
        img_tag = item.select_one("img.lazyload") or item.select_one(".content__list--item--aside img")
        images = []
        if img_tag:
            src = (img_tag.get("data-src")
                   or img_tag.get("data-original")
                   or img_tag.get("src", ""))
            if src and "default" not in src and "250-182.png" not in src:
                images.append(src)

        # ===== 完整地址 =====
        address_parts = [p for p in [district_name, biz_area, community] if p]
        full_address = " ".join(address_parts) if address_parts else community

        # ===== 缺失字段（中文） =====
        missing = []
        if not price_base or price_base == 0:
            missing.append("价格")
        if not area:
            missing.append("面积")
        if not layout:
            missing.append("户型")
        if not orientation:
            missing.append("朝向")
        if not floor:
            missing.append("楼层")
        if not images:
            missing.append("图片")

        raw = {}
        if price_range:
            raw["price_range"] = price_range
        if biz_area:
            raw["biz_area"] = biz_area
        if district_name:
            raw["district"] = district_name

        return Listing(
            id=f"beike_{platform_id}",
            platform=Platform.BEIKE,
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


beike_crawler = BeikeCrawler()
