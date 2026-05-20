"""真实月支出测算引擎

每一项成本都附带计算依据 (notes)，让用户看到单价×用量。

v0.7: 详情页数据写回
  - deposit_type (押付方式)  → 精确押金月数 + 付款月数
  - water_type   (用水类型)  → 民水/商水 不同单价
  - electricity_type         → 民电/商电 不同单价
"""
from typing import Optional
from app.models import CostBreakdown, Listing


# =========== 单价配置（基于2025 广州地区均值） ===========

# 物业费：按面积估算（元/㎡/月）
PROPERTY_FEE_PER_SQM = 2.0

# 水费（民水/商水双价）
WATER_PRICE_RESIDENTIAL = 7.5   # 民水：元/吨（含污水处理费）
WATER_PRICE_COMMERCIAL  = 13.0  # 商水：元/吨（广州商用水价约 13元/吨）
WATER_PRICE_PER_TON = 7.5       # 默认（兼容旧逻辑）
WATER_TONS_PER_PERSON = 4       # 月用水：单人 4 吨

# 电费（民电/商电双价）
ELECTRICITY_PRICE_RESIDENTIAL = 0.8    # 民电：元/度（阶梯电价均值）
ELECTRICITY_PRICE_COMMERCIAL  = 1.2    # 商电：元/度（广州商业用电约 1.2元/度）
ELECTRICITY_PRICE = 0.8                # 默认（兼容旧逻辑）
ELECTRICITY_KWH_NORMAL = 100   # 正常月度数（春秋）
ELECTRICITY_KWH_HEAVY = 180    # 高峰月度数（夏冬开空调）

# 燃气
GAS_PRICE_PER_M3 = 4.0         # 元/m³
GAS_M3_PER_MONTH = 5           # 单人月均 5 m³

# 网络
INTERNET_PRICE = 60            # 100M 宽带均价

# 中介费/押金
AGENCY_FEE_RATE = 0.5          # 中介费 = 半个月租金
DEPOSIT_MONTHS_DEFAULT = 1     # 默认押 1 付 1
DEPOSIT_INTEREST_ANNUAL = 0.03 # 资金占用按年化 3%

# 押付方式解析映射（deposit_type 文本 → 押金月数）
# 覆盖常见写法：押一付一 / 押1付1 / 押一付三 / 押二付三 / 押二付一 / 押三付三
_DEPOSIT_ZH_NUM = {'一': 1, '二': 2, '三': 3, '六': 6, '十二': 12, '0': 0}
import re as _re

def _parse_deposit_months(deposit_type: Optional[str]) -> Optional[int]:
    """从押付方式文本解析押金月数，返回 None 表示未识别"""
    if not deposit_type:
        return None
    # 数字写法：押1付1 / 押2付3
    m = _re.search(r'押(\d+)', deposit_type)
    if m:
        return int(m.group(1))
    # 汉字写法：押一付三 / 押二付一
    m = _re.search(r'押([一二三六])', deposit_type)
    if m:
        return _DEPOSIT_ZH_NUM.get(m.group(1), 1)
    return None


class CostEngine:
    """真实成本计算"""

    def compute(
        self,
        listing: Listing,
        rental_period: int = 12,
        with_agency: bool = True,
        # 用户生活习惯（v0.2 接入用户档案）
        electricity_heavy: bool = False,  # 是否高耗电（开空调）
        people_count: int = 1,             # 居住人数
        # v0.7: 详情页增量字段（写回cost engine）
        deposit_type: Optional[str] = None,        # 押付方式，如 "押一付三"
        water_type: Optional[str] = None,           # 用水类型，如 "民水" / "商水"
        electricity_type: Optional[str] = None,     # 用电类型，如 "民电" / "商电"
    ) -> CostBreakdown:
        """计算单条房源的真实月支出（含详细依据）"""
        breakdown = CostBreakdown()
        notes: dict[str, str] = {}

        # ===== 1. 基础房租 =====
        breakdown.base_rent = listing.price_base or 0
        # 区间价格说明
        price_range = listing.raw_data.get("price_range") if listing.raw_data else None
        if price_range:
            notes["base_rent"] = f"列表区间 ¥{price_range}/月，取下限"

        # ===== 2. 物业费 =====
        if listing.area:
            breakdown.property_fee = int(listing.area * PROPERTY_FEE_PER_SQM)
            notes["property_fee"] = (
                f"按 {listing.area}㎡ × {PROPERTY_FEE_PER_SQM}元/㎡/月"
            )
        else:
            breakdown.property_fee = 50
            notes["property_fee"] = "面积未知，按 50元/月 估算"

        # ===== 3. 水费（民水/商水精准单价）=====
        water_tons = WATER_TONS_PER_PERSON * people_count
        if water_type and "商" in water_type:
            water_price = WATER_PRICE_COMMERCIAL
            water_tag = f"商水 {water_price}元/吨"
        elif water_type and "民" in water_type:
            water_price = WATER_PRICE_RESIDENTIAL
            water_tag = f"民水 {water_price}元/吨"
        else:
            water_price = WATER_PRICE_PER_TON
            water_tag = f"默认 {water_price}元/吨"
        breakdown.water = int(water_tons * water_price)
        notes["water"] = (
            f"按 {people_count}人 × {WATER_TONS_PER_PERSON}吨/月 × {water_tag}"
            + (f"（{water_type}）" if water_type else "（水价未知，按默认估算）")
        )

        # ===== 4. 电费（民电/商电精准单价）=====
        kwh = ELECTRICITY_KWH_HEAVY if electricity_heavy else ELECTRICITY_KWH_NORMAL
        kwh = kwh * people_count
        if electricity_type and "商" in electricity_type:
            elec_price = ELECTRICITY_PRICE_COMMERCIAL
            elec_tag = f"商电 {elec_price}元/度"
        elif electricity_type and "民" in electricity_type:
            elec_price = ELECTRICITY_PRICE_RESIDENTIAL
            elec_tag = f"民电 {elec_price}元/度"
        else:
            elec_price = ELECTRICITY_PRICE
            elec_tag = f"默认 {elec_price}元/度"
        kwh_label = "高耗电(开空调)" if electricity_heavy else "正常"
        breakdown.electricity = int(kwh * elec_price)
        notes["electricity"] = (
            f"按 {kwh_label} {kwh}度/月 × {elec_tag}"
            + (f"（{electricity_type}）" if electricity_type else "（电价未知，按默认估算）")
        )

        # ===== 5. 燃气 =====
        gas_m3 = GAS_M3_PER_MONTH * people_count
        breakdown.gas = int(gas_m3 * GAS_PRICE_PER_M3)
        notes["gas"] = (
            f"按 {people_count}人 × {GAS_M3_PER_MONTH}m³/月 × {GAS_PRICE_PER_M3}元/m³"
        )

        # ===== 6. 网络费 =====
        breakdown.internet = INTERNET_PRICE
        notes["internet"] = f"100M宽带 {INTERNET_PRICE}元/月（合租可均摊）"

        # ===== 7. 中介费摊销 =====
        if with_agency and listing.platform.value in ("lianjia", "beike", "anjuke"):
            agency_total = int(breakdown.base_rent * AGENCY_FEE_RATE)
            breakdown.agency_fee_monthly = agency_total // rental_period
            notes["agency_fee_monthly"] = (
                f"中介费 ¥{agency_total} (半月租金)，按 {rental_period} 个月摊销"
            )
        else:
            notes["agency_fee_monthly"] = "公寓直租，无中介费"

        # ===== 8. 押金资金占用（押付方式精算）=====
        deposit_months = _parse_deposit_months(deposit_type) or DEPOSIT_MONTHS_DEFAULT
        deposit = breakdown.base_rent * deposit_months
        breakdown.deposit_cost = max(1, int(deposit * DEPOSIT_INTEREST_ANNUAL / 12))
        deposit_label = deposit_type if deposit_type else f"默认押{deposit_months}付X"
        notes["deposit_cost"] = (
            f"{deposit_label}：押金 ¥{deposit}（{deposit_months}个月）× 年化 {DEPOSIT_INTEREST_ANNUAL*100:.1f}% ÷ 12 月"
        )

        breakdown.notes = notes
        return breakdown


cost_engine = CostEngine()
