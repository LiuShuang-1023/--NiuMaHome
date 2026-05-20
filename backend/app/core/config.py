"""配置管理"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    """从 .env.local / .env 加载配置"""

    model_config = SettingsConfigDict(
        env_file=[ROOT_DIR / ".env.local", ROOT_DIR / ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== LLM 提供商选择 =====
    # 可选: deepseek (推荐，国内直连便宜) / claude (海外，需要梯子)
    LLM_PROVIDER: str = "deepseek"

    # DeepSeek 配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MODEL: str = "deepseek-chat"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # Anthropic Claude 配置
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"

    # ===== 地图 API =====
    AMAP_KEY: str = ""
    BAIDU_AK: str = ""
    BAIDU_SK: str = ""  # 百度SN签名校验方式所需，留空则不带sn（白名单方式可不填）
    TENCENT_KEY: str = ""  # 腾讯地图 WebService Key（LBS控制台申请）

    # ===== 平台 Cookie =====
    LIANJIA_COOKIE: str = ""
    BEIKE_COOKIE: str = ""
    ANJUKE_COOKIE: str = ""
    WUBA_COOKIE: str = ""  # 58同城

    # ===== 服务 =====
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:3000"

    # ===== 数据库 =====
    DATABASE_URL: str = "sqlite:///./data/niumahome.db"

    # ===== 日志 =====
    LOG_LEVEL: str = "INFO"


settings = Settings()
