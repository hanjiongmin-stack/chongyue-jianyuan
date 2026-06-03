# 崇岳鉴渊 | 大学生科研互助平台

> 面向在校大学生的科研互助、开源练手与论文资源平台 — 零成本永久部署方案
>
> **在线地址**: https://chongyue-jianyuan.onrender.com  
> **部署费用**: ¥0/月（Render 免费套餐 + UptimeRobot 保活）  
> **本地启动**: `python unified_server.py` → http://127.0.0.1:8888

---

## 🚀 技术栈

| 层面 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.136 |
| 服务器 | Uvicorn | 0.46 |
| ORM | SQLAlchemy | 2.0 |
| 数据库 | SQLite (WAL) | 3.x |
| 认证 | python-jose + passlib | JWT + bcrypt |
| 部署 | Render Free Tier | 新加坡节点 |
| 保活 | UptimeRobot | 免费版 |
| 版本控制 | GitHub | 公共仓库 |

---

## 📋 快速部署全流程（4 步完成）

### 第 1 步：创建 GitHub 仓库并推送代码

1. 打开 https://github.com/new
2. **Repository name**: `chongyue-jianyuan`
3. **Visibility**: `Public`
4. ⚠️ **重要**: 不要勾选任何初始化选项（README / .gitignore / License）
5. 点击 **Create repository**
6. 打开 CMD 执行：

```bash
cd "D:\Claude\制作中心"
git init
git add .
git commit -m "Initial commit: 完整项目代码"
git remote add origin https://github.com/你的用户名/chongyue-jianyuan.git
git branch -M main
git push -u origin main
```

### 第 2 步：一键部署到 Render

1. 打开 https://render.com，用 GitHub 账号登录
2. 点击顶部 **New +** → **Web Service**
3. 授权后选择 `chongyue-jianyuan` 仓库，点击 **Connect**
4. Render 会自动读取 `render.yaml`，无需手动配置
5. ⚠️ **关键环境变量**（点击 Advanced → Add Environment Variable）：
   - Key: `PYTHON_VERSION`  Value: `3.12.11`
6. 点击底部 **Deploy Web Service**
7. 等待 3-5 分钟，页面顶部显示绿色的 **Your site is live** 即部署成功
8. 网站地址：`https://chongyue-jianyuan.onrender.com`

### 第 3 步：配置 UptimeRobot 防休眠（必做）

Render 免费版 15 分钟无访问会自动休眠：

1. 打开 https://uptimerobot.com，注册免费账号
2. 点击 **+ Add New Monitor**
3. 配置：
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `崇岳鉴渊-防休眠监控`
   - **URL**: `https://chongyue-jianyuan.onrender.com`
   - **Monitoring Interval**: `5 minutes`
4. 点击 **Create Monitor**
5. 等待 5 分钟，监控状态变绿色的 **Up** 即完成

> Render 首次访问有 ~50 秒冷启动，之后秒开。

### 第 4 步：验证部署

访问以下地址确认正常：
```
https://chongyue-jianyuan.onrender.com/health
```
应返回：
```json
{"status": "ok", "backend": "...", "rate_limiting": "enabled", ...}
```

---

## 📁 项目文件清单

```
制作中心/
│
├── 核心层（14 个 Python 文件 / 2,271 行）
│   ├── unified_server.py    621 行  主入口：FastAPI 应用 + 页面路由 + 反向代理
│   ├── database.py          121 行  SQLite 引擎 + 自动播种
│   ├── models.py            119 行  7 张 ORM 表
│   ├── schemas.py           130 行  Pydantic 请求/响应模型
│   ├── auth.py              138 行  JWT 认证（access/refresh token）
│   ├── security.py          140 行  速率限制 + 安全头 + 文件名消毒
│   ├── seed_data.py          29 行  资源种子脚本（Phase 2）
│   ├── seed_resources.json   42 条  学习资源初始数据
│   ├── seed_categories_tags.json   10 分类 + 50 标签（含 slug）
│   │
│   └── routers/              6 个 API 路由模块
│       ├── auth.py          120 行  注册/登录/刷新/登出
│       ├── users.py         222 行  个人信息/收藏/学习进度
│       ├── resources.py     458 行  资源列表/详情/文件上传/PPT预览
│       ├── ai.py             89 行  AI 对话助手（关键词 + 全文搜索）
│       ├── categories.py     50 行  分类列表/详情
│       └── tags.py           38 行  标签列表/详情
│
├── 前端层（19 个 HTML 文件 / 8,623 行）
│   └── static/
│       ├── index.html          首页 · 六大板块入口
│       ├── login.html          登录/注册页
│       ├── profile.html        个人中心
│       ├── knowledge.html      资源列表（筛选+搜索+分页）
│       ├── knowledge-detail.html  资源详情（收藏+进度+文件预览）
│       ├── knowledge-base.html 多维知识库
│       ├── ai-coding.html      AI 编程专区
│       ├── python-course.html  Python 课程
│       ├── research.html       科研孵化
│       ├── pricing.html        平台通道
│       ├── pricing-start.html  新手池
│       ├── pricing-pro.html    进阶舱
│       ├── pricing-elite.html  科研孵化圈
│       ├── pricing-partner.html 校园合伙人
│       │
│       ├── chemistry/          化学子站
│       │   ├── index.html
│       │   ├── organic.html    有机化学
│       │   ├── inorganic.html  无机化学
│       │   ├── analytical.html 分析化学
│       │   ├── physical.html   物理化学
│       │   └── chem-style.css
│       │
│       ├── assets/            静态资源
│       └── uploads/           用户上传文件（gitignore）
│
├── 运维层
│   ├── render.yaml             Render 一键部署配置
│   ├── runtime.txt             Python 3.12.0
│   ├── requirements.txt        7 个 Python 依赖
│   ├── .gitignore              排除密钥/DB/日志/上传
│   ├── start_all.bat           本地一键启动脚本
│   └── install_requirements.bat
│
└── 运行时目录（gitignore，自动生成）
    ├── data/chongyue.db        SQLite 数据库
    ├── logs/                   服务日志
    └── .secret_key             JWT 密钥
```

---

## 🏗 系统架构

```
                         ┌──────────────────────────────────┐
                         │      Render.com (云端)            │
                         │  ┌────────────────────────────┐  │
                         │  │   UptimeRobot 每5分钟 ping  │  │
                         │  │   ↓ HEAD /                  │  │
                         │  │   uvicorn :$PORT            │  │
                         │  │   ├── _HeadSupportMiddleware│  │
                         │  │   │   (HEAD→GET + 清空body) │  │
                         │  │   ├── SecurityHeadersMW     │  │
                         │  │   ├── CORSMiddleware        │  │
                         │  │   ├── 16 条页面路由          │  │
                         │  │   ├── 26 条 API v1 路由     │  │
                         │  │   ├── 6 条反向代理路由       │  │
                         │  │   ├── 1 条 GitHub API 代理   │  │
                         │  │   ├── StaticFiles           │  │
                         │  │   └── SQLite /tmp/          │  │
                         │  └────────────────────────────┘  │
                         └──────────────────────────────────┘
```

### 中间件链（5 层，按执行顺序）

```
请求 → uvicorn
       ├─ 1. CORSMiddleware         跨域白名单
       ├─ 2. SecurityHeadersMW      XSS/Frame/Referrer 安全头
       ├─ 3. _HeadSupportMiddleware  HEAD→GET 转换（UptimeRobot 兼容）
       ├─ 路由匹配
       │   ├─ 页面路由 (@app.get)
       │   ├─ API 路由 (APIRouter)
       │   ├─ 代理路由 (@app.api_route)
       │   └─ StaticFiles (/assets, /uploads)
       └─ 全局异常处理
           ├─ 404 / 500 / 429  友好错误页
           └─ Exception        全局兜底
```

---

## 🗄 数据库结构（7 张表）

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  categories  │    │    resources     │    │     tags     │
├──────────────┤    ├──────────────────┤    ├──────────────┤
│ id (PK)      │◄───│ category_id (FK) │    │ id (PK)      │
│ name         │    │ id (PK)          │──┐ │ name         │
│ slug (UQ)    │    │ title            │  │ │ slug (UQ)    │
│ description  │    │ slug (UQ)        │  │ └──────────────┘
│ icon         │    │ description      │  │        │
│ sort_order   │    │ content (MD)     │  │        │
└──────────────┘    │ file_url         │  │ ┌──────┴───────────┐
                    │ file_type        │  │ │  resource_tags   │
                    │ file_size        │  ├─┤ (多对多关联表)    │
┌──────────────┐    │ author           │  │ │ resource_id (FK) │
│    users     │    │ source           │  │ │ tag_id (FK)      │
├──────────────┤    │ difficulty       │  │ └──────────────────┘
│ id (PK)      │    │ view_count       │    ┌──────────────────┐
│ username(UQ) │    │ download_count   │    │ token_blacklist  │
│ email (UQ)   │    │ is_featured      │    ├──────────────────┤
│ hashed_pw    │    │ status           │    │ id (PK)          │
│ display_name │    │ created_at       │    │ jti (UQ)         │
│ avatar_url   │    │ updated_at       │    │ user_id          │
│ is_active    │    └──────────────────┘    │ token_type       │
│ is_admin     │            │               │ expires_at       │
│ created_at   │       ┌────┴────┐          └──────────────────┘
└──────────────┘  ┌────┴────┐┌───┴──────┐
                  │favorites││ progress │    种子数据（自动注入）
                  ├─────────┤├──────────┤    ├─────────────────
                  │user(FK) ││ id (PK)  │    │ 10 分类
                  │res(FK)  ││ user(FK) │    │ 50 标签
                  │created  ││ res(FK)  │    │ 42 资源
                  └─────────┘│ status   │    └─────────────────
                             │ percent  │
                             │ started  │
                             │completed │
                             └──────────┘
```

---

## 📡 API 接口全览（51 条路由）

### 页面路由（16 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/knowledge` | 资源列表（筛选+搜索+分页） |
| GET | `/knowledge/{id}` | 资源详情 |
| GET | `/login` | 登录/注册 |
| GET | `/knowledge-base` | 多维知识库 |
| GET | `/research` | 科研孵化 |
| GET | `/profile` | 个人中心 |
| GET | `/pricing` | 定价页 |
| GET | `/pricing/start` | 新手池 |
| GET | `/pricing/pro` | 进阶舱 |
| GET | `/pricing/elite` | 科研孵化圈 |
| GET | `/pricing/partner` | 校园合伙人 |
| GET | `/ai-coding` | AI 编程专区 |
| GET | `/python-course` | Python 课程 |
| GET | `/chemistry` | 化学子站 |
| GET | `/chemistry/{page}` | 化学子页面 |

### 认证 API（4 条）

| 方法 | 路径 | 功能 | 限流 |
|------|------|------|------|
| POST | `/api/v1/auth/register` | 注册 | 10/min |
| POST | `/api/v1/auth/login` | 登录 | 10/min |
| POST | `/api/v1/auth/refresh` | 刷新 token | - |
| POST | `/api/v1/auth/logout` | 登出（JWT 黑名单） | - |

### 用户 API（9 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET/PUT | `/api/v1/users/me` | 获取/更新个人信息 |
| GET | `/api/v1/users/me/favorites` | 收藏列表（分页） |
| POST | `/api/v1/users/me/favorites/{id}` | 添加收藏 |
| DELETE | `/api/v1/users/me/favorites/{id}` | 取消收藏 |
| GET | `/api/v1/users/me/favorites/{id}/check` | 检查是否收藏 |
| GET | `/api/v1/users/me/progress` | 所有学习进度 |
| GET/POST | `/api/v1/users/me/progress/{id}` | 获取/更新进度 |

### 资源 API（6 条）

| 方法 | 路径 | 功能 | 特点 |
|------|------|------|------|
| GET | `/api/v1/resources` | 资源列表 | 分类/标签/难度/推荐筛选 + 排序 + 分页 |
| GET | `/api/v1/resources/featured` | 推荐资源 | Top 6 |
| GET | `/api/v1/resources/{id}` | 资源详情 | 含 Markdown 内容，浏览量+1 |
| GET | `/api/v1/resources/{id}/files` | 文件列表 | 含大小、预览类型 |
| POST | `/api/v1/resources/{id}/upload` | 上传文件 | ≤100MB，限流 5/min |
| GET | `/api/v1/resources/{id}/preview/{filename}` | PPT 预览 | python-pptx 渲染为 HTML |

### 分类 & 标签 API（4 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/categories` | 全部分类（含资源数） |
| GET | `/api/v1/categories/{slug}` | 分类详情 |
| GET | `/api/v1/tags` | 全部标签（含资源数） |
| GET | `/api/v1/tags/{slug}` | 标签详情 |

### AI 助手 & 代理 & 运维

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/ai/chat` | AI 对话（37条知识库 + SQL搜索） |
| ALL | `/math`, `/math/{path}` | 反向代理 → 数学竞赛 (8088) |
| ALL | `/pdf`, `/pdf/{path}` | PDF 文件代理 |
| ALL | `/api`, `/api/{path}` | 竞赛 API 代理 |
| GET | `/api/v1/github/{path}` | GitHub API 代理（内存缓存） |
| GET | `/health` | 健康检查 |

---

## 🛡 安全措施

| 机制 | 实现 |
|------|------|
| JWT 认证 | access (30min) + refresh (7d)，JTI 黑名单 |
| 密码哈希 | bcrypt |
| 速率限制 | 认证 10/min，AI 20/min，上传 5/min（滑动窗口） |
| 文件名消毒 | 路径注入防护，Unicode 正规化 |
| 安全响应头 | nosniff / SAMEORIGIN / XSS / Referrer-Policy |
| 全局异常 | 不暴露 Python Traceback |
| 密钥管理 | 环境变量 > .secret_key 文件 > 自动生成 |

---

## 🐛 常见问题与踩坑记录

| 错误信息 | 原因 | 解决方法 |
|---------|------|----------|
| `Exited with status 3` | Render 默认 Python 3.14 与依赖不兼容 | 添加环境变量 `PYTHON_VERSION=3.12.11` |
| `unable to open database file` | Render 当前目录只读 | 代码已修复：检测 `RENDER` 变量，切换到 `/tmp/chongyue.db` |
| `NOT NULL constraint failed: tags.slug` | 种子数据缺少 slug | 代码已修复：`seed_categories_tags.json` 已补全所有 slug |
| `上传目录不存在` | git clone 不包含空目录 | 代码已修复：`lifespan()` 中自动 `mkdir(exist_ok=True)` |
| `UptimeRobot 显示 Down 405` | 免费版只发 HEAD | 代码已修复：ASGI 中间件将 HEAD 转 GET 并清空 body |

---

## ⚠️ 免费版限制说明

### Render 免费版
- ✅ 每月 750 小时免费额度，足够 24 小时运行
- ✅ 自动 HTTPS 证书 + 自动部署
- ❌ 15 分钟无访问自动休眠（已通过 UptimeRobot 解决）
- ❌ 数据库在实例重启时重置（`/tmp` 目录）
- ❌ 单实例，适合几十人同时访问

### UptimeRobot 免费版
- ✅ 最多 50 个监控
- ✅ 每 5 分钟检查一次
- ✅ 邮件提醒
- ❌ 只能用 HEAD 请求（已通过 `_HeadSupportMiddleware` 兼容）

---

## 🔧 日常维护

### 更新网站内容
修改本地文件后，3 条命令自动更新：
```bash
cd "D:\Claude\制作中心"
git add .
git commit -m "更新内容说明"
git push
```
Render 自动检测 GitHub 更新，3-5 分钟后生效。

### 回滚到上一个版本
1. 进入 Render 仪表盘 → 你的服务
2. **Events** 页面找到上一个成功部署
3. 点击 **Rollback** 即可回滚

### 数据备份
- 定期备份本地 `D:\Claude\制作中心` 文件夹
- Render SQLite 在 `/tmp` 目录，实例重启后重置
- 如需持久化，可升级 Render 付费数据库或使用 Supabase 免费 PostgreSQL

---

## 📊 代码统计

| 类型 | 文件数 | 代码行数 |
|------|--------|---------|
| Python | 14 | 2,271 |
| HTML | 19 | 8,623 |
| JSON (种子数据) | 2 | 791 |
| **合计** | **35** | **11,685** |

---

## 💻 本地开发

```bash
pip install -r requirements.txt
python unified_server.py
# → http://127.0.0.1:8888
```

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8888 | 监听端口（Render 自动设置） |
| `RENDER` | (空) | Render 环境检测 → DB 切换到 /tmp |
| `CYJY_SECRET_KEY` | 自动生成 | JWT 签名密钥 |
| `CYJY_BACKEND_URL` | http://127.0.0.1:8088 | 数学竞赛后端 |
| `CYJY_CORS_ORIGINS` | localhost:8888,3000,5173 | CORS 白名单 |
| `GITHUB_TOKEN` | (空) | GitHub API 认证令牌 |

---

## 📄 许可证

MIT License
