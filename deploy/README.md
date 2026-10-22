# 部署手册（单域名 Web）

目标形态：`https://mouke.example.com` 同时提供前端页面与 `/api`，后端与数据库都在
一台 2C2G 以上的 Linux 服务器上。适合校园内测，不适合多实例高并发。

> 还没有服务器、也不想买域名？按 [ORACLE_FREE.md](ORACLE_FREE.md) 用
> Oracle Cloud Always Free（2 OCPU / 12 GB / 200 GB 磁盘）部署，现有 compose
> 不用改，配合 DuckDNS 免费子域名即可拿到 HTTPS 地址。

## 0. 前置条件

- 一台能跑 Docker 的服务器，80/443 端口对公网开放。
- 域名已解析到服务器（A 记录）。
- 学校邮箱 SMTP 可用（发件账号、授权码）。
- 国内公网部署需完成 ICP 备案；未备案时 80/443 可能被拦截，这是外部流程，
  代码无法替代。

## 1. 配置

```bash
cp .env.production.example .env.production
```

必须逐项填写：

| 变量 | 说明 |
| --- | --- |
| `MOUKE_DOMAIN` | 真实域名；Caddy 用它申请证书 |
| `MOUKE_CODE_SECRET` / `MOUKE_ALIAS_SECRET` | 两条不同的 32 字节以上随机值（`openssl rand -hex 32`） |
| `MOUKE_SMTP_*` | 发件服务器；不配置则注册收不到验证码 |
| `MOUKE_ADMIN_*` | 首个管理员；首次启动创建 |
| `MOUKE_LOG_LEVEL=INFO` | 输出一行一个 JSON 的访问日志 |

`MOUKE_ENV=production` 会启用启动自检：如果仍在回显验证码、使用默认密钥或没有
SMTP，进程会**拒绝启动**，而不是带着不安全的默认值上线。

## 2. 启动

```bash
cd deploy
docker compose --env-file ../.env.production up -d --build
docker compose ps
docker compose logs -f backend
```

`--env-file` 不能省：它负责把 `MOUKE_DOMAIN` 插值进 web 容器的环境变量，
Caddy 用它申请证书。backend 的变量则通过 compose 里的 `env_file` 注入。

首次启动会建库、写入种子地点并创建管理员。Caddy 会自动申请并续期 TLS 证书。

验证：

```bash
curl -fsS https://mouke.example.com/healthz
# {"status":"ok"}
```

浏览器打开首页 → 注册 → 发布一条动态。

## 3. 数据与备份

所有持久数据在 Docker 卷 `mouke_data` 中：

```
/data/mouke.db          SQLite 主库（WAL 伴生文件同目录）
/data/uploads/          用户上传图片
/data/map_cache/        地图瓦片缓存（可重建，不必备份）
/data/backups/          备份输出目录
```

每日备份（建议 cron 03:10）：

```bash
cd /opt/mouke
docker compose --env-file .env.production -f deploy/docker-compose.yml exec -T backend \
  python backup.py --db /data/mouke.db --uploads /data/uploads --out /data/backups --keep-days 14
```

备份脚本使用 SQLite 在线备份 API，不会拿到 WAL 撕裂快照。备份文件包含用户数据，
请放在加密磁盘，并**每季度做一次恢复演练**：

```bash
# 停止写入后恢复（示例）
docker compose --env-file .env.production -f deploy/docker-compose.yml stop backend
docker run --rm --entrypoint sh -v mouke_mouke_data:/data -v "$PWD/backups":/backup mouke-backend:latest \
  -c 'cp /backup/mouke-YYYYmmdd-HHMMSS.db /data/mouke.db && rm -f /data/mouke.db-wal /data/mouke.db-shm'
docker compose --env-file .env.production -f deploy/docker-compose.yml start backend
curl -fsS https://mouke.example.com/healthz
```

## 4. 更新与回滚

```bash
git pull
cd deploy && docker compose --env-file ../.env.production up -d --build
```

- 前端构建产物带内容哈希，`index.html` 不缓存，发版后刷新即可生效。
- 数据库迁移是幂等的补列逻辑；回滚镜像不会自动回滚数据，回滚前先备份。
- 回滚（以下命令在 `deploy/` 目录）：`docker compose --env-file ../.env.production down`
  → 切回上一个提交 → `docker compose --env-file ../.env.production up -d --build`。

## 5. 日志与排障

```bash
cd deploy
docker compose --env-file ../.env.production logs -f backend     # 应用日志
docker compose --env-file ../.env.production logs -f web         # Caddy 证书/访问日志
```

- 每个响应带 `X-Request-ID`，用户报错时让对方提供该值，可在日志中定位整条请求。
- 访问日志不记录查询串和请求体，避免验证码、聊天内容落盘。
- AI 接口失败会自动降级为模板文案；若页面完全没有 AI 建议，检查
  `DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY`。

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 容器反复重启，日志提示“生产配置不安全” | 按提示补齐 `MOUKE_CODE_SECRET`、`MOUKE_ALIAS_SECRET`、`MOUKE_SMTP_HOST`，并把 `MOUKE_DEV_EMAIL_CODES` 设为 0 |
| 注册提示“验证码邮件发送失败” | SMTP 地址/端口/授权码错误，或发件域名 SPF/DKIM 未配置，邮件进了垃圾箱 |
| 上传图片 413 | 反代 `client_max_body_size` 小于 15MB；Caddy 默认无限制，Nginx 见 `nginx.conf` |
| 地图空白 | 服务器访问 `tiles.openfreemap.org` 失败；检查出网与 `/api/map/status` |
| 登录提示 423 | 连续 5 次密码错误触发 15 分钟锁定，等待或让管理员处理 |
| 20 人以上写入变慢 | SQLite 单写者。先看慢在 PBKDF2 还是写锁；扩容前按下一节切换数据库 |

## 7. 什么时候该换 PostgreSQL

出现以下任一情况再换，提前换只会增加运维面：

- 需要跑多个后端实例（当前认证限流是进程内计数，多实例本就要改 Redis）；
- 日写入量持续超过 SQLite 舒适区（经验上数千条/天仍很轻松）；
- 需要在线只读副本或专业备份工具。

切换步骤：

1. 准备 PostgreSQL 15+，建库建用户。
2. 设置 `MOUKE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/mouke`。
3. 先在一个空库上启动一次，让 `create_all` 建表；旧 SQLite 数据用脚本迁移，
   不要直接复制文件。
4. 认证限流换成 Redis（`app/auth_security.py` 是唯一改动点），反向代理加
   `limit_req` 兜底。

## 8. 安全清单

- [ ] `.env.production` 权限 600，且不在 git 中
- [ ] 两条 secret 不同且足够长
- [ ] SMTP 使用授权码，不使用登录密码
- [ ] 管理员密码为独立强密码
- [ ] 服务器防火墙只放行 22/80/443
- [ ] 已配置每日备份与恢复演练
- [ ] 已准备举报值班邮箱与处理时限
