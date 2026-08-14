# 某刻 · 校园情境社交 MVP

一个用于验证“浏览地点 → 共鸣 → 回声 → 发布 → 回访”闭环的 Web 原型。

## 下载安装

Android 测试版请前往 [GitHub Releases](https://github.com/xkxasj/HUSTmomentfocus/releases/latest) 下载。APK 作为发行附件提供，不直接存入源码仓库。

## 技术结构

- `frontend/`：Vue 3 + TypeScript + Vite
- `backend/`：FastAPI + SQLAlchemy + SQLite
- `backend/app/mouke.db`：首次启动自动创建并写入演示数据

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

当前 Android APK 通过局域网访问电脑上的 FastAPI。手机与电脑需连接同一 Wi-Fi 或电脑热点；登录页的“连接设置”可填写 `http://电脑当前IP:8000`，无需仅为 IP 变化重新打包。

```powershell
cd backend
.\start-backend.ps1
```

重新打包 APK：

```powershell
cd frontend
npm.cmd run apk:debug
```

生成文件位于 `frontend/android/app/build/outputs/apk/debug/app-debug.apk`。如电脑局域网 IP 变化，可参考 `frontend/.env.mobile.example` 创建或更新 `frontend/.env.mobile` 后重新打包。

## 真实邮箱验证码

默认不显示开发验证码；没有发件服务时，注册页会明确提示暂时不能发送。正式启用步骤：

1. 将 `backend/smtp.local.env.example` 复制为 `backend/smtp.local.env`。
2. 使用专门的服务邮箱填写用户名和邮箱密码/应用密码，不要使用个人主账号，也不要把密码发到聊天或提交到版本库。
3. 保持 `MOUKE_DEV_EMAIL_CODES=0`，重新运行 `backend/start-backend.ps1`。

发件邮箱不必是校园邮箱，收件人仍由系统限制为学号对应的教育邮箱。华科邮箱可尝试 `mail.hust.edu.cn`、SSL 端口 `465`；实际参数以学校邮件服务说明为准。

Outlook 可以作为发件账号，但 Outlook.com / Exchange Online 当前要求 OAuth2（Modern Auth）。本项目现有的用户名+密码 SMTP 适配器不能直接使用普通 Outlook 密码；接入时应增加 Microsoft Graph/OAuth 发件适配器并提供应用注册凭据。

## 真实地图与图片文案

- 地图使用 MapLibre GL 5 和 OpenFreeMap/OpenStreetMap 矢量数据，手机只访问电脑后端；后端按需转发并缓存当前视野瓦片，不再使用水彩演示底图。
- 图片支持 JPG、PNG、WebP，单张上限 15MB。
- `POST /api/ai/image-caption` 已提供稳定接口。未配置视觉服务时返回明确的地点模板文案；配置 `MOUKE_VISION_API_URL`、`MOUKE_VISION_API_KEY` 后，适配器可真正识图并返回 `{"caption":"..."}`。
- `GET /api/ai/status` 和 `GET /api/map/status` 可用于检查服务配置和地图缓存状态。

## 当前范围

- “此刻校园”动态首页
- 六个固定校园地点及情绪地图
- 地点心情墙
- 文字与图片发布
- 三种共鸣与匿名回声
- 个人活动概览
- AI 表达提示、隐私检查和图片文案接口

## 下一阶段

1. Microsoft Graph/OAuth 或事务邮件服务接入
2. 视觉模型与图片内容审核服务接入
3. 语音录制与转写
4. 内容举报和审核后台
5. 通知与双向同意的限时对话
