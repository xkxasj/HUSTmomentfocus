# 某刻 · 校园情境社交 MVP

一个用于验证“浏览地点 → 共鸣 → 回声 → 发布 → 回访”闭环的 Web 原型。

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

- “此刻校园”动态首页
- 六个固定校园地点及情绪地图
- 地点心情墙
- 文字心情发布
- 匿名回声
- 个人活动概览
- AI 表达提示和隐私检查占位接口

## 下一阶段

1. 校园身份认证与前台匿名机制
2. 图片上传、语音录制与转写
3. 内容审核、举报和拉黑后台
4. 通知与双向同意的限时对话
5. 地图设计完善增加地点
6. 埋点与校园验证实验
