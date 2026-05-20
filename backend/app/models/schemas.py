"""核心数据模型 - Pydantic"""
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field


# =============== 需求解析 ===============

class GeoPoint(BaseModel):
    lng: Optional[float] = None
    lat: Optional[float] = None


class Destination(BaseModel):
    """通勤目的地"""
    city: str = ""
    district: str = ""
    landmark: str = ""
    address: str = ""
    geo: GeoPoint = Field(default_factory=GeoPoint)


class CommuteRequirement(BaseModel):
    """通勤要求"""
    max_minutes: int = 30
    modes: list[Literal["transit", "riding", "walking", "driving"]] = Field(
        default_factory=lambda: ["transit", "riding", "walking"]
    )
    maps: list[Literal["amap", "baidu", "tencent"]] = Field(
        default_factory=lambda: ["amap", "baidu"]
    )


class RentalType(BaseModel):
    """居住形态"""
    include: list[str] = Field(default_factory=list)  # entire_1b1b, single_room, ...
    exclude: list[str] = Field(default_factory=list)  # shared, urban_village, ...


class PriceRange(BaseModel):
    """价格区间（月租，单位 元）"""
    base_rent_max: Optional[int] = None
    base_rent_min: Optional[int] = None
    total_cost_max: Optional[int] = None
    total_cost_min: Optional[int] = None


class ParsedRequirement(BaseModel):
    """AI 解析后的结构化需求"""
    destination: Destination = Field(default_factory=Destination)
    commute: CommuteRequirement = Field(default_factory=CommuteRequirement)
    rental_type: RentalType = Field(default_factory=RentalType)
    price: PriceRange = Field(default_factory=PriceRange)
    soft_preferences: list[str] = Field(default_factory=list)
    hard_excludes: list[str] = Field(default_factory=list)
    raw_text: str = ""


# =============== 对话 ===============

class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    current_requirement: Optional[ParsedRequirement] = None


class ChatResponse(BaseModel):
    """AI 对话响应"""
    reply: str
    requirement: Optional[ParsedRequirement] = None
    is_ready: bool = False  # 需求是否完整、可触发搜索
    clarifying_questions: list[str] = Field(default_factory=list)


# =============== 房源 ===============

class Platform(str, Enum):
    LIANJIA = "lianjia"
    BEIKE = "beike"
    ANJUKE = "anjuke"
    WUBA = "wuba"          # 58同城
    ZIROOM = "ziroom"
    XIANYU = "xianyu"
    XIAOHONGSHU = "xiaohongshu"


class Listing(BaseModel):
    """房源"""
    id: str
    platform: Platform
    platform_id: str
    url: str
    title: str

    # 价格
    price_base: int  # 基础月租
    price_total: Optional[int] = None  # 真实月支出（计算后）

    # 户型信息
    area: Optional[float] = None
    layout: Optional[str] = None  # "1室1厅"
    floor: Optional[str] = None  # "中楼层/共18层"
    has_elevator: Optional[bool] = None
    orientation: Optional[str] = None
    rental_type_tag: Optional[str] = None  # "整租" / "合租" / "单间"

    # 位置
    address: str = ""
    community: str = ""  # 小区名
    geo_lng: Optional[float] = None
    geo_lat: Optional[float] = None

    # 媒体
    images: list[str] = Field(default_factory=list)

    # 元数据
    raw_data: dict = Field(default_factory=dict)
    confidence_score: float = 1.0
    missing_fields: list[str] = Field(default_factory=list)


# =============== 通勤 ===============

class CommuteMode(str, Enum):
    TRANSIT = "transit"
    RIDING = "riding"
    WALKING = "walking"
    DRIVING = "driving"


class MapProvider(str, Enum):
    AMAP = "amap"
    BAIDU = "baidu"
    TENCENT = "tencent"
    STABLE_BASELINE = "stable_baseline"   # 已固化的稳定基准，不调 API


class CommuteResult(BaseModel):
    """单次通勤计算结果"""
    map_provider: MapProvider
    mode: CommuteMode
    duration_min: int
    distance_km: float
    direction: Literal["home_to_work", "work_to_home"] = "home_to_work"
    nearest_metro: Optional[str] = None
    metro_walk_min: Optional[int] = None
    metro_distance_m: Optional[int] = None
    transfers: Optional[int] = None  # 换乘次数
    raw_response: dict = Field(default_factory=dict)


class CommuteSummary(BaseModel):
    """房源完整通勤数据（多地图 × 多模式 × 双向）"""
    listing_id: str
    destination_address: str
    results: list[CommuteResult]

    # 汇总指标（用于排序）
    best_duration_min: int = 0
    avg_transit_min: Optional[int] = None
    nearest_metro: Optional[str] = None
    metro_walk_min: Optional[int] = None


# =============== 成本 ===============

class CostBreakdown(BaseModel):
    """真实月支出明细 + 计算依据"""
    base_rent: int = 0          # 基础房租
    property_fee: int = 0        # 物业费
    water: int = 0              # 水
    electricity: int = 0         # 电
    gas: int = 0                # 燃气
    internet: int = 0           # 网络
    agency_fee_monthly: int = 0  # 中介费摊销
    deposit_cost: int = 0       # 押金资金占用
    other: int = 0              # 其他

    # === 计算依据（让用户看清是怎么算出来的） ===
    notes: dict[str, str] = Field(default_factory=dict)
    # 例如:
    # {
    #   "property_fee": "按 70㎡ × 2元/㎡/月",
    #   "water": "按 4 吨/月 × 7.5 元/吨",
    #   "electricity": "按 100 度/月 × 0.8 元/度",
    #   "gas": "按 5 m³/月 × 4 元/m³",
    #   "internet": "100M 宽带，60元/月",
    #   "agency_fee_monthly": "中介费 1500元，按12个月摊销",
    #   "deposit_cost": "押金 3000元，按年化3%/12月计资金占用"
    # }

    @computed_field
    @property
    def total(self) -> int:
        return (self.base_rent + self.property_fee + self.water + self.electricity
                + self.gas + self.internet + self.agency_fee_monthly
                + self.deposit_cost + self.other)


# =============== AI 房源点评 ===============

class ListingReview(BaseModel):
    """AI 对单套房源的点评"""
    score: float = 0.0  # 0-10 综合评分
    summary: str = ""   # 一句话总结
    pros: list[str] = Field(default_factory=list)  # 优点列表
    cons: list[str] = Field(default_factory=list)  # 缺点/风险列表
    tags: list[str] = Field(default_factory=list)  # 关键标签，如「性价比高」「通勤友好」
    generated_at: str = ""  # ISO 时间戳
    model: str = ""         # 生成模型名


# =============== 推荐 ===============

class Recommendation(BaseModel):
    """推荐项"""
    listing: Listing
    cost: CostBreakdown
    commute: Optional[CommuteSummary] = None
    score: float = 0.0
    rank: int = 0
    reason: str = ""
    flags: list[str] = Field(default_factory=list)  # 警告标记，如"信息不全"
    ai_review: Optional[ListingReview] = None  # AI 点评（按需生成，列表搜索默认空）
