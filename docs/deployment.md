# 部署指南

本文介绍如何把崇岳鉴渊部署到 [Render](https://render.com)，以及全部环境变量和可选功能的配置方法。本地运行方式见 [README](../README.md#本地运行)。

- [部署到 Render](#部署到-render)
- [保持在线](#保持在线)
- [环境变量](#环境变量)
- [开启 AI 学术助教的大模型问答](#开启-ai-学术助教的大模型问答)
- [开启数学竞赛真题在线阅读](#开启数学竞赛真题在线阅读)
- [开启管理后台的内容管理](#开启管理后台的内容管理)
- [数据与持久化](#数据与持久化)
- [更新与回滚](#更新与回滚)
- [常见问题](#常见问题)

## 部署到 Render

### 方式一：Blueprint（推荐）

1. Fork 本仓库。
2. 在 Render 控制台选择 **New → Blueprint**，连接 GitHub 并选择仓库。Render 会读取仓库里的 `render.yaml`，创建一个 Free 计划的 Web Service：
   - 构建命令：`pip install -r requirements.txt`
   - 启动命令：`uvicorn unified_server:app --host 0.0.0.0 --port $PORT`
   - Python 版本：3.12
   - `CYJY_SECRET_KEY`：自动生成随机值
3. `render.yaml` 中标记为 `sync: false` 的变量（AI、真题阅读与内容管理相关）会提示填写，可以先留空，之后在 Environment 页面补充。
4. 在 Environment 中添加 `CYJY_ADMIN_PASSWORD`，设置管理员密码。需要在网站上编辑页面、上传文档时，再按 [开启管理后台的内容管理](#开启管理后台的内容管理) 添加 `CYJY_GITHUB_TOKEN`。
5. 部署完成后访问 `https://<服务名>.onrender.com/health`，返回 `"status": "ok"` 即表示服务正常。

### 方式二：手动创建 Web Service

在 Render 控制台选择 **New → Web Service**，选择仓库后填写：

| 项目 | 值 |
|------|----|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn unified_server:app --host 0.0.0.0 --port $PORT` |
| Instance Type | Free |

并在 Environment 中至少添加：

| 变量 | 值 |
|------|----|
| `PYTHON_VERSION` | `3.12.11`（Render 默认的 Python 版本可能与依赖不兼容） |
| `CYJY_SECRET_KEY` | 一段足够长的随机字符串 |
| `CYJY_ADMIN_PASSWORD` | 管理员密码 |

### 健康检查

`GET /health` 返回服务状态：

```json
{
  "status": "ok",
  "rate_limiting": "enabled",
  "ai": "llm",
  "content": "github",
  "timestamp": "2026-09-26T15:00:00"
}
```

其中 `ai` 为 `llm` 表示 AI 助教已接入大模型，为 `basic` 表示仍是基础模式；`content` 表示管理后台内容修改的保存位置：`github` 为提交到 GitHub 仓库，`local` 为写入本地文件，`readonly` 表示线上没有配置令牌、暂时只读。

## 保持在线

Render 免费实例在 15 分钟无访问后会休眠，之后的第一次访问需要大约 50 秒冷启动。可以用 [UptimeRobot](https://uptimerobot.com) 定时访问来避免休眠：

1. 注册 UptimeRobot 免费账号，点击 **Add New Monitor**；
2. Monitor Type 选 `HTTP(s)`，URL 填 `https://<服务名>.onrender.com/health`，间隔 5 分钟；
3. 保存后状态变为 **Up** 即可。

UptimeRobot 默认发送 HEAD 请求，服务端已通过 `_HeadSupportMiddleware` 兼容。

## 环境变量

本地运行时，可以把变量写进项目根目录的 `.env` 文件（参考 [`.env.example`](../.env.example)），启动时会自动读取；线上在 Render 的 Environment 页面设置。

### 基础

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CYJY_SECRET_KEY` | 自动生成 | JWT 签名密钥。未设置时会生成并保存到 `.secret_key` 文件；线上应固定设置，否则每次重启后已登录的用户都需要重新登录 |
| `CYJY_ADMIN_PASSWORD` | `admin123` | 管理员账号 `admin` 的初始密码，在数据库为空时创建。默认值只适合本地开发，线上务必设置 |
| `CYJY_RECOVERY_KEY` | 空 | 恢复密钥，用于 `POST /api/v1/auth/forgot-password` 在不登录的情况下重置密码。未设置时该接口关闭 |
| `CYJY_CORS_ORIGINS` | 本地地址与线上域名 | 允许跨域访问的来源，多个用逗号分隔 |
| `PORT` | `8888` | 监听端口，Render 会自动设置 |
| `RENDER` | — | Render 自动设置。检测到后数据库改存到 `/tmp` |

### AI 学术助教

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DOUBAO_API_KEY` | 空 | 豆包（火山方舟）的 API Key |
| `DOUBAO_ENDPOINT_ID` | 空 | 推理接入点 ID（`ep-...`）或模型名 |
| `CYJY_AI_BASE_URL` | 火山方舟地址 | 改用其他 OpenAI 兼容服务时填写其接口地址 |
| `CYJY_AI_API_KEY` | 空 | 其他服务的 API Key，设置后优先于 `DOUBAO_API_KEY` |
| `CYJY_AI_MODEL` | 空 | 其他服务的模型名，设置后优先于 `DOUBAO_ENDPOINT_ID` |

### 数学竞赛真题库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CYJY_GDRIVE_API_KEY` | 空 | Google API 密钥（需启用 Google Drive API）。设置后直接读取公开的 Google Drive 文件夹 |
| `CYJY_MATH_DRIVE_URL` | 项目的真题文件夹 | 真题所在的公开 Drive 文件夹链接，既是页面上的下载入口，也是 Drive 直读的文件夹 |
| `CYJY_MATH_DRIVE_FOLDER` | 空 | 直接指定 Drive 文件夹 ID，覆盖从上一项链接中解析出的 ID |
| `CYJY_MATH_FILES_URL` | 空 | Cloudflare R2 等公网存储的地址，设置后优先于 Google Drive |
| `CYJY_MATH_PROXY` | `auto` | 本地运行时，如果 8088 端口的旧版真题服务在运行，`/math` 默认转发过去；设为 `off` 始终使用内置阅读器 |
| `CYJY_BACKEND_URL` | `http://127.0.0.1:8088` | 旧版真题服务的地址 |

### 管理后台内容管理

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CYJY_GITHUB_TOKEN` | 空 | GitHub 令牌（只需本仓库的 Contents 读写权限）。设置后，管理后台的修改会提交到仓库，上传的文件保存到仓库 Release。线上未设置时内容管理为只读 |
| `CYJY_GITHUB_REPO` | `hanjiongmin-stack/chongyue-jianyuan` | 保存内容的仓库。Fork 部署时改成自己的仓库 |
| `CYJY_GITHUB_BRANCH` | `main` | 提交到的分支，应与 Render 部署的分支一致 |
| `CYJY_CONTENT_LOCAL_WRITE` | 空 | 设为 `1` 时，线上即使没有令牌也直接写本地文件。只在挂载了持久化磁盘时使用 |
| `CYJY_CONTENT_SYNC` | 空 | 设为 `1` 时，本地运行也会在启动时从仓库同步内容文件（线上总是同步） |

### 其他

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GITHUB_TOKEN` | 空 | 科研孵化页通过站内代理访问 GitHub API，配置令牌后速率限制更宽松 |

## 开启 AI 学术助教的大模型问答

每个页面右下角的 AI 学术助教默认是基础模式，只能回答平台使用问题、检索知识库资源。接入大模型后，才能回答学科问题、推导公式、解释代码，并支持多轮对话。

1. 打开 [火山方舟控制台](https://console.volcengine.com/ark)，创建 API Key，并开通一个豆包模型（或创建推理接入点，记下 `ep-...`）。
2. 在 Render → Environment 添加 `DOUBAO_API_KEY` 和 `DOUBAO_ENDPOINT_ID`，保存并重新部署。
3. 访问 `/health`，`"ai"` 显示 `"llm"` 即已生效。

也可以换成其他 OpenAI 兼容的服务，例如 DeepSeek：

```bash
CYJY_AI_BASE_URL=https://api.deepseek.com
CYJY_AI_API_KEY=<你的 API Key>
CYJY_AI_MODEL=deepseek-chat
```

提问后如果显示「AI 服务暂时不可用（状态码）」，可以在日志中搜索 `AI API error` 查看原因：401 表示密钥无效，404 表示模型或接入点不存在，403 表示没有权限或账户欠费，429 表示调用频率或额度超限。

## 开启数学竞赛真题在线阅读

`/math` 内置了基于 PDF.js 的阅读器。真题文件体积较大，不放在仓库里。下面两种方式任选其一，服务端都会同源转发文件并支持分段加载（Range）。两种都没有配置时，页面只显示目录（`math_catalog.json`），并引导到 Google Drive 下载。

### 方式一（推荐）：直接读取 Google Drive 公开文件夹

文件已经在 Google Drive 上，不需要再上传，也不需要绑定银行卡。服务端通过 Drive API 按文件夹结构生成目录，Drive 中新增的文件最多 30 分钟后会自动出现。

1. 确认 Drive 文件夹的共享设置为「知道链接的任何人 → 查看者」。
2. 打开 [Google Cloud Console](https://console.cloud.google.com/)，新建或选择一个项目，在「API 和服务 → 库」中搜索并启用 **Google Drive API**。
3. 在「API 和服务 → 凭据 → 创建凭据 → API 密钥」中创建密钥。建议在「API 限制」里只勾选 Google Drive API；「应用限制」保持「无」，否则服务器发出的请求会被拒绝。
4. 在 Render → Environment 添加 `CYJY_GDRIVE_API_KEY`，保存并重新部署。

文件夹第一层按年份或赛事分子文件夹；如果外面多包了一层文件夹，也能自动识别。部署后页面右上角显示「Google Drive · 在线直读」即已生效。如果仍显示「目录浏览」，在日志中搜索 `Google Drive` 查看原因：

| 日志中的错误 | 原因 |
|--------------|------|
| `HTTP 400 badRequest` | API 密钥无效 |
| `HTTP 403 accessNotConfigured` | 密钥所在项目没有启用 Google Drive API |
| `HTTP 403 forbidden` | 密钥设置了「网站」类的应用限制 |
| `HTTP 404` 或「文件夹为空或未公开共享」 | 文件夹没有设为公开共享 |

### 方式二：托管到 Cloudflare R2

R2 有 10 GB 免费额度，下行流量免费；开通 R2 需要在 Cloudflare 账户中绑定付款方式。

1. **Cloudflare 控制台**：R2 → 创建 Bucket（默认名 `chongyue-math`）→ Settings → Public access 开启 `R2.dev subdomain`，记下 `https://pub-xxxx.r2.dev`；再在 *Manage R2 API Tokens* 创建 “Object Read & Write” 令牌，记下 Access Key ID、Secret Access Key 与 Account ID。
2. **在存放真题文件的电脑上上传**（文件夹第一层按年份或赛事分类）：

   ```bash
   pip install boto3
   export CYJY_R2_ACCESS_KEY=...  CYJY_R2_SECRET_KEY=...  CYJY_R2_ACCOUNT_ID=...
   export CYJY_R2_PUBLIC_URL=https://pub-xxxx.r2.dev      # 可选，用于上传后的公网自检
   python upload_math_to_r2.py --src "<真题文件夹>"         # 默认读取 static/uploads/10
   ```

   已上传且大小相同的文件会自动跳过，可以反复运行；结束后会更新 `math_catalog.json`（含文件大小）。
3. **提交**更新后的 `math_catalog.json`，并在 Render → Environment 添加 `CYJY_MATH_FILES_URL=https://pub-xxxx.r2.dev`，重新部署。

### 本地运行时

如果 `static/uploads/10/` 下有真题文件，页面会直接读取本地文件，优先级最高。如果同时运行着旧的 8088 真题服务，`/math` 默认转发过去；设置 `CYJY_MATH_PROXY=off` 或访问 `/math/?viewer=builtin` 可以强制使用内置阅读器。

## 开启管理后台的内容管理

管理员登录后打开 `/admin`，可以在网站上完成日常的内容维护：

| 标签页 | 用途 |
|--------|------|
| 学习资源 | 新建、编辑、下架学习资源，上传附件（PDF、Word、PPT、代码等），资源详情页可在线预览 |
| 页面编辑 | 修改任意页面及公共导航、页脚的 HTML，带实时预览、历史版本和一键恢复 |
| 文件库 | 上传文件并复制链接，插入到页面中；学习资源的附件也在这里 |
| 真题库 | 查看数学竞赛真题库的文件来源和统计，Google Drive 中增删文件后立即刷新目录 |

Render 免费实例的磁盘是临时的，直接写在服务器上的修改会在重启后丢失，所以线上需要一个 GitHub 令牌，把修改保存到仓库里。没有配置令牌时，这几个标签页只能查看、不能修改；「用户管理」和「精英审批」不受影响。

### 创建令牌

1. 登录 GitHub，打开 **Settings → Developer settings → Personal access tokens → Fine-grained tokens**，点击 **Generate new token**。
2. 填写：
   - **Token name**：例如 `chongyue-jianyuan-render`；
   - **Expiration**：按需选择。令牌过期后保存会失败，需要重新生成并更新 Render 中的变量；
   - **Repository access**：选 **Only select repositories**，只勾选本仓库；
   - **Permissions → Repository permissions → Contents**：选 **Read and write**（Metadata 只读会自动加上），其他权限保持 No access。
3. 点击 **Generate token**，复制以 `github_pat_` 开头的令牌。令牌只显示一次。

### 配置到 Render

1. 在 Render 服务的 **Environment** 页面添加 `CYJY_GITHUB_TOKEN`，值为上一步的令牌。Fork 部署时同时添加 `CYJY_GITHUB_REPO=<你的用户名>/<仓库名>`。
2. 选择 **Save and deploy**，等待部署完成。
3. 访问 `/health`，`"content"` 显示 `"github"` 即已生效；`/admin` 顶部的提示也会变成「修改会提交到 GitHub 仓库」。

令牌只保存在 Render 的环境变量里，不要写进仓库或发给他人。泄露后在 GitHub 的令牌页面删除它，再生成新的替换即可。

### 修改保存在哪里

- **页面与学习资源**：每次保存都是一次提交到 `main` 分支的 commit（页面对应 `static/` 下的 HTML，学习资源对应 `seed_resources.json`；提交者是令牌所属的 GitHub 账号，提交信息里注明操作的管理员），同时写入正在运行的实例，刷新页面即可看到。提交信息末尾带 `[skip render]`，Render 不会因此重新部署，用户数据也就不会被清空。
- **上传的文件**：保存为仓库 Release `site-files` 的附件，第一次上传时自动创建（标记为预发布），不会增大仓库体积。网站通过 `/files/<文件编号>` 访问这些文件，请不要删除这个 Release。单个文件不超过 50 MB，出于安全考虑不接受 HTML、SVG、JS 等可能在浏览器中执行脚本的文件。
- **重启之后**：实例启动时会比较仓库与本地的内容文件，把后台改过的页面和学习资源同步下来，所以重启、休眠唤醒或重新部署都不会丢失修改。
- **历史版本**：每次保存就是一次提交。在「页面编辑」中点击「历史版本」可以查看任意一次保存的内容并恢复，也可以在 GitHub 的提交记录里查看。

后台的提交会直接进入 `main`。在本地修改同一个文件之前，先执行 `git pull`，避免冲突。

### 本地开发

本地运行且没有设置令牌时，修改直接写入项目目录下的文件（`static/*.html`、`seed_resources.json`），用 git 自行提交即可；上传的文件保存在 `static/uploads/files/`，已被 `.gitignore` 忽略，只在本机可用。本地模式没有「历史版本」，请使用 `git log` 查看。本地也设置了 `CYJY_GITHUB_TOKEN` 时，行为与线上相同，修改会直接提交到仓库。

## 数据与持久化

- **本地**：数据库位于 `data/chongyue.db`，会一直保留。
- **Render 免费实例**：文件系统是临时的，数据库位于 `/tmp/chongyue.db`。实例重启、重新部署或休眠后再唤醒，数据库都会被重建。注册用户、收藏、学习进度、科研孵化圈申请都不会保留；管理员账号会按 `CYJY_ADMIN_PASSWORD` 重新创建，在个人中心修改过的管理员密码也会恢复。

通过管理后台修改的页面、学习资源和上传的文件不存放在数据库里，配置了 `CYJY_GITHUB_TOKEN` 后会保存到 GitHub 仓库，重启后自动恢复，见 [开启管理后台的内容管理](#开启管理后台的内容管理)。

目前代码只支持 SQLite。需要长期保存用户数据时，可以使用 Render 付费实例的持久化磁盘，并把数据库路径指向磁盘目录（见 `database.py`）。

## 更新与回滚

- `render.yaml` 开启了 `autoDeploy`，推送到 `main` 分支后 Render 会自动重新部署，通常 3～5 分钟生效。管理后台产生的提交带 `[skip render]`，不会触发部署。
- 需要回滚时，在 Render 服务的 **Events** 页面找到之前成功的部署，点击 **Rollback**。

## 常见问题

| 现象 | 原因 | 处理 |
|------|------|------|
| 部署日志出现 `Exited with status 3` | Render 默认的 Python 版本与依赖不兼容 | 设置 `PYTHON_VERSION=3.12.11` |
| `unable to open database file` | Render 的项目目录只读 | 代码检测到 `RENDER` 环境变量后会自动改用 `/tmp/chongyue.db`，确认该变量存在 |
| UptimeRobot 显示 Down（405） | 监控使用 HEAD 请求 | 服务端已兼容，确认监控地址正确（建议 `/health`） |
| 首次访问很慢 | 免费实例休眠后冷启动 | 配置 [UptimeRobot](#保持在线) |
| 登录提示「操作太频繁」 | 认证接口限流（每分钟 10 次） | 稍等一分钟再试 |
| `/health` 中 `"ai": "basic"` | 没有读到大模型相关变量 | 检查变量名拼写、前后空格，保存后重新部署 |
| 真题库显示「目录浏览 · 在线阅读准备中」 | 未配置文件来源，或读取失败 | 见 [开启数学竞赛真题在线阅读](#开启数学竞赛真题在线阅读) |
| 管理后台提示「暂时只读」 | 线上没有配置 `CYJY_GITHUB_TOKEN` | 见 [开启管理后台的内容管理](#开启管理后台的内容管理) |
| 保存时提示「GitHub 拒绝了……请求（401 或 403）」 | 令牌过期、被删除，或没有授予本仓库的 Contents 读写权限 | 重新生成令牌并更新 Render 中的 `CYJY_GITHUB_TOKEN` |
| 保存时提示「文件在你编辑期间已被修改」 | 这段时间内有另一次保存或代码提交改了同一个文件 | 复制自己的修改，重新加载页面后再合并保存 |
| 保存时提示「保存文件失败（GitHub 返回 409 …）」 | `main` 分支开启了分支保护或规则集，不允许直接提交 | 在仓库设置中允许自己绕过该规则 |
