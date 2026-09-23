# 某刻 · 校园情境社交 MVP

一个用于验证“浏览地点 → 共鸣 → 回声 → 发布 → 回访”闭环的 Web 原型。

## 技术结构

- `frontend/`：Vue 3 + TypeScript + Vite
- `backend/`：FastAPI + SQLAlchemy + SQLite
- `backend/app/mouke.db`：首次启动自动创建并初始化校园地点

## 本地运行

### 后端

```powershell
cd backend
.\start-backend.ps1
```

如果手机无法访问后端，请以管理员身份打开 PowerShell，并运行以下脚本。它只允许本地子网访问 TCP 8000：

```powershell
cd backend
.\allow-mobile-firewall.ps1
```

脚本会依次寻找系统 Python、`py` 启动器和 Codex 内置 Python，自动创建虚拟环境、安装依赖并启动服务。

如果希望手动运行，PowerShell 中应使用：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

如果 `python` 和 `py` 都不存在，需要先安装 Python 3.11 或更高版本，并勾选 **Add Python to PATH**。激活脚本前面的 `.\` 不能省略。

### 前端

```powershell
cd frontend
.\start-frontend.ps1
```

浏览器打开 `http://localhost:5173`。接口文档位于 `http://localhost:8000/docs`。

## Android 测试版

当前 Android APK 通过局域网访问电脑上的 FastAPI。手机与电脑需连接同一 Wi-Fi，电脑地址为 `192.168.43.162`。

```powershell
cd backend
.\start-backend.ps1
```

重新打包 APK：

```powershell
cd frontend
npm.cmd run apk:debug
```

生成文件位于 `frontend/android/app/build/outputs/apk/debug/app-debug.apk`。如电脑局域网 IP 变化，需更新 `frontend/.env.mobile` 后重新打包。

## 真实邮箱验证码

默认不显示开发验证码；没有发件服务时，注册页会明确提示暂时不能发送。正式启用步骤：

1. 将 `backend/smtp.local.env.example` 复制为 `backend/smtp.local.env`。
2. 使用专门的服务邮箱填写用户名和邮箱密码/应用密码，不要使用个人主账号，也不要把密码发到聊天或提交到版本库。
3. 保持 `MOUKE_DEV_EMAIL_CODES=0`，重新运行 `backend/start-backend.ps1`。

华科邮箱可使用 `mail.hust.edu.cn`、SSL 端口 `465`；实际部署更建议申请项目专用发件账号并设置发送频率限制。

## 管理员后台

管理员与普通用户使用同一套应用，服务端按账号角色隔离权限。后台入口为 `/#/admin`，普通账号无法读取管理接口。

首次设置或重置管理员账号：

```powershell
cd backend
.\setup-admin.ps1
```

脚本会把账号和密码写入被 Git 忽略的 `backend/smtp.local.env`，不会把密码提交到仓库。设置后重启后端，再从普通登录页面使用管理员账号登录；个人页面会显示“进入管理后台”。生产部署时应将 `MOUKE_ADMIN_STUDENT_ID`、`MOUKE_ADMIN_EMAIL`、`MOUKE_ADMIN_PASSWORD` 配置为云平台的私密环境变量。

## 当前范围

- 校园邮箱验证码注册、匿名昵称、登录和服务端注销会话。
- 校园动态首页（每页 20 条、加载更多）、28 个固定地点和真实校园地图；地点墙独立加载完整地点内容。
- 文字和单张图片发布；公开文字在服务端检查常见手机号、邮箱、身份证格式和隐私关键词。
- 每个账号对一条片段保留一份共鸣，可切换种类、取消；30 字公开回声及匿名回声列表。
- 个人发布记录、送出共鸣、公开回声和收到共鸣统计；今日统计按服务器当地自然日计算。
- 从公开片段发起邀请；邀请 24 小时内有效，接收方接受后可聊 24 小时。拒绝、主动结束、到期后保留记录，禁止继续发送。旧版会话保留历史，但升级后需要接收方重新接受邀请。
- 会话未读数和逐消息已读游标；前台会话列表每 5 秒刷新，聊天页每 3 秒拉取消息。只有正在查看的聊天页且窗口可见时才标记已读；当前没有系统推送通知。
- 屏蔽用户后双向禁止私聊及共鸣/回声互动，并结束双方已有会话；个人页可解除屏蔽，已结束的会话不会自动重开。同一片段结束后不能反复重新邀请。
- 位置共享默认关闭，只有双方接受且仍有效的会话可见；位置超过 30 分钟失效。
- 动态、公开回声、会话举报；管理员查看举报证据、隐藏内容或结束会话、填写处理说明和结案。会话举报会明确提示将最近 20 条消息提交给管理员，后台没有任意读取私人会话的接口。
- 运营埋点、管理员统计、用户停用、内容隐藏与操作审计。
- 图片文案与回复建议可接外部 AI；没有配置服务时退化为模板。
- 公开内容经过本地词表把关（`backend/app/moderation.py`）：动态正文、心情、公开回声命中即拒绝发布，AI 生成的文案与回复命中即整批丢弃并退化为模板。**不在把关范围内**：私聊消息、举报理由、管理端处理说明、以及图片内容本身（`upload_image` 只校验魔数）。词表是少量无争议的种子词，正式上线前必须从合规渠道获取并人工审校；隐私规则和图片格式校验不等于完整自动内容审核。

## 验证与升级

```powershell
cd backend
.\.venv-runtime\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-runtime\Scripts\python.exe -m unittest discover -s tests -v
cd ../frontend
npm.cmd ci
npm.cmd run typecheck
npm.cmd run build
```

首次运行按前面的步骤创建虚拟环境。GitHub Actions 同样运行后端测试、前端类型检查和生产构建。

测试分两层，改内容把关时先跑快的那个：`tests/test_moderation.py` 是纯函数测试，毫秒级、不碰数据库；其余文件走 `TestClient`，约 10 秒。加词表规则的做法见 `backend/app/moderation.py` 顶部的「加词的纪律」。

启动时会自动补充旧数据库的互动归属、回声隐藏、邀请状态和已读字段，并建立举报和屏蔽表；升级前请备份 `backend/app/mouke.db` 及 `uploads/`。历史共鸣和回声没有用户归属，继续保留但不计入任何人的“送出”统计。迁移可重复运行，不会删除历史消息。

## 尚未包含

语音录制与转写、年度回顾、毕业声音地图、系统推送、图片内容识别、外接自动审核服务与人工复核队列、密码找回、正式云部署和发布签名。当前适合局域网功能验证，图片仍保存在本地目录。
