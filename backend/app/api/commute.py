"""通勤测算 API"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.models import CommuteMode, CommuteSummary
from app.services.map.engine import commute_engine

router = APIRouter()


class CommuteRequest(BaseModel):
    origin: str
    destination: str
    city: str
    modes: list[CommuteMode] | None = None
    use_amap: bool = True
    use_baidu: bool = True


@router.post("/compute", response_model=CommuteSummary | None)
async def compute_commute(req: CommuteRequest):
    """测算单次通勤（多地图×多模式）"""
    return await commute_engine.compute(
        origin_address=req.origin,
        dest_address=req.destination,
        city=req.city,
        modes=req.modes,
        use_amap=req.use_amap,
        use_baidu=req.use_baidu,
    )
