"""单连接 WebSocket 输入滑动窗口限流器。"""

import time
from collections import deque
from collections.abc import Callable


class WebSocketRateLimiter:
    """限制一个连接在指定时间窗口内可提交的命令数量。"""

    def __init__(
        self,
        limit: int,
        windowSeconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """保存显式限制并允许测试注入单调时钟。"""
        if limit < 1:
            raise ValueError("限流数量必须大于零")
        if windowSeconds <= 0:
            raise ValueError("限流窗口必须大于零")
        self._limit = limit
        self._windowSeconds = windowSeconds
        self._clock = clock
        self._acceptedAt: deque[float] = deque()

    def tryAcquire(self) -> bool:
        """允许窗口内请求并记录时间，超限时返回 False。"""
        now = self._clock()
        windowStart = now - self._windowSeconds
        while self._acceptedAt and self._acceptedAt[0] <= windowStart:
            self._acceptedAt.popleft()
        if len(self._acceptedAt) >= self._limit:
            return False
        self._acceptedAt.append(now)
        return True
