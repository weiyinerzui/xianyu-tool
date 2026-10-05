"""应用配置。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    database_url: str = "sqlite+aiosqlite:///./xianyu_ops.db"

    # 采集层
    crawler_request_delay_min: float = 3.0
    crawler_request_delay_max: float = 8.0
    crawler_max_consecutive_failures: int = 5
    crawler_cooldown_minutes: int = 30
    crawler_search_max_pages: int = 3

    # 浏览器反指纹（P0-1）
    # 闲鱼对 headless Chromium 有指纹识别，会直接返回「非法访问」页。
    # 实测 headless=False + xvfb 可绕过该层拦截，因此默认关闭 headless。
    crawler_headless: bool = False
    # Linux 无显示器（CI / 服务器）时自动套 xvfb-run 启动
    crawler_auto_xvfb: bool = True
    # 持久化浏览器 profile 目录：复用登录态与设备指纹，降低风控命中率
    crawler_user_data_dir: str = ""
    # 代理池（逗号分隔，如 http://127.0.0.1:7890,http://127.0.0.1:7891）
    crawler_proxies: str = ""

    # 风控护栏
    limiter_max_writes_per_minute: int = 1
    guard_circuit_break_minutes: int = 10

    # 评分权重
    weight_want_velocity: float = 0.35
    weight_price_advantage: float = 0.25
    weight_engagement_rate: float = 0.20
    weight_freshness: float = 0.10
    weight_competition: float = 0.10

    # 登录态
    cookies_path: str = str(Path.home() / ".xianyu-ops" / "cookies.json")

    class Config:
        env_file = ".env"
        env_prefix = "XIANYU_OPS_"


settings = Settings()
