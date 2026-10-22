# 运营手册（内测阶段）

配套文件：部署见 [deploy/README.md](../deploy/README.md)，上线清单见
[LAUNCH_TODO.md](LAUNCH_TODO.md)。

## 1. 值班与举报处理

内测阶段至少保证 **工作日 24 小时内、节假日 72 小时内** 处理举报。举报入口在
每条动态/回声/会话的“举报”按钮，管理员在产品内“管理后台 → 举报”处理。

处理顺序：

1. 看证据与上下文，判断是否违反用户协议（违法、骚扰、隐私泄露、诈骗等）。
2. `hide` 隐藏被举报内容；会话类举报用 `close` 结束会话；误报用 `dismiss`。
3. 在 `note` 写清依据，便于复核；这是审计日志的一部分。
4. 涉及人身安全、诈骗、未成年人或违法内容：先隐藏，再上报学校相关部门，
   不要自行联系当事人。

不要绕过管理后台直接改数据库；管理操作会写 `admin_audit_logs`，直接改库会丢审计。

## 2. 数据保留与清理

| 数据 | 保留期 | 清理方式 |
| --- | --- | --- |
| 登录会话 | 14 天过期 | `scripts/retention.py` |
| 验证码 | 10 分钟有效；已用/过期 24 小时后删 | 同上 |
| AI 调用计量 | 30 天 | 同上 |
| 匿名埋点 | 90 天 | 同上 |
| 表达风格语料 | 180 天 | 同上 |
| 动态/回声/聊天 | 至用户删除或注销 | 用户操作 |
| 举报证据 | 处理完成后 180 天 | 人工复核后清理 |
| 备份 | 14 天滚动 | `backup.py --keep-days` |

每日 03:20 执行（与备份错开）：

```bash
cd /opt/mouke/backend
.venv/bin/python scripts/retention.py --dry-run   # 先看数量
.venv/bin/python scripts/retention.py
```

容器部署：

```bash
docker compose --env-file .env.production -f deploy/docker-compose.yml exec -T backend \
  python scripts/retention.py --dry-run
docker compose --env-file .env.production -f deploy/docker-compose.yml exec -T backend \
  python scripts/retention.py
```

> **不要**在库正在被容器写入时从宿主机直接删除数据文件；用脚本走 SQL，
> 让 SQLite 自己处理锁与 WAL。

## 3. 数据主体请求（查阅 / 更正 / 删除）

用户可通过“我的 → 注销账号”自助删除。其他请求走联系邮箱：

1. 用学校邮箱回信，确认是本人（学号后四位 + 注册邮箱）。
2. 查阅：从管理后台导出该用户的公开内容与账号状态，不提供他人聊天内容。
3. 更正：仅限账号信息（邮箱等）；内容由用户自行修改/删除。
4. 删除：引导自助注销；无法登录时由管理员停用账号并按注销流程匿名化。
5. 全程记录时间、请求内容、处理结果，保存 2 年。

## 4. ICP 备案与合规清单

公开发布前需完成（**外部流程，代码无法替代**）：

- [ ] 域名实名认证与 ICP 备案（主体、网站负责人、幕布拍照按接入商要求）
- [ ] 公安联网备案（备案号展示在页脚）
- [ ] 隐私政策/用户协议由运营主体法务审阅，替换模板中的 `【运营主体】` 等占位符
- [ ] 明确运营主体、联系邮箱、通信地址
- [ ] 若涉及生成式 AI 功能，确认所用模型服务已完成相应备案/登记，并在页面说明
- [ ] 校园数据使用授权（如涉及学校名称、邮箱域名）
- [ ] 等保测评（按学校/属地要求，内测阶段通常先做备案与安全加固）

## 5. 故障处理

| 级别 | 例子 | 目标响应 |
| --- | --- | --- |
| P0 | 全站 5xx、数据库损坏、密钥泄露 | 立即回滚/停服，30 分钟内通报 |
| P1 | 注册/登录不可用、图片全部失败 | 2 小时内定位 |
| P2 | 单个功能异常、AI 降级 | 工作日 24 小时内 |

排查顺序：

1. `curl -fsS https://<域名>/healthz`，区分“进程挂了”和“数据库/路径问题”。
2. `docker compose --env-file .env.production -f deploy/docker-compose.yml ps` 与
   `docker compose --env-file .env.production -f deploy/docker-compose.yml logs --since 30m backend`
   （在仓库根目录执行；`--env-file` 不能省，原因见 `deploy/README.md`）。
3. 让用户提供页面上的 `X-Request-ID`（响应头），按该值检索日志。
4. 数据库损坏时停服 → 从最近备份恢复 → 记录丢失窗口 → 通知受影响用户。

**密钥泄露**（`MOUKE_CODE_SECRET`、`MOUKE_ALIAS_SECRET`、SMTP、模型 API Key）：
立即轮换、重启、吊销旧 key；验证码会话与登录会话全部失效（删除
`auth_sessions` 表数据），并评估是否需要通知用户。

## 6. 发布检查（每次上线）

- [ ] 全量后端测试通过：`python -m unittest discover -s tests`
- [ ] 前端类型检查与构建通过：`npm run typecheck && npm run build`
- [ ] 已备份当前数据库
- [ ] 新版本启动日志无“生产配置不安全”
- [ ] 手工走一遍：注册 → 发动态 → 共鸣 → 回声 → 发起/接受聊天 → 注销
- [ ] 20 人并发脚本通过（见 `backend/tests/loadtest_20users.py`）
- [ ] 回滚方案与上一个镜像 tag 已确认
