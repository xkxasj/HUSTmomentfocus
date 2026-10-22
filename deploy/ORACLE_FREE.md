# Oracle Cloud 永久免费部署（Web 版）

目标：在 Oracle Cloud Always Free 的 ARM 机器上，用仓库现有的
`docker compose` 跑起单域名 HTTPS 站点，不买服务器、不买域名。

适合校园内测 / 演示；不适合把唯一一份数据放在上面长期不管。开始前先读
[第 8 节](#8-关于闲置回收)的回收规则。

> 官方额度（2026-06 文档）：Ampere A1 共 **2 OCPU + 12 GB 内存**、
> **200 GB 块存储**，另有 2 台 AMD 微型实例。不是网上旧教程写的 4 核 24G。
> 参考：[Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)。

## 0. 你需要准备

- 一张能验证的信用卡/借记卡（注册身份验证用，Always Free 额度内不扣费）。
- 一个 SSH 密钥对。
- 学校邮箱 SMTP 账号（注册验证码要用；HUST 可用 `mail.hust.edu.cn:465` SSL）。
- 先在本机提交并推送最新代码，服务器才能 `git clone` 到包含 `deploy/` 的版本。

## 1. 创建实例

在 OCI 控制台：

1. **Region**：选首尔、大阪或新加坡。Home region 创建后不能改，先想好。
2. **Shape**：`VM.Standard.A1.Flex`，OCPU 填 `2`，内存填 `12 GB`。
3. **Image**：Canonical Ubuntu 24.04（aarch64）。
4. **Boot volume**：默认 47–50 GB 即可，200 GB 额度用不完。
5. 上传/选择 SSH 公钥，分配公网 IPv4。
6. 创建后在实例详情里记下 **Public IP**。

如果提示 `Out of host capacity`：换一个 Availability Domain、隔段时间再试，
或者把账号升级为 Pay As You Go（Always Free 额度内仍然 $0，且更容易开出来）。

建议在 **Networking → Reserved public IP** 里把公网 IP 保留下来，避免实例重建后
地址变化导致域名失效。

## 2. 放行 80/443

两处都要放行，缺一处外面就打不开。

### 2.1 OCI 安全列表

VCN → Security Lists → Default Security List → Add Ingress Rules：

| 源 | 协议 | 端口 |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |
| `0.0.0.0/0` | UDP | `443`（可选，HTTP/3） |

不要放行 `8000`：后端只应该被 Caddy 通过容器内网访问。

### 2.2 机器自带防火墙

Oracle 的 Ubuntu 镜像默认在 iptables 末尾有 REJECT 规则。登录服务器后执行：

```bash
sudo bash /opt/mouke/deploy/oracle/open-ports.sh
```

脚本会插入 80/443 规则并持久化。还没克隆代码时，也可以手动执行：

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT -p udp --dport 443 -j ACCEPT
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

## 3. 域名：DuckDNS（免费）

不买域名也能有 HTTPS。**推荐 DuckDNS**，因为它已列入 Public Suffix List，
每个 `*.duckdns.org` 子域名单独计算 Let's Encrypt 证书额度。

> 不推荐 `sslip.io` / `nip.io`：它们不在 Public Suffix List 里，所有用户的
> 子域名共用 `sslip.io` 的 50 张证书/周额度，签发经常失败。它们适合临时
> 测试，不适合当正式地址。

### 3.1 创建子域名

1. 打开 <https://www.duckdns.org/>，用 GitHub/Google 登录。
2. 创建一个子域名，例如 `mouke-hust`，完整域名是 `mouke-hust.duckdns.org`。
3. 在 `current ip` 里填 Oracle 的 Public IP，点 `update ip`。
4. 记下页面上的 token。

检查解析：

```bash
getent hosts mouke-hust.duckdns.org
# 应返回你的 Oracle 公网 IP
```

### 3.2 自动更新（可选）

如果公网 IP 是保留地址，通常不会变；没有保留就加一个 cron：

```bash
sudo mkdir -p /etc/mouke
sudo tee /etc/mouke/duckdns.env >/dev/null <<'EOF'
DUCKDNS_DOMAIN=mouke-hust
DUCKDNS_TOKEN=把这里换成你的token
EOF
sudo chmod 600 /etc/mouke/duckdns.env

# 手动验证一次
sudo bash /opt/mouke/deploy/oracle/duckdns-update.sh

# 每小时检查一次（root cron，能读 /etc/mouke/duckdns.env）
echo '17 * * * * root bash /opt/mouke/deploy/oracle/duckdns-update.sh >/dev/null 2>&1' \
  | sudo tee /etc/cron.d/mouke-duckdns >/dev/null
sudo chmod 644 /etc/cron.d/mouke-duckdns
```

> DuckDNS 在少数校园网/运营商可能解析不稳定。如果 `getent hosts` 经常失败，
> 花 ¥10 左右买个域名（或用 GitHub 学生包领 Namecheap `.me`）会更稳，
> 后面的 Caddy 配置不用改，只换 `MOUKE_DOMAIN`。

## 4. 安装 Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

`python:3.12-slim`、`node:22-alpine`、`caddy:2.8-alpine` 都有 arm64 镜像，
不需要改 Dockerfile。

## 5. 拉代码并配置

```bash
sudo mkdir -p /opt/mouke
sudo chown "$USER":"$USER" /opt/mouke
git clone https://github.com/xkxasj/HUSTmomentfocus.git /opt/mouke
cd /opt/mouke
cp .env.production.example .env.production
chmod 600 .env.production
```

编辑 `.env.production`，至少改这些：

```ini
MOUKE_ENV=production
MOUKE_DOMAIN=mouke-hust.duckdns.org

# 两条不同的 32 字节随机值
MOUKE_CODE_SECRET=...
MOUKE_ALIAS_SECRET=...

# 学校邮箱 SMTP；Oracle 只封 25 端口，465/587 可用
MOUKE_SMTP_HOST=mail.hust.edu.cn
MOUKE_SMTP_PORT=465
MOUKE_SMTP_SSL=1
MOUKE_SMTP_TLS=0
MOUKE_SMTP_USERNAME=你的发件账号
MOUKE_SMTP_PASSWORD=授权码
MOUKE_SMTP_FROM=某刻校园 <你的发件账号>

MOUKE_ADMIN_STUDENT_ID=...
MOUKE_ADMIN_EMAIL=...
MOUKE_ADMIN_PASSWORD=...

MOUKE_LOG_LEVEL=INFO
MOUKE_ALLOWED_ORIGINS=
```

生成密钥：

```bash
openssl rand -hex 32
openssl rand -hex 32
```

注意：

- `MOUKE_ENV=production` 会做启动自检：仍在回显验证码、使用默认/弱密钥、
  两条 secret 相同、缺少 SMTP，都会让进程**拒绝启动**。这是有意的。
- `MOUKE_DEV_EMAIL_CODES` 必须是 `0`（模板默认就是 0）。
- 不要把 `.env.production` 提交到 Git，也不要放进 Docker 构建上下文。

## 6. 启动

```bash
cd /opt/mouke/deploy
docker compose --env-file ../.env.production up -d --build
docker compose --env-file ../.env.production ps
docker compose --env-file ../.env.production logs -f backend
```

`--env-file` 不能省：backend 通过 `env_file` 读配置，但 web 容器的
`MOUKE_DOMAIN` 依赖 compose 变量插值，插值只认 `--env-file` / shell。
少了它，Caddy 会退回 `localhost`，证书签不下来。

首次在 2 OCPU 的 ARM 机器上构建需要几分钟。构建完成后：

```bash
curl -fsS https://mouke-hust.duckdns.org/healthz
# {"status":"ok"}
```

浏览器打开首页 → 注册 → 发布一条动态 → 上传一张图片。

## 7. 备份与清理（必须做）

Always Free 实例可能被回收，**唯一一份数据不能只放在这台机器上**。

### 7.1 每日备份

```bash
sudo bash /opt/mouke/deploy/oracle/daily-maintenance.sh
```

脚本会：

1. 用 SQLite 在线备份 API 备份数据库和上传图片，保留 14 天；
2. 清理过期会话、验证码、AI 用量等；
3. 如果配置了名为 `mouke-offsite:` 的 rclone 远端，把备份同步过去。

加入 cron（每天 03:10，root 执行，避免 Docker 套接字和备份文件权限问题）：

```bash
echo '10 3 * * * root bash /opt/mouke/deploy/oracle/daily-maintenance.sh >> /var/log/mouke-maintenance.log 2>&1' \
  | sudo tee /etc/cron.d/mouke-maintenance >/dev/null
sudo chmod 644 /etc/cron.d/mouke-maintenance
sudo touch /var/log/mouke-maintenance.log
```

### 7.2 异地副本

任选一种：

- **另一台机器**：`sudo rclone config` 建一个 SFTP 远端，命名为 `mouke-offsite`；
- **OCI Object Storage**：Always Free 含 20 GB 对象存储，用 rclone 的 S3 兼容模式；
- **手动下载**：`sudo docker run --rm --entrypoint sh -v mouke_mouke_data:/data -v "$PWD/backups":/backup mouke-backend:latest -c 'cp -a /data/backups/. /backup/'`。

因为 daily-maintenance 由 root cron 执行，rclone 配置也要放在 root 的配置里
（`sudo rclone config`，默认写到 `/root/.config/rclone/rclone.conf`）。

备份里有用户聊天和邮箱，放到第三方存储前先加密（rclone 的 `crypt` 远端）。

### 7.3 恢复

```bash
cd /opt/mouke
docker compose --env-file .env.production -f deploy/docker-compose.yml stop backend

# 备份已经在容器卷 /data/backups 里的情况。
# 用已经构建好的 backend 镜像，避免临时拉取 alpine。
sudo docker run --rm --entrypoint sh -v mouke_mouke_data:/data mouke-backend:latest \
  -c 'cp /data/backups/mouke-YYYYmmdd-HHMMSS.db /data/mouke.db && rm -f /data/mouke.db-wal /data/mouke.db-shm'

# 上传图片（tar 内部目录名就是 uploads）
sudo docker run --rm --entrypoint sh -v mouke_mouke_data:/data -v "$PWD/backups":/backup mouke-backend:latest \
  -c 'rm -rf /data/uploads && mkdir -p /data/uploads && tar -xzf /backup/mouke-uploads-YYYYmmdd-HHMMSS.tar.gz -C /data'

docker compose --env-file .env.production -f deploy/docker-compose.yml start backend
curl -fsS https://mouke-hust.duckdns.org/healthz
```

如果实例是重建的（本地卷已经没了），先把异地备份放回宿主机 `./backups`，
再用上面的命令复制进卷。恢复前建议先备份当前库，哪怕它看起来已经坏了。

## 8. 关于闲置回收

Oracle 文档写明：7 天内 **CPU 95 分位 < 20%**、**网络 < 20%**、
**内存 < 20%（仅 A1）** 三条同时成立，实例可能被判定为闲置并回收。

这套栈内存占用通常远低于 12 GB 的 20%（2.4 GB），所以确实有命中风险。
可行的降低风险方式：

1. **升级为 Pay As You Go**：Oracle 的回收通知邮件明确说，转为 PAYG 后
   闲置实例不会被停机；只要总用量在 Always Free 额度内仍然不收费。
   升级后建议设置预算告警（Billing → Budgets，阈值 $1）。
2. **不要把备份只放在这台机器上**：见上一节。
3. 不要靠“每天 curl 一次”来规避，CPU 95 分位几乎不会因此上升。

如果真的被回收：重建实例 → 装 Docker → 拉代码 → 恢复数据库和上传目录。
域名解析指向新 IP 即可（DuckDNS 更新一下）。

## 9. 更新与回滚

```bash
cd /opt/mouke
git pull
cd deploy
docker compose --env-file ../.env.production up -d --build
```

回滚：`docker compose --env-file ../.env.production down` → `git checkout <上一个提交>`
→ 重新 `up -d --build`。数据库迁移是幂等补列；回滚镜像不会回滚数据，
回滚前先跑一次备份。

## 10. 排障

| 现象 | 排查 |
| --- | --- |
| `https://` 打不开，`http://` 也超时 | OCI 安全列表 + 机器 iptables 都要放行 80/443；`sudo iptables -L INPUT -n` 看规则 |
| Caddy 日志 `no such host` | DuckDNS 未解析或还没生效；`getent hosts 域名` |
| Caddy 日志申请证书失败 | 80 端口没通、域名填错、或用了 sslip.io 这类共享额度域名 |
| 502 Bad Gateway | backend 没起来；`logs backend` 看是否被生产自检拒绝 |
| 注册提示邮件发送失败 | SMTP 账号/授权码错；Oracle 封 25 端口，改用 465/587；检查 SPF/DKIM |
| 上传图片 413 | 走的是 Caddy，默认无大小限制；若换 Nginx，确认 `client_max_body_size 16m` |
| 地图空白 | 服务器访问 `tiles.openfreemap.org` 失败；看 `/api/map/status` |
| 实例突然消失 | 可能被判定闲置回收；用异地备份重建，见第 8 节 |

## 11. 上线前检查

- [ ] OCI 安全列表放行 TCP 80/443
- [ ] `open-ports.sh` 已执行并 `netfilter-persistent save`
- [ ] DuckDNS 解析到正确 IP
- [ ] `MOUKE_ENV=production` 启动无“生产配置不安全”
- [ ] HTTPS 证书正常，`/healthz` 返回 ok
- [ ] 注册 → 登录 → 发动态 → 上传图片走通
- [ ] 每日备份 cron 已跑过一次，异地副本可读
- [ ] 管理员密码为独立强密码，`.env.production` 权限 600
- [ ] 隐私政策/用户协议里的 `【运营主体全称】` 等占位符已替换
- [ ] 已准备举报值班邮箱与处理时限
