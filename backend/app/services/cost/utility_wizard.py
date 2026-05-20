"""智能水电估算模块 (v0.4)

根据用户生活习惯问卷，精算水/电/燃气月均费用，
结果可写回 CostBreakdown 覆盖默认值。

问卷设计原则：
  - 只问三类：空调使用习惯 / 洗澡习惯 / 做饭习惯
  - 每类 3-4 个选项，都有中文描述
  - 所有计算公式公开透明，notes 里写清楚

计算依据（广州地区 2025 均价）：
  - 电价：0.8 元/度（民用阶梯价均值）
  - 水价：7.5 元/吨（含污水处理）
  - 燃气：4.0 元/m³
"""
from typing import Literal, Optional
from dataclasses import dataclass

from app.models import CostBreakdown

# ── 空调习惯 ──────────────────────────────────────────────────
AcLevel = Literal["never", "mild", "moderate", "heavy"]
"""
never    = 基本不开，只用风扇                 → 电量: +0 度/月
mild     = 偶尔开（每天 <2h，仅睡觉）         → +60 度/月
moderate = 正常开（每天 4h，早晚）             → +120 度/月
heavy    = 长时间开（每天 8h+，几乎不关）       → +240 度/月
"""
AC_KWH: dict[AcLevel, int] = {
    "never":    0,
    "mild":     60,
    "moderate": 120,
    "heavy":    240,
}
AC_LABEL: dict[AcLevel, str] = {
    "never":    "基本不开（只用风扇）",
    "mild":     "偶尔开（睡觉时，每天 <2h）",
    "moderate": "正常开（早晚各 2h，每天约 4h）",
    "heavy":    "长时间开（每天 8h+，几乎不关）",
}

# ── 洗澡习惯 ──────────────────────────────────────────────────
ShowerLevel = Literal["quick", "normal", "long", "bath"]
"""
quick  = 短促冲澡 (<5 min)    → 水: 0.1 吨/次；电热水器: 1 度/次
normal = 正常淋浴 (10 min)    → 水: 0.2 吨/次；电热水器: 2 度/次
long   = 喜欢长时间淋浴(20min)→ 水: 0.4 吨/次；电热水器: 3 度/次
bath   = 经常泡澡              → 水: 0.5 吨/次；电热水器: 3.5 度/次
"""
SHOWER_WATER_PER_TIMES: dict[ShowerLevel, float] = {
    "quick":  0.1,
    "normal": 0.2,
    "long":   0.4,
    "bath":   0.5,
}
SHOWER_KWH_PER_TIME: dict[ShowerLevel, float] = {
    "quick":  1.0,
    "normal": 2.0,
    "long":   3.0,
    "bath":   3.5,
}
SHOWER_LABEL: dict[ShowerLevel, str] = {
    "quick":  "短促冲澡（5 分钟内）",
    "normal": "正常淋浴（约 10 分钟）",
    "long":   "喜欢长淋浴（20 分钟+）",
    "bath":   "经常泡澡",
}

# 默认每天洗一次澡（30 天）
SHOWER_TIMES_PER_MONTH = 30

# ── 做饭习惯 ──────────────────────────────────────────────────
CookLevel = Literal["never", "sometimes", "daily", "heavy"]
"""
never     = 基本不做饭（外卖/外食为主）  → 燃气: 0.5 m³/月；电: 5 度/月
sometimes = 偶尔做（每周 2-3 次）       → 燃气: 3 m³/月；电: 15 度/月
daily     = 每天做饭（1-2 餐）           → 燃气: 6 m³/月；电: 25 度/月
heavy     = 重度厨房爱好者（每天 3 餐）  → 燃气: 10 m³/月；电: 40 度/月
"""
COOK_GAS_M3: dict[CookLevel, float] = {
    "never":     0.5,
    "sometimes": 3.0,
    "daily":     6.0,
    "heavy":     10.0,
}
COOK_KWH: dict[CookLevel, int] = {
    "never":     5,
    "sometimes": 15,
    "daily":     25,
    "heavy":     40,
}
COOK_LABEL: dict[CookLevel, str] = {
    "never":     "基本不做饭（外卖/食堂为主）",
    "sometimes": "偶尔做饭（每周 2-3 次）",
    "daily":     "每天做饭（1-2 餐）",
    "heavy":     "重度厨房爱好者（每天 3 餐）",
}

# ── 电价/水价/气价 ────────────────────────────────────────────
ELEC_PRICE   = 0.8   # 元/度
WATER_PRICE  = 7.5   # 元/吨（含污水）
GAS_PRICE    = 4.0   # 元/m³

# ── 其他固定基础用电（非空调/热水/做饭）────────────────────────
BASE_KWH = 40   # 月均：照明 + 手机充电 + 电视 + 电脑 + 冰箱 + 洗衣机 = ~40 度


@dataclass
class UtilityWizardInput:
    """水电估算问卷输入"""
    ac_level: AcLevel = "moderate"           # 空调习惯
    shower_level: ShowerLevel = "normal"     # 洗澡习惯
    cook_level: CookLevel = "daily"          # 做饭习惯
    people_count: int = 1                    # 居住人数
    has_gas: bool = True                     # 有无燃气（纯电气化厨房时 = False）
    water_heater_type: Literal["gas", "electric", "central"] = "gas"
    # gas: 燃气热水器（热水计入燃气，不计电）
    # electric: 电热水器（热水计入电，不计燃气洗澡部分）
    # central: 集中供热/太阳能（热水免费，不计水电燃气）


@dataclass
class UtilityEstimate:
    """精算结果"""
    electricity: int     # 月电费（元）
    water: int           # 月水费（元）
    gas: int             # 月燃气费（元）
    total_utility: int   # 合计（元）
    # 详细分解（给用户看）
    electricity_kwh: float
    water_tons: float
    gas_m3: float
    notes: dict[str, str]
    # 与默认估算的差值（+/-）
    delta_vs_default: int


def compute_utility(inp: UtilityWizardInput, listing_area: float = 70.0) -> UtilityEstimate:
    """根据问卷习惯精算水电燃气"""
    people = max(1, inp.people_count)

    # ── 电 ──────────────────────────────────────────────────
    ac_kwh       = AC_KWH[inp.ac_level] * people
    cook_kwh     = COOK_KWH[inp.cook_level] * people
    base_kwh     = BASE_KWH * people

    shower_kwh = 0.0
    if inp.water_heater_type == "electric":
        shower_kwh = (
            SHOWER_KWH_PER_TIME[inp.shower_level]
            * SHOWER_TIMES_PER_MONTH * people
        )

    total_kwh = base_kwh + ac_kwh + cook_kwh + shower_kwh
    elec_fee  = int(round(total_kwh * ELEC_PRICE))

    # ── 水 ──────────────────────────────────────────────────
    shower_tons = (
        SHOWER_WATER_PER_TIMES[inp.shower_level]
        * SHOWER_TIMES_PER_MONTH * people
    )
    base_water_tons = 1.5 * people   # 饮用+烹饪+洗衣+洗脸等基础用水
    total_water_tons = base_water_tons + shower_tons
    water_fee = int(round(total_water_tons * WATER_PRICE))

    # ── 燃气 ──────────────────────────────────────────────────
    shower_gas_m3 = 0.0
    if inp.water_heater_type == "gas":
        # 燃气热水器：每次热水约 0.25 m³ 燃气
        shower_gas_m3 = 0.25 * SHOWER_TIMES_PER_MONTH * people

    cook_gas_m3 = COOK_GAS_M3[inp.cook_level] * people if inp.has_gas else 0.0
    total_gas_m3 = shower_gas_m3 + cook_gas_m3
    gas_fee = int(round(total_gas_m3 * GAS_PRICE)) if inp.has_gas else 0

    # ── 默认值（用于计算 delta）──────────────────────────────
    default_elec = int(100 * people * ELEC_PRICE)       # 默认 100度/人
    default_water = int(4 * people * WATER_PRICE)        # 默认 4吨/人
    default_gas  = int(5 * people * GAS_PRICE)           # 默认 5m³/人
    default_total = default_elec + default_water + default_gas

    total_utility = elec_fee + water_fee + gas_fee
    delta = total_utility - default_total

    # ── 生成 notes ──────────────────────────────────────────
    notes: dict[str, str] = {}

    elec_parts = [f"基础 {base_kwh:.0f}度"]
    if ac_kwh > 0:
        elec_parts.append(f"空调 {ac_kwh:.0f}度({AC_LABEL[inp.ac_level]})")
    if cook_kwh > 0:
        elec_parts.append(f"厨房 {cook_kwh:.0f}度")
    if shower_kwh > 0:
        elec_parts.append(f"电热水 {shower_kwh:.0f}度")
    notes["electricity"] = (
        f"{' + '.join(elec_parts)} = {total_kwh:.0f}度 × ¥{ELEC_PRICE}/度"
    )

    water_parts = [f"日常 {base_water_tons:.1f}吨"]
    water_parts.append(f"洗澡 {shower_tons:.1f}吨({SHOWER_LABEL[inp.shower_level]}×{SHOWER_TIMES_PER_MONTH}次)")
    notes["water"] = (
        f"{' + '.join(water_parts)} = {total_water_tons:.1f}吨 × ¥{WATER_PRICE}/吨"
    )

    if inp.has_gas:
        gas_parts = []
        if shower_gas_m3 > 0:
            gas_parts.append(f"热水 {shower_gas_m3:.1f}m³")
        if cook_gas_m3 > 0:
            gas_parts.append(f"做饭 {cook_gas_m3:.1f}m³({COOK_LABEL[inp.cook_level]})")
        notes["gas"] = (
            f"{' + '.join(gas_parts)} = {total_gas_m3:.1f}m³ × ¥{GAS_PRICE}/m³"
        )
    else:
        notes["gas"] = "纯电气化，无燃气"

    return UtilityEstimate(
        electricity=elec_fee,
        water=water_fee,
        gas=gas_fee,
        total_utility=total_utility,
        electricity_kwh=round(total_kwh, 1),
        water_tons=round(total_water_tons, 1),
        gas_m3=round(total_gas_m3, 1),
        notes=notes,
        delta_vs_default=delta,
    )
