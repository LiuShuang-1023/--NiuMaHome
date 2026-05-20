"""推荐排序引擎 + 车位过滤 + 价格区间过滤 + 排序模式"""
import re
from typing import Literal

from loguru import logger

from app.models import (
    CommuteSummary,
    CostBreakdown,
    Listing,
    ParsedRequirement,
    Recommendation,
)


# 车位/储藏室关键词（标题中包含 → 排除）
PARKING_KEYWORDS = [
    "车位", "停车位", "停车场", "车库", "地下车位",
    "储藏室", "储物间", "杂物间",
]


def is_parking(listing: Listing) -> bool:
    """判断是否车位/非住宅 (v0.2.2.4 加强阈值)

    实测案例：
    - 华南碧桂园翠山蓝天苑 1室0厅 13.85㎡ ¥500 → 车位（图片为停车场）
    - 昊龙花园北区 1室1厅 13.5㎡ ¥600 → 车位
    - 此类房源标题被链家伪装成"整租·xxx"，无法靠关键词识别，必须靠面积+价格
    """
    title = listing.title or ""
    # 1. 标题关键词（最直接）
    if any(kw in title for kw in PARKING_KEYWORDS):
        return True

    area = listing.area or 0
    price = listing.price_base or 0

    # 2. 面积 ≤ 14㎡ 且价格 ≤ 800：车位特征明显
    # 真实房屋哪怕单间公寓也很少 < 15㎡，且 ≤800 的住宅在一线城市基本不存在
    if 0 < area <= 14 and 0 < price <= 800:
        return True

    # 3. 面积 ≤ 16㎡ 且价格 ≤ 700：极小户型 + 极低价 = 车位
    if 0 < area <= 16 and 0 < price <= 700:
        return True

    # 4. 1室0厅0卫 + 价格 < 800（即使面积稍大也可能是车位/储藏）
    if listing.layout in ["1室0厅", "1室0厅0卫"] and 0 < price < 800:
        return True

    # 5. 户型为空 + 价格 < 800
    if not listing.layout and 0 < price < 800:
        return True
    return False


SortMode = Literal["综合", "价格", "通勤", "面积"]


class Ranker:
    """根据需求对房源排序"""

    def rank(
        self,
        items: list[tuple[Listing, CostBreakdown, CommuteSummary | None]],
        requirement: ParsedRequirement,
        sort_mode: SortMode = "综合",
    ) -> list[Recommendation]:
        """
        排序并生成推荐列表
        """
        if not items:
            return []

        # ===== 硬过滤 =====
        filtered = []
        skip_stats = {"parking": 0, "price_high": 0, "price_low": 0,
                      "commute_far": 0, "excluded": 0, "shared": 0}

        for listing, cost, commute in items:
            # 1. 过滤车位/储藏室
            if is_parking(listing):
                skip_stats["parking"] += 1
                continue

            # 2. 价格硬过滤（上限 + 下限）
            if requirement.price.total_cost_max and cost.total > requirement.price.total_cost_max:
                skip_stats["price_high"] += 1
                continue
            if requirement.price.base_rent_max and listing.price_base > requirement.price.base_rent_max:
                skip_stats["price_high"] += 1
                continue
            # 价格下限（用户说"房租大于 X"）
            if requirement.price.base_rent_min and listing.price_base > 0 and listing.price_base < requirement.price.base_rent_min:
                skip_stats["price_low"] += 1
                continue
            if requirement.price.total_cost_min and cost.total < requirement.price.total_cost_min:
                skip_stats["price_low"] += 1
                continue

            # 3. 通勤超限：仅在离线估算阶段硬过滤；精算后改为软标记降权，不踢出列表
            # 原因：离线估算误差 ±25%，精算后真实值超限不代表完全不可选（用户可自行判断）
            commute_over_limit = False
            if commute and requirement.commute.max_minutes:
                if commute.best_duration_min > requirement.commute.max_minutes:
                    # 判断来源：raw_json 里 source 字段，精算数据(amap/baidu)不硬过滤
                    # 通过 listing.missing_fields 里是否含"离线估算"来判断
                    is_offline = any(
                        "离线" in (f or "") for f in (listing.missing_fields or [])
                    )
                    if is_offline:
                        skip_stats["commute_far"] += 1
                        continue  # 离线估算超限 → 仍然硬过滤（精度低）
                    else:
                        commute_over_limit = True  # 精算超限 → 软标记，排到末位

            # 4. 硬性排除标签
            text = f"{listing.title} {listing.community} {listing.rental_type_tag or ''}"
            if any(ex in text for ex in requirement.hard_excludes):
                skip_stats["excluded"] += 1
                continue

            # 5. 合租排除
            if "shared" in requirement.rental_type.exclude:
                if listing.rental_type_tag and "合租" in listing.rental_type_tag:
                    skip_stats["shared"] += 1
                    continue

            filtered.append((listing, cost, commute, commute_over_limit))

        if any(skip_stats.values()):
            logger.info(f"过滤统计: {skip_stats}")

        if not filtered:
            return []

        # ===== 归一化基准 =====
        costs = [c.total for _, c, _, _ in filtered if c.total > 0]
        commutes = [s.best_duration_min for _, _, s, _ in filtered if s and s.best_duration_min > 0]
        areas = [l.area for l, _, _, _ in filtered if l.area]

        max_cost = max(costs) if costs else 1
        min_cost = min(costs) if costs else 0
        max_commute = max(commutes) if commutes else 1
        min_commute = min(commutes) if commutes else 0

        # ===== 评分 =====
        recommendations: list[Recommendation] = []
        for listing, cost, commute, commute_over_limit in filtered:
            score = self._compute_score(
                listing, cost, commute,
                max_cost, min_cost, max_commute, min_commute,
                requirement, sort_mode,
                commute_over_limit=commute_over_limit,
            )

            flags = []
            if listing.missing_fields:
                flags.append(f"信息不全: {'、'.join(listing.missing_fields)}")
            if commute_over_limit and commute:
                over = commute.best_duration_min - (requirement.commute.max_minutes or 0)
                flags.append(f"⚠️ 精算通勤超出限制 {over} 分钟（仍展示供参考）")

            recommendations.append(Recommendation(
                listing=listing,
                cost=cost,
                commute=commute,
                score=round(score, 3),
                reason=self._gen_reason(listing, cost, commute, requirement),
                flags=flags,
            ))

        # 排序
        recommendations.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(recommendations):
            r.rank = i + 1

        return recommendations

    def _compute_score(
        self,
        listing, cost, commute,
        max_cost, min_cost, max_commute, min_commute,
        req, sort_mode: SortMode,
        commute_over_limit: bool = False,
    ) -> float:
        """根据排序模式计算得分；精算超限直接给极低分排末位"""
        # 精算通勤超限 → 强制排末位（仍展示但用户能清楚看到排在后面）
        if commute_over_limit:
            return -1.0

        # 判断是否已精算（missing_fields 不含"离线估算"且有通勤数据）
        is_offline = any("离线" in (f or "") for f in (listing.missing_fields or []))
        is_precise = commute is not None and not is_offline
        # 精算房源整体加分 0.25，确保精算结果排在离线估算前面
        precise_bonus = 0.25 if is_precise else 0.0

        # 基础分量
        cost_score = 1 - (cost.total - min_cost) / max(1, max_cost - min_cost) if max_cost > min_cost else 1.0
        # v0.2.2.2: 没通勤数据 → 给最低分 (0)，让它排到最后；不再给"中间分 0.5"
        # 这样在"通勤优先"模式下，未测算房源不会混在中等通勤之间
        if commute and max_commute > min_commute:
            commute_score = 1 - (commute.best_duration_min - min_commute) / (max_commute - min_commute)
        elif commute:
            commute_score = 1.0  # 只有 1 条且有数据 → 满分
        else:
            commute_score = 0.0  # 没数据 → 0 分，必然沉底
        confidence = listing.confidence_score
        # 偏好匹配
        text = f"{listing.title} {listing.community} {listing.floor or ''} {listing.orientation or ''}"
        pref_hits = sum(1 for p in req.soft_preferences if p in text)
        pref_score = min(1.0, pref_hits / max(1, len(req.soft_preferences)))

        # 不同排序模式调整权重（主分量上限缩到 0.75，precise_bonus 最多占 0.25）
        if sort_mode == "价格":
            base = cost_score * 0.70 + commute_score * 0.10 + confidence * 0.10 + pref_score * 0.10
        elif sort_mode == "通勤":
            base = commute_score * 0.70 + cost_score * 0.10 + confidence * 0.10 + pref_score * 0.10
        elif sort_mode == "面积":
            area_score = min(1.0, (listing.area or 0) / 100)
            base = area_score * 0.60 + cost_score * 0.15 + commute_score * 0.15 + confidence * 0.10
        else:  # 综合
            base = cost_score * 0.30 + commute_score * 0.30 + confidence * 0.20 + pref_score * 0.20

        return base + precise_bonus

    def _gen_reason(
        self,
        listing: Listing,
        cost: CostBreakdown,
        commute: CommuteSummary | None,
        req: ParsedRequirement,
    ) -> str:
        parts = []
        if commute:
            parts.append(f"最快通勤 {commute.best_duration_min} 分钟")
        if req.price.total_cost_max:
            saving = req.price.total_cost_max - cost.total
            if saving > 0:
                parts.append(f"全包预算内省 ¥{saving}")
        if listing.area:
            parts.append(f"{listing.area}㎡")
        if listing.orientation:
            parts.append(f"朝{listing.orientation}")
        return " · ".join(parts) if parts else "符合基础需求"


ranker = Ranker()
