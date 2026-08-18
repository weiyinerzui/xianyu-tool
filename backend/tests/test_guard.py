"""风控护栏测试：令牌桶限流 + 熔断器。"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.guard import (
    TokenBucket,
    Limiter,
    CircuitGuard,
    detect_risk_control,
    RiskControlError,
)


def test_token_bucket_basic():
    """令牌桶基本逻辑。"""
    bucket = TokenBucket(max_per_minute=2)
    # 初始有 2 个令牌
    assert bucket.acquire() is True
    assert bucket.acquire() is True
    # 用完后获取失败
    assert bucket.acquire() is False


def test_token_bucket_refill():
    """令牌桶随时间补充。"""
    bucket = TokenBucket(max_per_minute=60)
    bucket.tokens = 0
    bucket.last_refill = time.time() - 2  # 2 秒前
    # 2 秒应补充约 2 个令牌
    bucket._refill()
    assert bucket.tokens >= 1.0


def test_limiter_persistence():
    """限流器持久化。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "limiter.json"
        limiter1 = Limiter(path)
        # 消耗一个令牌
        assert limiter1.acquire("test") is True
        # 手动把令牌清零再保存，模拟"刚消耗完"的持久化状态
        limiter1._buckets["test"].tokens = 0.0
        limiter1._buckets["test"].last_refill = time.time()
        limiter1._save()
        # 重新加载，令牌数应为 0，获取失败
        limiter2 = Limiter(path)
        assert limiter2.acquire("test") is False


def test_limiter_multiple_namespaces():
    """不同命名空间独立限流。"""
    with tempfile.TemporaryDirectory() as tmp:
        limiter = Limiter(Path(tmp) / "limiter.json")
        assert limiter.acquire("ns1") is True
        # ns1 用完，但 ns2 仍可用
        assert limiter.acquire("ns1") is False
        assert limiter.acquire("ns2") is True


def test_circuit_guard_trip_and_check():
    """熔断器触发与检查。"""
    with tempfile.TemporaryDirectory() as tmp:
        guard = CircuitGuard(Path(tmp) / "circuit.json")
        assert guard.is_tripped("default") is False
        guard.trip("default")
        assert guard.is_tripped("default") is True
        assert guard.remaining("default") > 0


def test_circuit_guard_reset():
    """熔断器手动重置。"""
    with tempfile.TemporaryDirectory() as tmp:
        guard = CircuitGuard(Path(tmp) / "circuit.json")
        guard.trip("default")
        assert guard.is_tripped("default") is True
        guard.reset("default")
        assert guard.is_tripped("default") is False


def test_circuit_guard_persistence():
    """熔断器状态持久化。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "circuit.json"
        guard1 = CircuitGuard(path)
        guard1.trip("default")
        # 重新加载
        guard2 = CircuitGuard(path)
        assert guard2.is_tripped("default") is True


def test_detect_risk_control():
    """风控关键字检测。"""
    assert detect_risk_control('{"ret":["RGV587_ERROR"]}') is True
    assert detect_risk_control("FAIL_SYS_USER_VALIDATE") is True
    assert detect_risk_control("punish") is True
    assert detect_risk_control("x5sec") is True
    assert detect_risk_control('{"ret":["SUCCESS"]}') is False
    assert detect_risk_control("正常响应") is False


def test_risk_control_error():
    """异常可正常抛出。"""
    try:
        raise RiskControlError("test")
        assert False, "should have raised"
    except RiskControlError:
        pass


if __name__ == "__main__":
    test_token_bucket_basic()
    test_token_bucket_refill()
    test_limiter_persistence()
    test_limiter_multiple_namespaces()
    test_circuit_guard_trip_and_check()
    test_circuit_guard_reset()
    test_circuit_guard_persistence()
    test_detect_risk_control()
    test_risk_control_error()
    print("✅ test_guard: 全部通过")
