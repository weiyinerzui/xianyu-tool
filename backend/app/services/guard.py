"""风控护栏：令牌桶限流 + RGV587 熔断。

参考 goofish-cli core/limiter.py + core/guard.py 的设计：
- 令牌桶：限制写操作频率（默认 1 写/分钟），持久化到 JSON
- 熔断：命中 RGV587 风控后自动熔断 N 分钟，期间拒绝所有请求
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from app.config import settings


class RiskControlError(Exception):
    """风控触发异常。"""


@dataclass
class TokenBucket:
    """令牌桶限流器。

    每秒生成 rate/max_per_minute 个令牌，桶容量 = max_per_minute。
    acquire() 时如果有令牌则消耗一个并返回 True，否则返回 False。
    """
    max_per_minute: int = 1
    # 用 -1.0 作哨兵：区分"未设置"和"显式设为 0"
    tokens: float = -1.0
    last_refill: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.tokens < 0:  # 哨兵值 → 初始化为满桶
            self.tokens = float(self.max_per_minute)

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self.last_refill
        rate = self.max_per_minute / 60.0
        self.tokens = min(self.max_per_minute, self.tokens + elapsed * rate)
        self.last_refill = now

    def acquire(self) -> bool:
        """尝试获取一个令牌。成功返回 True，失败返回 False。"""
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "max_per_minute": self.max_per_minute,
            "tokens": self.tokens,
            "last_refill": self.last_refill,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenBucket":
        return cls(
            max_per_minute=data.get("max_per_minute", 1),
            tokens=data.get("tokens", 0.0),
            last_refill=data.get("last_refill", time.time()),
        )


class Limiter:
    """持久化限流器。

    按命名空间（如 "item.write"）维护独立的令牌桶。
    状态持久化到 JSON 文件，重启后恢复。
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = Path.home() / ".xianyu-ops" / "limiter.json"
        self._path = path
        self._buckets: dict[str, TokenBucket] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for ns, bucket_data in data.items():
                    self._buckets[ns] = TokenBucket.from_dict(bucket_data)
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {ns: b.to_dict() for ns, b in self._buckets.items()}
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def acquire(self, namespace: str) -> bool:
        """尝试获取命名空间的令牌。"""
        if namespace not in self._buckets:
            self._buckets[namespace] = TokenBucket(
                max_per_minute=settings.limiter_max_writes_per_minute
            )
        ok = self._buckets[namespace].acquire()
        self._save()
        return ok

    @contextmanager
    def acquire_or_wait(self, namespace: str, max_wait: float = 60.0) -> Generator[bool, None, None]:
        """获取令牌或等待，作为上下文管理器使用。

        用法：
            with limiter.acquire_or_wait("item.write"):
                # 执行写操作
        """
        import time as _time

        deadline = time.time() + max_wait
        while time.time() < deadline:
            if self.acquire(namespace):
                yield True
                return
            _time.sleep(1)
        # 超时仍放行（但记录），避免死锁
        yield False


class CircuitGuard:
    """熔断器：命中风控后熔断 N 分钟。

    状态持久化到 JSON，重启后恢复。
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            path = Path.home() / ".xianyu-ops" / "circuit.json"
        self._path = path
        self._tripped: dict[str, float] = {}  # namespace -> trip_timestamp
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._tripped = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._tripped), encoding="utf-8")

    def is_tripped(self, namespace: str = "default") -> bool:
        """检查是否处于熔断状态。"""
        trip_time = self._tripped.get(namespace)
        if trip_time is None:
            return False
        elapsed = time.time() - trip_time
        if elapsed >= settings.guard_circuit_break_minutes * 60:
            # 熔断过期，自动恢复
            del self._tripped[namespace]
            self._save()
            return False
        return True

    def trip(self, namespace: str = "default") -> None:
        """触发熔断。"""
        self._tripped[namespace] = time.time()
        self._save()

    def reset(self, namespace: str = "default") -> None:
        """手动重置熔断。"""
        self._tripped.pop(namespace, None)
        self._save()

    def remaining(self, namespace: str = "default") -> float:
        """返回剩余熔断秒数（未熔断返回 0）。"""
        trip_time = self._tripped.get(namespace)
        if trip_time is None:
            return 0.0
        elapsed = time.time() - trip_time
        total = settings.guard_circuit_break_minutes * 60
        return max(0.0, total - elapsed)


def detect_risk_control(response_text: str) -> bool:
    """检测响应体是否包含风控标记。

    参考 goofish-cli core/mtop.py 的风控关键字识别。
    """
    keywords = ["RGV587_ERROR", "FAIL_SYS_USER_VALIDATE", "FAIL_SYS_ILLEGAL_ACCESS",
                "punish", "x5sec", "bypass"]
    lowered = response_text.lower() if isinstance(response_text, str) else str(response_text).lower()
    return any(kw.lower() in lowered for kw in keywords)


# 模块级单例
_limiter: Limiter | None = None
_guard: CircuitGuard | None = None


def get_limiter() -> Limiter:
    global _limiter
    if _limiter is None:
        _limiter = Limiter()
    return _limiter


def get_guard() -> CircuitGuard:
    global _guard
    if _guard is None:
        _guard = CircuitGuard()
    return _guard
