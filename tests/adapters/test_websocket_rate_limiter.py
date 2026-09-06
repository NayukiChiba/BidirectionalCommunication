"""WebSocket 单连接滑动窗口限流测试。"""

from src.adapters import WebSocketRateLimiter


class FakeClock:
    """无需 sleep 即可推进的测试单调时钟。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_rejects_only_requests_over_current_window() -> None:
    """窗口内超限应拒绝，时间推进后容量应自动恢复。"""
    clock = FakeClock()
    limiter = WebSocketRateLimiter(limit=2, windowSeconds=10, clock=clock)

    assert limiter.tryAcquire() is True
    assert limiter.tryAcquire() is True
    assert limiter.tryAcquire() is False

    clock.now = 10.0

    assert limiter.tryAcquire() is True


def test_rate_limiter_configuration_must_be_positive() -> None:
    """无效限制应在创建时明确失败。"""
    for limit, windowSeconds in ((0, 1.0), (1, 0.0)):
        try:
            WebSocketRateLimiter(limit, windowSeconds)
        except ValueError:
            continue
        raise AssertionError("无效限流配置没有被拒绝")
