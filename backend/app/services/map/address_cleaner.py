"""地址清洗工具

针对链家/贝壳的小区名做归一化，提高 geocode 命中率。

实测高德/百度 geocode 失败的常见情况：
1. 含品牌前缀: "独栋·MI 米谷公寓" → 应清洗为 "MI 米谷公寓"
2. 含分店后缀: "优居 汉溪长隆店" → "优居 汉溪长隆"
3. 含特殊符号: "·" "•" "/" → 应替换为空格
4. 公寓品牌全名: "MI米谷公寓-番禺天河城店" → "米谷公寓"

策略：
- Layer 1 原始地址（万一能命中）
- Layer 2 清洗后的小区名
- Layer 3 商圈/landmark（用户指定的目的地附近）
- Layer 4 区中心点（最后兜底，警告"位置粗略"）

v0.2.1.1: 加坐标合理性验证（防止百度把小区名 fuzzy match 到几十公里外）
"""
import math
import re
from typing import Optional

# 主要城市的中心点坐标（WGS84/GCJ02 通用作为粗略中心，BD09 略偏不影响判断）
# 用于检验 geocode 返回的坐标是否还在该城市范围内
CITY_CENTERS: dict[str, tuple[float, float]] = {
    "广州": (113.264385, 23.129112),
    "深圳": (114.057868, 22.543099),
    "北京": (116.407526, 39.904030),
    "上海": (121.473701, 31.230416),
    "杭州": (120.155070, 30.274085),
    "成都": (104.066301, 30.572961),
    "南京": (118.796877, 32.060255),
    "武汉": (114.305393, 30.593099),
    "西安": (108.940175, 34.341568),
    "重庆": (106.551556, 29.563009),
    "苏州": (120.585315, 31.298886),
    "长沙": (112.938814, 28.228209),
    "天津": (117.190182, 39.125596),
    "郑州": (113.625368, 34.746599),
    "厦门": (118.089425, 24.479833),
    "青岛": (120.355173, 36.082982),
    "合肥": (117.283042, 31.861191),
    "佛山": (113.121416, 23.021548),
    "东莞": (113.751756, 23.020536),
    "宁波": (121.549792, 29.868388),
}

# 城市半径阈值（公里）：geocode 返回坐标距 city 中心超过这个距离视为错误
DEFAULT_CITY_RADIUS_KM = 60  # 大城市跨度通常 50-80km，60 比较稳

# 需要去除的前缀（带 · 或 • 分隔）
BRAND_PREFIXES = [
    "独栋", "整租", "合租", "单间",
    "公寓", "酒店式", "短租",
]

# 需要去除的后缀（分店标识）
STORE_SUFFIXES = [
    "店", "号店", "公馆", "馆",
]

# 需要替换为空格的字符
NOISE_CHARS = ["·", "•", "・", "‧", "／", "/", "(", ")", "（", "）", "[", "]", "【", "】"]


def haversine_km(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """计算两点经纬度的球面距离（公里）

    用于验证 geocode 返回坐标是否在合理范围。
    p1, p2: (lng, lat)
    """
    lng1, lat1 = p1
    lng2, lat2 = p2
    R = 6371.0  # 地球半径
    rad = math.pi / 180.0
    dlat = (lat2 - lat1) * rad
    dlng = (lng2 - lng1) * rad
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlng / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def is_coord_in_city(
    coord: tuple[float, float],
    city: str,
    radius_km: float = DEFAULT_CITY_RADIUS_KM,
) -> bool:
    """坐标是否在指定城市范围内

    用于过滤 geocode 错误命中（如把"广州 MI米谷公寓" fuzzy 匹配到"白云区"）

    返回 True 表示坐标可信；False 表示离谱，应当 fallback 到下一级候选。
    未知城市默认 True（不做验证，避免误杀）。
    """
    if not city:
        return True
    center = CITY_CENTERS.get(city)
    if not center:
        return True  # 未收录的城市不做验证
    distance = haversine_km(coord, center)
    return distance <= radius_km


def clean_community_name(name: str) -> str:
    """清洗小区名

    >>> clean_community_name("独栋·MI 米谷公寓 番禺天河城店")
    'MI米谷公寓'
    >>> clean_community_name("优居 汉溪长隆店")
    '优居'
    >>> clean_community_name("招商城市主场")
    '招商城市主场'
    """
    if not name:
        return ""

    s = name.strip()

    # 1. 替换噪声字符为空格
    for ch in NOISE_CHARS:
        s = s.replace(ch, " ")

    # 2. 去除"独栋·" "整租·"前缀
    for prefix in BRAND_PREFIXES:
        # 形如 "独栋 MI 米谷公寓" → "MI 米谷公寓"
        if s.startswith(prefix + " ") or s.startswith(prefix):
            s = s[len(prefix):].lstrip(" ·•")

    # 3. 去除"xxx店"分店后缀
    # 匹配：空格 + 任意中文 + 店（出现在最后）
    # 例如 "MI米谷公寓 番禺天河城店" → "MI米谷公寓"
    s = re.sub(r"\s+[\u4e00-\u9fa5A-Za-z0-9]+店$", "", s)

    # 4. 把多个空格压缩成 1 个
    s = re.sub(r"\s+", " ", s).strip()

    return s


def extract_community_from_title(title: str) -> str:
    """从房源标题中兜底提取小区名（v0.2.2.5）

    链家/贝壳标题的常见格式：
    - "整租·华南碧桂园翠山蓝天苑 1室0厅 朝东南"
    - "独栋·海上明月公寓 南沙店 【毕业季..."
    - "合租·阳光花园 主卧"
    - "整租·万科金域蓝湾 3室2厅"
    - "独栋·百合社区 人和地铁站店 步梯..."

    策略：取第一个 "·" 后到第一个空格之前的部分

    >>> extract_community_from_title("整租·华南碧桂园翠山蓝天苑 1室0厅")
    '华南碧桂园翠山蓝天苑'
    >>> extract_community_from_title("独栋·海上明月公寓 南沙店 【毕业季..")
    '海上明月公寓'
    >>> extract_community_from_title("某无前缀小区 1室1厅")
    '某无前缀小区'
    """
    if not title:
        return ""
    s = title.strip()

    # 1. 如有"·"分隔，取后半部分（去掉品牌前缀）
    for sep in ["·", "•", "・"]:
        if sep in s:
            s = s.split(sep, 1)[1]
            break

    # 2. 取第一个空格之前
    s = s.split(" ", 1)[0].split("\u3000", 1)[0]

    # 3. 去掉常见尾缀（"店"等）
    s = re.sub(r"[\u4e00-\u9fa5A-Za-z0-9]+店$", "", s) or s.rstrip("店")

    return s.strip()


def build_geocode_candidates(
    raw_community: str,
    address: str = "",
    city: str = "",
    district: str = "",
    landmark: str = "",
) -> list[str]:
    """构建 geocode 候选地址列表（按优先级）

    返回的列表会被依次尝试，第一个命中即停止。

    Args:
        raw_community: 原始小区名（如 "独栋·MI 米谷公寓 番禺天河城店"）
        address: 详细地址（如有）
        city: 城市
        district: 区
        landmark: 用户的目的地地标（用于fallback 到附近区域）

    Returns:
        候选地址字符串列表
    """
    candidates: list[str] = []

    cleaned = clean_community_name(raw_community)

    # 一组：精确地址（最优）
    if address and address != raw_community:
        candidates.append(_compose(city, district, address))

    # 二组：原始小区名（万一品牌词高德也认）
    if raw_community:
        candidates.append(_compose(city, district, raw_community))

    # 三组：清洗后的小区名
    if cleaned and cleaned != raw_community:
        candidates.append(_compose(city, district, cleaned))

    # 四组：清洗后小区名（不带 district，全市搜索）
    if cleaned and district:
        candidates.append(_compose(city, "", cleaned))

    # 五组：district + 清洗后小区名（极简）
    if cleaned and district:
        candidates.append(f"{district}{cleaned}")

    # 去重保序
    seen = set()
    uniq = []
    for c in candidates:
        c2 = c.strip()
        if c2 and c2 not in seen:
            seen.add(c2)
            uniq.append(c2)
    return uniq


def _compose(city: str, district: str, addr: str) -> str:
    """组合 city + district + addr，避免重复"""
    parts = []
    if city:
        parts.append(city)
    if district and district not in (city or ""):
        # 避免 "广州广州" 这种
        if not addr.startswith(district):
            parts.append(district)
    if addr:
        parts.append(addr)
    return "".join(parts)


def fallback_landmark_address(
    landmark: str,
    city: str = "",
    district: str = "",
) -> Optional[str]:
    """实在 geocode 不到时，用 landmark 兜底

    返回类似 "广州番禺南村万博" 的字符串，作为该房源的"粗略位置"。
    """
    if not landmark:
        return None
    parts = []
    if city:
        parts.append(city)
    if district:
        parts.append(district)
    parts.append(landmark)
    return "".join(parts)
