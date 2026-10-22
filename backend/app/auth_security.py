"""认证入口的轻量限流。

刻意不依赖 Redis：单机内测阶段，进程内滑动窗口足够挡住脚本化的撞库/发码轰炸。
它的边界也要说清楚：

- 多 worker / 多实例时计数不共享，只能作为“单进程兜底”；
  正式多实例部署时，应在反向代理再加一层 `limit_req`，或换成 Redis。
- 只用于未登录入口；已登录用户的发布频控在 ratelimit.py。
"""
from __future__ import annotations

from collections import deque
import threading
import time

from fastapi import HTTPException, Request


_BUCKETS: dict[str, deque[float]] = {}
_LOCK = threading.Lock()

# 同一出口 IP 往往对应整个校园 NAT，所以 IP 额度必须比账号额度宽得多。
# 真正挡住“轰炸某个学号”的是 SUBJECT 档；IP 档只兜底脚本化批量请求。
# 30/小时对宿舍 NAT 太紧（一次招新就可能超过），因此放到 100。
REQUEST_CODE_IP = (100, 3600)
REQUEST_CODE_SUBJECT = (3, 3600)
REGISTER_IP = (200, 3600)
LOGIN_IP = (100, 600)
LOGIN_SUBJECT = (10, 600)


def _prune(bucket: deque[float], window_seconds: int, now: float) -> None:
    cutoff = now - window_seconds
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def allow(scope: str, value: str, limit: int, window_seconds: int) -> bool:
    """返回 True 表示放行；False 表示超限。"""
    key = f"{scope}:{value}"
    now = time.monotonic()
    with _LOCK:
        bucket = _BUCKETS.get(key)
        if bucket is None:
            bucket = deque()
            _BUCKETS[key] = bucket
        _prune(bucket, window_seconds, now)
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        # 防止被大量随机 key 撑爆内存：超过阈值时清掉已空的桶。
        if len(_BUCKETS) > 10_000:
            for stale_key in [k for k, v in _BUCKETS.items() if not v][:5_000]:
                _BUCKETS.pop(stale_key, None)
        return True


def enforce(scope: str, value: str, limit: int, window_seconds: int, message: str) -> None:
    if not allow(scope, value, limit, window_seconds):
        raise HTTPException(429, message, headers={"Retry-After": str(window_seconds)})


def client_ip(request: Request | None) -> str:
    # uvicorn 在 --proxy-headers 下会把可信反代传来的地址写进 request.client，
    # 这里不直接信任原始 X-Forwarded-For，避免被客户端伪造。
    # 直接调用路由函数的测试没有 Request，退回共享桶。
    if request is None or request.client is None:
        return "unknown"
    return request.client.host


def reset_all() -> None:
    """测试用：清空进程内计数。"""
    with _LOCK:
        _BUCKETS.clear()
