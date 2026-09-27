# 开发文档

本文介绍项目的代码结构、前后端约定、接口和数据模型，供参与开发的同学参考。部署与配置见 [部署指南](deployment.md)。

- [目录结构](#目录结构)
- [请求处理流程](#请求处理流程)
- [前端约定](#前端约定)
- [新增一个页面](#新增一个页面)
- [接口一览](#接口一览)
- [数据模型](#数据模型)
- [安全机制](#安全机制)
- [本地开发提示](#本地开发提示)

## 目录结构

```
.
├── unified_server.py        # 应用入口：中间件、页面路由、真题库文件服务、GitHub 代理、错误页、健康检查
├── routers/                 # API 路由（均挂载在 /api/v1 下）
│   ├── auth.py              #   注册、登录、令牌刷新、登出、恢复密钥重置密码
│   ├── users.py             #   个人资料、修改密码、收藏、学习进度
│   ├── resources.py         #   学习资源列表与详情、附件上传与在线预览
│   ├── categories.py        #   分类
│   ├── tags.py              #   标签
│   ├── ai.py                #   AI 学术助教（流式问答、知识库检索）
│   ├── admin.py             #   管理后台：用户管理、科研孵化圈申请审核
│   ├── content.py           #   管理后台内容管理：页面编辑、文件库、学习资源增删改；公开的 /files 文件访问
│   └── elite.py             #   科研孵化圈申请
├── models.py                # SQLAlchemy 数据模型
├── schemas.py               # Pydantic 请求 / 响应模型
├── database.py              # 数据库连接、首次启动时的初始化与示例数据
├── auth.py                  # JWT 签发与校验、密码哈希、令牌黑名单
├── security.py              # 接口限流、安全响应头、文件名清理、密钥管理
├── content_store.py         # 内容存储：把后台修改提交到 GitHub 仓库、文件存到 Release，启动时同步；无令牌时读写本地
├── partials.py              # 公共片段注入与静态资源版本号（页面响应和后台预览共用）
├── seed_categories_tags.json、seed_resources.json   # 初始分类、标签与学习资源
├── math_catalog.json        # 真题库目录（未接入文件存储时使用）
├── upload_math_to_r2.py     # 把真题文件上传到 Cloudflare R2 并生成目录
├── static/                  # 前端
│   ├── *.html               #   各板块页面
│   ├── partials/            #   导航、页脚、AI 助教等公共片段，由服务端注入页面
│   ├── assets/              #   设计系统 cyjy.css / cyjy.js、管理后台 admin-content.js、化学讲义 chem.css / chem.js、PDF.js、图标
│   └── chemistry/           #   高等化学五份讲义
├── docs/                    # 部署与开发文档、README 截图
├── archive/                 # 制作讲义用过的原始素材和一次性脚本（运行不依赖）
├── render.yaml              # Render Blueprint 配置
├── start_all.bat、install_requirements.bat   # Windows 本地启动与安装脚本
└── requirements.txt
```

运行时自动生成、不纳入版本管理的目录：`data/`（SQLite 数据库）、`logs/`、`.secret_key`、`static/uploads/`（上传文件与本地真题文件）。

## 请求处理流程

所有请求都由 `unified_server.py` 中的 FastAPI 应用处理，依次经过以下中间件（由外到内）：

| 顺序 | 中间件 | 作用 |
|------|--------|------|
| 1 | `_HeadSupportMiddleware` | 把 HEAD 请求当作 GET 处理并去掉响应体，兼容 UptimeRobot 等监控 |
| 2 | `_SEOInjectMiddleware` | 处理 HTML 响应：注入公共片段、页面标题与描述等 SEO 信息、静态资源版本号；为 `/assets/` 设置长期缓存 |
| 3 | `GZipMiddleware` | 压缩响应（跳过 SSE 流式响应） |
| 4 | `SecurityHeadersMiddleware` | 添加 `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy` 等安全响应头 |
| 5 | `CORSMiddleware` | 跨域白名单（`CYJY_CORS_ORIGINS`） |

之后按路由分发到页面、API 或静态文件。

启动时（`lifespan`），在初始化数据库之前会先调用 `content_store.sync_from_remote()`：线上配置了 `CYJY_GITHUB_TOKEN` 时，把仓库中与本地不同的内容文件（页面 HTML、`seed_resources.json` 等）写入本地，使管理后台的修改在重启后恢复。同步最多等待 30 秒，失败时记录警告并继续使用部署时的文件。404、429、500 和未捕获的异常由全局处理器统一返回：`/api/` 下返回 JSON，其他路径返回站点风格的错误页，不会暴露 Python 调用栈。

## 前端约定

前端是原生 HTML / CSS / JavaScript，不需要构建步骤，修改后刷新页面即可看到效果。

**公共片段**：页面中的 `<!--cy:名称-->` 标记会在响应时替换为 `static/partials/名称.html` 的内容。常用片段：

| 标记 | 内容 |
|------|------|
| `<!--cy:head-->` | 公共 `<head>` 内容：字体、`cyjy.css`、主题初始化 |
| `<!--cy:nav-->` | 顶部导航（含下拉菜单和移动端菜单） |
| `<!--cy:footer-->` | 页脚与站点地图 |
| `<!--cy:tail-->` | 回到顶部按钮、AI 学术助教、`cyjy.js` |
| `<!--cy:tail-lite-->` | 同上，但不含 AI 学术助教（登录页、管理后台使用） |
| `<!--cy:chem-head-->`、`<!--cy:chem-tail-->` | 化学讲义的样式、脚本与 MathJax 配置 |

公共片段的注入逻辑在 `partials.py` 中，页面响应和管理后台的页面预览共用同一份实现。

**资源版本号**：页面中的 `%%V%%` 会替换为 `static/assets` 下 CSS / JS 内容的哈希值，写成 `cyjy.css?v=%%V%%`。静态资源设置了 7 天缓存，文件内容变化后版本号随之变化，浏览器会自动获取新文件。

**设计系统**：`static/assets/cyjy.css` 定义了颜色、字体、间距等设计变量（默认深色主题，`[data-theme="light"]` 为浅色主题）以及按钮、卡片、表单、弹窗等通用组件。新页面应优先复用这些变量和组件。

**公共脚本**：`static/assets/cyjy.js` 在 `window.CY` 上提供常用工具，例如：

| 方法 | 作用 |
|------|------|
| `CY.api(path, options)` | 调用后端接口：自动附带登录令牌、解析 JSON，访问令牌过期时自动刷新后重试 |
| `CY.esc(text)` | HTML 转义，拼接 HTML 时必须对外部数据使用 |
| `CY.toast(message, type)` | 页面提示 |
| `CY.reveal()`、`CY.observe(el, fn)` | 滚动进入视口时的动画与回调 |
| `CY.countUp(el)` | 数字滚动动画 |
| `CY.openAssistant(question)` | 打开 AI 学术助教，可预填问题 |

**第三方库**：PDF.js（`static/assets/pdfjs/`，legacy 构建，随仓库分发）用于真题阅读；MathJax 3 和 Pyodide 从 jsDelivr 按需加载。

## 新增一个页面

1. 在 `static/` 下新建 HTML 文件，参照现有页面放入 `<!--cy:head-->`、`<!--cy:nav-->`、`<!--cy:footer-->`、`<!--cy:tail-->` 等标记。
2. 在 `unified_server.py` 中添加对应的页面路由，并在 `_SEOInjectMiddleware.PAGE_META` 中填写标题和描述。
3. 需要出现在导航或页脚中时，修改 `static/partials/nav.html` 和 `footer.html`；需要被搜索引擎收录时，把地址加入 `sitemap.xml` 路由中的列表。
4. 分别在深色、浅色主题和手机宽度下检查页面，确认浏览器控制台没有报错。

## 接口一览

除特别说明外，接口都在 `/api/v1` 下，请求和响应均为 JSON。需要登录的接口在请求头中携带 `Authorization: Bearer <access_token>`。

| 模块 | 方法与路径 | 说明 |
|------|-----------|------|
| 认证 | `POST /auth/register` · `POST /auth/login` · `POST /auth/refresh` · `POST /auth/logout` | 注册、登录、刷新令牌、登出（令牌加入黑名单） |
| | `POST /auth/forgot-password` | 使用恢复密钥重置密码（需配置 `CYJY_RECOVERY_KEY`） |
| 用户 | `GET` / `PUT /users/me` · `PUT /users/me/password` | 个人资料、修改密码 |
| | `GET /users/me/favorites` · `GET /users/me/favorites/{id}/check` · `POST` / `DELETE /users/me/favorites/{id}` | 收藏 |
| | `GET /users/me/progress` · `GET` / `POST /users/me/progress/{id}` | 学习进度 |
| 学习资源 | `GET /resources` · `GET /resources/featured` · `GET /resources/{id}` | 列表（分类、标签、难度筛选与搜索、分页）、精选、详情 |
| | `GET /resources/{id}/files` · `POST /resources/{id}/upload` · `GET /resources/{id}/preview/{filename}` | 附件列表、上传（需管理员，存入文件库）、Office 文件在线预览 |
| 分类与标签 | `GET /categories` · `GET /categories/{slug}` · `GET /tags` · `GET /tags/{slug}` | 分类、标签 |
| AI 学术助教 | `POST /ai/chat` | 提问；接入大模型时返回 SSE 流式回答，可携带最近的对话历史 |
| | `GET /ai/status` | 是否已接入大模型 |
| 科研孵化圈 | `POST /elite/apply` | 提交申请 |
| 管理后台 | `GET /admin/users` · `PUT` / `DELETE /admin/users/{id}` · `PUT /admin/users/{id}/password` | 用户管理（需管理员） |
| | `GET /admin/elite-applications` · `POST /admin/elite-applications/{id}/review` | 申请审核（需管理员） |
| 内容管理 | `GET /admin/content/status` | 内容存储模式（`github` / `local`）与是否可写（需管理员，下同） |
| | `GET /admin/content/pages` · `GET` / `PUT /admin/content/page` · `POST /admin/content/page/preview` | 可编辑页面列表、读取与保存页面（携带读取时的 `sha`，被他人修改过时返回 409）、预览 |
| | `GET /admin/content/page/history` · `GET /admin/content/page/version` | 页面的历史提交、某次提交时的内容 |
| | `GET` / `POST /admin/content/files` · `DELETE /admin/content/files/{key}` | 文件库列表、上传（multipart，字段 `files`，一次最多 20 个）、删除（被学习资源引用时返回 409） |
| | `GET /admin/content/taxonomy` · `GET` / `POST /admin/content/resources` · `GET` / `PUT` / `DELETE /admin/content/resources/{id}` | 学习资源增删改（含草稿和附件），保存后重新导出 `seed_resources.json` |
| | `GET /admin/content/math` · `POST /admin/content/math/refresh` | 真题库的文件来源与统计、立即刷新 Google Drive 目录 |
| 真题库 | `GET /math/catalog` | 真题目录与当前文件来源 |
| GitHub 代理 | `GET /github/{path}` | 转发 GitHub API 请求并缓存，供科研孵化页使用 |

站点级接口：`GET /health`（健康检查）、`GET /math/files/{path}`（真题文件，支持 Range）、`GET /files/{key}`（文件库中的文件，支持 Range；PDF、图片、音视频在浏览器中打开，其他类型或加 `?download=1` 时下载）、`GET /sitemap.xml`、`GET /robots.txt`。

## 数据模型

数据库为 SQLite（WAL 模式），表结构由 `models.py` 定义，启动时自动创建。

| 表 | 说明 |
|----|------|
| `categories` | 资源分类（名称、slug、描述、排序） |
| `resources` | 学习资源（标题、描述、Markdown 正文、附件、作者、难度、浏览与下载次数、是否精选、状态） |
| `tags`、`resource_tags` | 标签及资源与标签的多对多关联 |
| `users` | 用户（用户名、邮箱、密码哈希、显示名称、是否管理员、订阅与精英身份等） |
| `favorites` | 收藏记录 |
| `progress` | 学习进度（状态、完成百分比、开始与完成时间） |
| `token_blacklist` | 已登出的令牌，过期后定期清理 |
| `elite_applications` | 科研孵化圈申请与审核结果 |

首次启动时，`database.auto_seed()` 会在对应表为空时写入示例数据：管理员账号、分类与标签（`seed_categories_tags.json`）、学习资源（`seed_resources.json`）。

学习资源以 `seed_resources.json` 为准：管理后台每次增删改资源后都会重新导出这个文件（包括资源编号、草稿状态和附件列表），Render 上数据库重建时再从文件导入，资源编号和详情页地址保持不变。`resources.attachments` 列保存附件列表（JSON，`[{key, name, size}]`，`key` 为文件库中的文件编号），旧数据库启动时会自动补上这一列。

## 安全机制

| 机制 | 实现 |
|------|------|
| 登录令牌 | JWT：访问令牌 30 分钟、刷新令牌 7 天；登出后令牌加入黑名单 |
| 密码存储 | bcrypt 哈希 |
| 接口限流 | 内存滑动窗口：认证每分钟 10 次、AI 问答 20 次、上传 5 次 |
| 输出转义 | 页面渲染外部数据（用户名、GitHub 数据、AI 回答等）前统一转义；登录后的跳转地址只允许站内路径 |
| 文件访问 | 上传文件名清理；真题文件与附件预览路径规范化，拒绝越界访问 |
| 管理后台内容 | 所有内容管理接口都要求管理员身份；页面编辑只允许已登记的 HTML 文件；上传按扩展名白名单（不含 HTML、SVG、JS 等），响应类型由扩展名决定并带 `nosniff`；页面预览在沙箱 iframe 中渲染 |
| 第三方密钥 | Google Drive、大模型和 GitHub 的密钥只在服务端使用，不会出现在页面、接口响应或日志中；下载 Release 附件时的跳转不会携带 GitHub 令牌 |
| 错误处理 | 统一错误页与 JSON 错误，不暴露调用栈 |

## 本地开发提示

- 项目根目录的 `.env` 会在启动时自动读取（不会覆盖已有的环境变量），可以参考 `.env.example` 填写。
- 首次启动会创建管理员账号 `admin`（密码为 `CYJY_ADMIN_PASSWORD`，默认 `admin123`），登录后点击导航栏的「管理后台」（或访问 `/admin`）进入管理后台。
- 本地没有设置 `CYJY_GITHUB_TOKEN` 时，管理后台的修改直接写入工作区文件，可以用 `git diff` 查看后再提交；上传的文件保存在 `static/uploads/files/`，不纳入版本管理。
- 删除 `data/chongyue.db` 即可重置本地数据库，下次启动时重新初始化。
- 把真题文件放到 `static/uploads/10/`（第一层为年份文件夹）后，`/math` 会直接读取本地文件。
- AI 学术助教没有配置大模型时以基础模式运行，可以用任意 OpenAI 兼容服务调试（见 [部署指南](deployment.md#开启-ai-学术助教的大模型问答)）。
- 项目目前没有自动化测试。提交前请在本地启动服务，打开改动涉及的页面，确认浏览器控制台没有报错，并分别检查深色、浅色主题和手机宽度下的显示效果。
