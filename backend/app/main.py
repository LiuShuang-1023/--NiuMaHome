"""牛马归栏 - FastAPI 后端入口"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import chat, search, listings, commute, utility, agent, subsidy, housing
from app.core.config import settings
from app.services.storage import init_db, session_db
from app.services.storage.daily_cache import daily_cache
from app.services.storage.commute_store import commute_store


# ============================================================
# 后台清理任务（v0.3.0）
# ① 每 5 分钟扫一次过期 session，物理删除
# ② 每天 00:00 清理前日 daily_cache
# ============================================================
async def _periodic_cleanup():
    """后台定时清理任务（session TTL + 每日缓存清理）"""
    while True:
        try:
            await asyncio.sleep(5 * 60)  # 5 分钟检查一次
            # 清过期 session
            n = session_db.cleanup_expired()
            if n > 0:
                logger.info(f"🧹 自动清理了 {n} 个过期 session")

            # 每日维护：daily_cache 清旧日缓存 + commute_store 更新7日均值
            # 用 needs_daily_update() 检查今天是否已执行，防止多次触发
            daily_cache._cleanup_old_dates()  # 每次循环都检查，清理前日缓存（幂等）
            if commute_store.needs_daily_update():
                result = commute_store.daily_update()
                logger.info(f"🗓️ 每日通勤均值更新完成: {result}")

        except asyncio.CancelledError:
            logger.info("后台清理任务收到取消信号")
            raise
        except Exception as e:
            logger.warning(f"后台清理异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info("🐂 牛马归栏后端启动中...")
    logger.info(f"日志级别: {settings.LOG_LEVEL}")
    logger.info(f"LLM 提供商: {settings.LLM_PROVIDER}")
    logger.info(f"高德地图: {'✅ 已配置' if settings.AMAP_KEY else '❌ 未配置'}")
    logger.info(f"百度地图: {'✅ 已配置' if settings.BAIDU_AK else '❌ 未配置'}")

    # v0.3.0: 初始化 SQLite + 启动后台清理任务
    init_db()
    # daily_cache 在 import 时自动清理旧日缓存（已在 __init__ 里调用）
    cache_stats = daily_cache.stats()
    logger.info(f"📦 今日缓存: 房源 {cache_stats['listings']} 条 | geocode {cache_stats['geocode']} 条")
    store_stats = commute_store.stats()
    logger.info(f"🧠 通勤知识库: 精算记录 {store_stats['precise_records']} 条 | 基准路线 {store_stats['baseline_routes']} 条")
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    logger.info("✅ SQLite 已就绪，后台清理任务已启动（5 分钟周期，TTL 30 分钟）")

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("👋 牛马归栏后端关闭")


app = FastAPI(
    title="牛马归栏 API",
    description="打工人的 AI 租房助理",
    version="0.9.2",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(chat.router, prefix="/api/chat", tags=["AI 对话"])
app.include_router(search.router, prefix="/api/search", tags=["搜索任务"])
app.include_router(listings.router, prefix="/api/listings", tags=["房源"])
app.include_router(commute.router, prefix="/api/commute", tags=["通勤"])
app.include_router(utility.router, prefix="/api/utility", tags=["水电估算"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent小助手"])
app.include_router(subsidy.router, prefix="/api/subsidy", tags=["房补政策"])
app.include_router(housing.router, prefix="/api/housing", tags=["保障房政策"])


@app.get("/")
async def root():
    return {
        "name": "牛马归栏 NiuMaHome",
        "version": "0.9.2",
        "status": "running",
        "slogan": "打工人，回家路上少操点心",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
