# 上线改造 TODO

> 目标：以“HTTPS 网址 + 校园白名单内测”的 Web 形态上线。
> 状态：`[ ]` 待办 / `[x]` 已完成 / `[~]` 已完成代码与配置，需外部账号或人工执行。

## A. 部署层

- [x] A1 单域名 + HTTPS 反代（Caddy 自动证书 / Nginx 配置）
- [x] A2 SPA fallback、静态资源缓存策略
- [x] A3 进程守护、关闭 `--reload`、统一 `TZ=Asia/Shanghai`
- [x] A4 持久化目录、每日备份脚本与恢复演练步骤
- [x] A5 `/healthz`、`X-Request-ID`、一行一个 JSON 的访问日志（`MOUKE_LOG_LEVEL`）
- [x] A6 反向代理头（`--proxy-headers` / `X-Forwarded-*`）
- [x] A7 Oracle Cloud Always Free 部署指南与辅助脚本
  （[deploy/ORACLE_FREE.md](../deploy/ORACLE_FREE.md)）：DuckDNS 子域名、
  开端口、每日备份、闲置回收说明

## B. 代码与配置

- [x] B1 登录/注册/发码限流；验证码尝试次数；登录失败锁定
- [x] B2 生产环境配置校验（关闭 dev 验证码、强制强密钥、SMTP）
- [x] B3 匿名昵称改为服务端密钥 HMAC
- [x] B4 AI 接口每用户配额（图片文案、回复建议）
- [x] B5 SQLite WAL / busy_timeout / 外键；支持 `MOUKE_DATABASE_URL` 切换 PostgreSQL
- [x] B6 安全响应头（CSP/HSTS/nosniff/Referrer-Policy/frame-ancestors）与可配置 CORS
- [x] B7 上传目录可配置、仅图片、纳入备份

## C. 合规与运营

- [x] C1 隐私政策、用户协议、注销说明模板
- [x] C2 账号注销/数据删除接口与前端入口
- [x] C3 举报值班、数据留存、ICP 备案清单（[OPERATIONS.md](OPERATIONS.md)）
- [x] C4 过期会话/验证码/AI 用量清理脚本

## D. 验证

- [x] D1 新增后端单测并通过全量回归（96 个测试通过）
- [x] D2 20 用户并发压测脚本（`backend/tests/loadtest_20users.py`）
- [x] D3 压测执行与结果记录（原生 uvicorn + Docker/Caddy 两轮，见下）
- [x] D4 Docker 镜像在本机构建成功（amd64），`docker compose config` 通过；
  backend 健康检查、Caddy 反代、生产配置自检、备份/恢复均实测。
  ARM64（Oracle A1）构建尚未实测，首次部署时 `--build` 会验证。

## 压测结果（2026-10-22，本机 Windows / uvicorn 单进程 / SQLite WAL）

20 个账号并发完成完整链路：发码 → 注册 → 浏览 → 发布 → 共鸣（含重复提交）
→ 回声 → 发起会话 → 接受 → 发消息 → 已读。

| 阶段 | 请求数 | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 281 | 241 ms | 2390 ms | 3479 ms |
| 注册（PBKDF2 600k） | 20 | 2479 ms | 3394 ms | 3479 ms |
| 发布动态 | 20 | 248 ms | 266 ms | 271 ms |
| 共鸣 / 回声 / 互动详情 | 80 | 131–165 ms | 166–315 ms | 333 ms |
| 发起会话 | 20 | 487 ms | 577 ms | 602 ms |
| 发消息 / 接受 / 已读 | 60 | 268–310 ms | 284–412 ms | 496 ms |

- 状态码：全部符合预期（201/200），**无 4xx、无 5xx、无 SQLite 锁超时**。
- 连续跑两轮，注册 p50 分别为 2.5 s 与 4.4 s：差异来自 20 个 PBKDF2（60 万次）
  同时抢 CPU，不是数据库瓶颈。真实注册是低频操作，可接受；若需要更快，只能
  降迭代次数（不建议）或把注册改成异步任务。其余接口两轮都在亚秒级。
- 本结果只证明「单实例、20 人」可用，不代表百人以上容量。超过这个量级先看
  `docs/OPERATIONS.md` 的扩容前条件。

### 第二轮：完整 Docker 栈（backend + Caddy 反代）

同一脚本改为经 `http://127.0.0.1` 走 Caddy → backend，镜像为本地构建产物：

| 阶段 | 请求数 | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 281 | 121.7 ms | 292.6 ms | 426.3 ms |
| 注册（PBKDF2 600k） | 20 | 142.0 ms | — | — |
| 信息流 | 20 | 264.7 ms | — | — |
| 发起会话 | 20 | 192.3 ms | — | — |

- 20/20 注册成功，全部响应为预期 2xx，无 4xx / 5xx。
- 同一轮还通过 Caddy 走通了：发码 → 注册 → 地点 → 上传图片 → 发动态 →
  信息流可见 → 注销账号 → 注销后 `me` 返回 401。
- 备份/恢复演练、保留策略 dry-run、`daily-maintenance.sh`、生产配置自检
  （缺 SMTP/弱密钥时拒绝启动；配齐后 `/healthz` 200）均通过。
- Caddyfile 用真实 DuckDNS 域名做 `caddy validate`：`Valid configuration`，
  自动 HTTP→HTTPS 跳转已启用。真实证书签发需公网 80/443，未测。

## 需要外部执行、代码无法代替的事项

- [ ] 注册 Oracle Cloud 并创建 Always Free 实例（或改用已有服务器）
- [ ] 购买域名、解析 DNS、申请 TLS（Caddy 自动完成；DuckDNS 可先用免费子域名）
- [ ] 国内公网 ICP 备案、公安备案（仅国内服务器需要）
- [ ] 隐私政策/用户协议法律审阅并替换模板中的主体信息
- [ ] SMTP 发件域名 SPF/DKIM/DMARC 配置
- [ ] 应用商店/校园分发渠道审批（当前仅 Web）
