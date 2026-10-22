"""20 人并发基础链路压测（不是单元测试，文件名故意不以 test_ 开头）。

它回答的不是「代码逻辑对不对」（那是 unittest 的事），而是：**20 个同学同时
注册、发动态、共鸣、回声、发起并接受聊天时，单进程 SQLite 后端会不会超时、
锁死或返回 5xx。**

启动被测服务（另一个终端）：

    cd backend
    set MOUKE_DB_PATH=%TEMP%\\mouke-load.db
    set MOUKE_UPLOAD_DIR=%TEMP%\\mouke-load-uploads
    set MOUKE_DEV_EMAIL_CODES=1
    set MOUKE_CODE_SECRET=load-test-secret-at-least-32-characters
    set MOUKE_ALIAS_SECRET=another-load-test-secret-32-characters
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010

再运行：

    .venv\\Scripts\\python.exe tests\\loadtest_20users.py --base-url http://127.0.0.1:8010

注意：认证限流按 IP 计数，同一服务进程只能跑一轮（20 个 request-code 已接近
30/小时的 IP 上限）。重跑请重启服务或换一个临时库+新进程。

判读标准：
- 所有预期请求都落在 2xx；
- p95 在秒级以内（本机 SQLite，注册含 PBKDF2 约 0.2-0.4s，属正常）；
- 没有 500/503，没有 SQLite "database is locked"。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter, defaultdict

import httpx


class Stats:
    def __init__(self) -> None:
        self.durations: dict[tuple[str, str], list[float]] = defaultdict(list)
        self.statuses: Counter[tuple[str, int]] = Counter()
        self.failures: list[str] = []

    def record(self, phase: str, name: str, elapsed: float, response: httpx.Response, allowed: tuple[int, ...]) -> None:
        self.durations[(phase, name)].append(elapsed)
        self.statuses[(name, response.status_code)] += 1
        if response.status_code not in allowed:
            body = response.text[:200].replace("\n", " ")
            self.failures.append(f"{name} -> {response.status_code}: {body}")

    def percentile(self, values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]


async def call(
    client: httpx.AsyncClient,
    stats: Stats,
    phase: str,
    name: str,
    method: str,
    path: str,
    allowed: tuple[int, ...] = (200,),
    **kwargs,
) -> httpx.Response:
    started = time.perf_counter()
    response = await client.request(method, path, **kwargs)
    stats.record(phase, name, time.perf_counter() - started, response, allowed)
    return response


async def main() -> int:
    parser = argparse.ArgumentParser(description="某刻校园 20 人并发基础链路")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--users", type=int, default=20)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    total = args.users
    stats = Stats()

    limits = httpx.Limits(max_connections=total * 2, max_keepalive_connections=total * 2)
    async with httpx.AsyncClient(base_url=base, timeout=httpx.Timeout(60.0), limits=limits) as client:
        health = await call(client, stats, "准备", "healthz", "GET", "/healthz")
        if health.status_code != 200:
            print(f"服务不可用：{health.status_code} {health.text}")
            return 1

        users: list[dict] = [{} for _ in range(total)]

        async def register(index: int) -> None:
            student_id = f"LOAD{index:02d}"
            email = f"load{index:02d}@hust.edu.cn"
            code_response = await call(
                client, stats, "注册", "request_code", "POST", "/api/auth/request-code",
                json={"student_id": student_id, "email": email},
            )
            code = code_response.json().get("dev_code") if code_response.status_code == 200 else None
            if not code:
                stats.failures.append(f"LOAD{index:02d} 未拿到开发验证码")
                return
            response = await call(
                client, stats, "注册", "register", "POST", "/api/auth/register",
                allowed=(201,),
                json={"student_id": student_id, "email": email, "code": code, "password": "LoadTest123!"},
            )
            if response.status_code == 201:
                users[index] = {
                    "headers": {"Authorization": f"Bearer {response.json()['access_token']}"},
                    "student_id": student_id,
                }

        await asyncio.gather(*(register(i) for i in range(total)))

        ready = [i for i, user in enumerate(users) if user]
        print(f"注册成功：{len(ready)}/{total}")

        async def publish(index: int) -> None:
            user = users[index]
            if not user:
                return
            locations = await call(client, stats, "浏览", "locations", "GET", "/api/locations", headers=user["headers"])
            location_id = locations.json()[0]["id"] if locations.status_code == 200 else 1
            await call(client, stats, "浏览", "feed", "GET", "/api/feed", headers=user["headers"])
            response = await call(
                client, stats, "发布", "create_moment", "POST", "/api/moments",
                allowed=(201,), headers=user["headers"],
                json={"location_id": location_id, "content": "今天的晚风很舒服，想在这里坐一会儿", "mood": "平静"},
            )
            if response.status_code == 201:
                user["moment_id"] = response.json()["id"]
                user["location_id"] = location_id

        await asyncio.gather(*(publish(i) for i in range(total)))

        async def interact(index: int) -> None:
            user = users[index]
            target = users[(index + 1) % total]
            if not user or not target.get("moment_id"):
                return
            moment_id = target["moment_id"]
            for _ in range(2):  # 第二次验证共鸣幂等（upsert）
                await call(
                    client, stats, "互动", "resonate", "POST", f"/api/moments/{moment_id}/resonances",
                    headers=user["headers"], json={"kind": "我也这样"},
                )
            await call(
                client, stats, "互动", "echo", "POST", f"/api/moments/{moment_id}/echoes",
                headers=user["headers"], json={"content": "我也喜欢这里的风"},
            )
            await call(
                client, stats, "互动", "interactions", "GET", f"/api/moments/{moment_id}/interactions",
                headers=user["headers"],
            )

        await asyncio.gather(*(interact(i) for i in range(total)))

        async def chat(index: int) -> None:
            user = users[index]
            target = users[(index + 1) % total]
            if not user or not target.get("moment_id"):
                return
            created = await call(
                client, stats, "聊天", "start_conversation", "POST", "/api/conversations",
                allowed=(201,), headers=user["headers"], json={"moment_id": target["moment_id"]},
            )
            if created.status_code not in (200, 201):
                return
            conversation_id = created.json()["id"]
            await call(
                client, stats, "聊天", "accept", "POST", f"/api/conversations/{conversation_id}/decision",
                headers=target["headers"], json={"action": "accept"},
            )
            message = await call(
                client, stats, "聊天", "send_message", "POST", f"/api/conversations/{conversation_id}/messages",
                allowed=(201,), headers=user["headers"], json={"content": "你好，我也常来这里坐一会儿"},
            )
            await call(
                client, stats, "聊天", "read_messages", "GET", f"/api/conversations/{conversation_id}/messages",
                headers=target["headers"],
            )
            if message.status_code == 201:
                await call(
                    client, stats, "聊天", "mark_read", "POST", f"/api/conversations/{conversation_id}/read",
                    headers=target["headers"], json={"message_id": message.json()["id"]},
                )

        await asyncio.gather(*(chat(i) for i in range(total)))

    print("\n== 各阶段延迟（毫秒） ==")
    print(f"{'阶段':<6}{'请求':<24}{'次数':>5}{'p50':>9}{'p95':>9}{'max':>9}")
    for (phase, name), values in sorted(stats.durations.items()):
        ms = [value * 1000 for value in values]
        print(f"{phase:<6}{name:<24}{len(ms):>5}{statistics.median(ms):>9.1f}"
              f"{stats.percentile(ms, .95):>9.1f}{max(ms):>9.1f}")

    print("\n== 状态码 ==")
    for (name, code), count in sorted(stats.statuses.items()):
        print(f"{name:<24}{code:>4}  x{count}")

    all_values = [value for values in stats.durations.values() for value in values]
    print(f"\n总计 {len(all_values)} 个请求，p50 {statistics.median(all_values) * 1000:.1f} ms，"
          f"p95 {stats.percentile(all_values, .95) * 1000:.1f} ms，"
          f"max {max(all_values) * 1000:.1f} ms")

    if stats.failures:
        print(f"\n失败 {len(stats.failures)} 条（最多显示 20 条）：")
        for failure in stats.failures[:20]:
            print("  -", failure)
        return 1

    print("\n所有预期请求均成功。")
    print(json.dumps({"requests": len(all_values), "users": total}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
