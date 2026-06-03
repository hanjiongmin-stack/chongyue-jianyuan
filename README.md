# 崇岳鉴渊 ChongYue JianYuan v2.0.0

> 大学生学习资源共享平台 — 公网知识库 + AI 编程 + 科研孵化
>
> **在线地址**: https://chongyue-jianyuan.onrender.com  
> **部署费用**: ¥0/月（Render 免费套餐 + UptimeRobot 保活）  
> **本地启动**: `python unified_server.py` → http://127.0.0.1:8888

---

## 1. 项目文件清单

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
│       ├── pricing.html        平台通道（定价对比）
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
│       ├── assets/            静态资源（favicon/头像/简历）
│       └── uploads/           用户上传文件（gitignore）
│
├── 运维层
│   ├── render.yaml             Render 一键部署配置
│   ├── runtime.txt             Python 3.12.0
│   ├── requirements.txt        7 个 Python 依赖
│   ├── .gitignore              排除密钥/DB/日志/上传
│   ├── start_all.bat           本地一键启动脚本
│   └── install_requirements.bat 依赖安装脚本
│
├── 运行时目录（gitignore，自动生成）
│   ├── data/chongyue.db        SQLite 数据库
│   ├── logs/                   服务日志
│   └── .secret_key             JWT 密钥
│
└── 临时文件
    └── tags_full.json          标签导出（已删除）
```

---

## 2. 系统架构

```
                         ┌──────────────────────────────────┐
                         │      Render.com (云端)            │
                         │  ┌────────────────────────────┐  │
                         │  │   UptimeRobot 每5分钟 ping  │  │
                         │  │   ↓ HEAD /                  │  │
                         │  │   uvicorn :$PORT            │  │
                         │  │   ├── _HeadSupportMiddleware│  │
                         │  │   │   (HEAD→GET + 清空body) │  │
                         │  │   │                         │  │
                         │  │   ├── SecurityHeadersMW     │  │
                         │  │   ├── CORSMiddleware        │  │
                         │  │   │                         │  │
                         │  │   ├── 16 条页面路由          │  │
                         │  │   ├── 26 条 API v1 路由     │  │
                         │  │   ├── 6 条反向代理路由       │  │
                         │  │   │   (/math /pdf /api →    │  │
                         │  │   │    8088 数学竞赛服务)    │  │
                         │  │   ├── 1 条 GitHub API 代理   │  │
                         │  │   │                         │  │
                         │  │   ├── StaticFiles           │  │
                         │  │   │   /assets /uploads      │  │
                         │  │   │                         │  │
                         │  │   └── SQLite /tmp/          │  │
                         │  │       chongyue.db           │  │
                         │  └────────────────────────────┘  │
                         └──────────────────────────────────┘
                                       │
                                       ▼
                             https://xxx.onrender.com
                                       │
                              ┌────────┴────────┐
                              │    浏览器访问     │
                              └─────────────────┘
```

---

## 3. 数据库结构（7 张表）

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
┌──────────────┐    │ author           │  │ ├──────────────────┤
│    users     │    │ source           │  │ │ resource_id (FK) │
├──────────────┤    │ difficulty       │  │ │ tag_id (FK)      │
│ id (PK)      │    │ view_count       │  │ └──────────────────┘
│ username(UQ) │    │ download_count   │
│ email (UQ)   │    │ is_featured      │
│ hashed_pw    │    │ status           │    ┌──────────────────┐
│ display_name │    │ created_at       │    │ token_blacklist  │
│ avatar_url   │    │ updated_at       │    ├──────────────────┤
│ is_active    │    └──────────────────┘    │ id (PK)          │
│ is_admin     │            │               │ jti (UQ)         │
│ created_at   │            │               │ user_id          │
└──────────────┘    ┌───────┴───────┐       │ token_type       │
        │           │               │       │ expires_at       │
        │      ┌────┴────┐    ┌─────┴─────┐ │ blacklisted_at   │
        ├──────┤favorites│    │ progress  │ └──────────────────┘
        │      ├─────────┤    ├───────────┤
        │      │user(FK) │    │ id (PK)   │
        │      │res(FK)  │    │ user (FK) │
        │      │created  │    │ res (FK)  │
        │      └─────────┘    │ status    │
        │                     │ percent   │
        │                     │ started   │
        │                     │ completed │
        │                     └───────────┘
```

**种子数据**：启动时如果数据库为空，自动注入 **10 个分类 + 50 个标签 + 42 条资源**。

---

## 4. API 接口全览（51 条路由）

### 4.1 页面路由（16 条）

| 方法 | 路径 | 功能 | HTML 文件 |
|------|------|------|-----------|
| GET | `/` | 首页 | index.html |
| GET | `/knowledge` | 资源列表 | knowledge.html |
| GET | `/knowledge/{id}` | 资源详情 | knowledge-detail.html |
| GET | `/login` | 登录/注册 | login.html |
| GET | `/knowledge-base` | 多维知识库 | knowledge-base.html |
| GET | `/research` | 科研孵化 | research.html |
| GET | `/profile` | 个人中心 | profile.html |
| GET | `/pricing` | 定价页 | pricing.html |
| GET | `/pricing/start` | 新手池 | pricing-start.html |
| GET | `/pricing/pro` | 进阶舱 | pricing-pro.html |
| GET | `/pricing/elite` | 科研孵化圈 | pricing-elite.html |
| GET | `/pricing/partner` | 校园合伙人 | pricing-partner.html |
| GET | `/ai-coding` | AI 编程专区 | ai-coding.html |
| GET | `/python-course` | Python 课程 | python-course.html |
| GET | `/chemistry` | 化学子站首页 | chemistry/index.html |
| GET | `/chemistry/{page}` | 化学子页面 | chemistry/*.html |

### 4.2 认证 API（4 条）

| 方法 | 路径 | 功能 | 限流 |
|------|------|------|------|
| POST | `/api/v1/auth/register` | 注册新用户 | 10/min |
| POST | `/api/v1/auth/login` | 登录 | 10/min |
| POST | `/api/v1/auth/refresh` | 刷新 token | - |
| POST | `/api/v1/auth/logout` | 登出（JWT 黑名单） | - |

### 4.3 用户 API（11 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/users/me` | 获取当前用户信息 |
| PUT | `/api/v1/users/me` | 更新显示名/头像 |
| GET | `/api/v1/users/me/favorites` | 收藏列表（分页） |
| POST | `/api/v1/users/me/favorites/{id}` | 添加收藏 |
| DELETE | `/api/v1/users/me/favorites/{id}` | 取消收藏 |
| GET | `/api/v1/users/me/favorites/{id}/check` | 检查是否收藏 |
| GET | `/api/v1/users/me/progress` | 所有学习进度 |
| GET | `/api/v1/users/me/progress/{id}` | 单个资源进度 |
| POST | `/api/v1/users/me/progress/{id}` | 设置/更新进度 |

### 4.4 资源 API（6 条）

| 方法 | 路径 | 功能 | 特点 |
|------|------|------|------|
| GET | `/api/v1/resources` | 资源列表 | 筛选(分类/标签/难度/推荐) + 搜索 + 排序 + 分页 |
| GET | `/api/v1/resources/featured` | 推荐资源 | Top 6 |
| GET | `/api/v1/resources/{id}` | 资源详情 | 含内容 + 浏览量+1 |
| GET | `/api/v1/resources/{id}/files` | 文件列表 | 含大小/预览类型 |
| POST | `/api/v1/resources/{id}/upload` | 上传文件 | ≤100MB，限流 5/min |
| GET | `/api/v1/resources/{id}/preview/{filename}` | PPT 预览 | python-pptx 渲染为 HTML |

### 4.5 分类 & 标签 API（4 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v1/categories` | 全部分类（含资源数） |
| GET | `/api/v1/categories/{slug}` | 分类详情 |
| GET | `/api/v1/tags` | 全部标签（含资源数） |
| GET | `/api/v1/tags/{slug}` | 标签详情 |

### 4.6 AI 助手 API（1 条）

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/v1/ai/chat` | AI 对话（37 条知识库关键词匹配 + SQL 全文搜索） |

### 4.7 代理 & 运维路由

| 方法 | 路径 | 功能 |
|------|------|------|
| ALL | `/math`, `/math/{path}` | 反向代理 → 数学竞赛服务 (8088) |
| ALL | `/pdf`, `/pdf/{path}` | PDF 文件代理 |
| ALL | `/api`, `/api/{path}` | 竞赛 API 代理 |
| GET | `/api/v1/github/{path}` | GitHub API 代理（内存缓存） |
| GET | `/health` | 健康检查 |
| GET | `/organic.html` | 重定向 → /chemistry/organic.html |

---

## 5. 中间件链（5 层，按执行顺序）

```
请求 → uvicorn
       │
       ├─ 1. CORSMiddleware         跨域白名单
       ├─ 2. SecurityHeadersMW      XSS/Frame/Referrer 安全头
       ├─ 3. _HeadSupportMiddleware  HEAD→GET 转换（UptimeRobot 兼容）
       │
       ├─ 路由匹配
       │   ├─ 页面路由 (@app.get)
       │   ├─ API 路由 (APIRouter)
       │   ├─ 代理路由 (@app.api_route)
       │   └─ StaticFiles (/assets, /uploads)
       │
       └─ 全局异常处理
           ├─ 404 / 500 / 429  友好错误页
           └─ Exception        全局兜底
```

---

## 6. 安全措施

| 机制 | 实现 | 位置 |
|------|------|------|
| JWT 认证 | access (30min) + refresh (7d)，含 JTI 黑名单 | auth.py |
| 密码哈希 | bcrypt | auth.py |
| 速率限制 | 认证 10/min，AI 20/min，上传 5/min（滑动窗口） | security.py |
| 文件名消毒 | 路径注入防护，unicode 正规化 | security.py |
| 安全响应头 | nosniff / SAMEORIGIN / XSS / Referrer-Policy | security.py |
| 全局异常 | 不暴露 Python Traceback | unified_server.py |
| 密钥管理 | 环境变量 > .secret_key 文件 > 自动生成 | security.py |
| 邮箱校验 | 正则 + 唯一性约束 | routers/auth.py |

---

## 7. 部署架构

```
GitHub (源码)                Render.com (免费云)
┌──────────────┐    push    ┌─────────────────────────┐
│ main 分支     │──────────►│ Auto Deploy              │
│ 14 .py        │           │ ├─ pip install           │
│ 19 .html      │           │ ├─ uvicorn :$PORT        │
│ 2 .json (seed)│           │ ├─ SQLite → /tmp         │
│ render.yaml   │           │ └─ auto_seed() 播种      │
└──────────────┘           └──────────┬──────────────┘
                                      │
                          ┌───────────┴───────────┐
                          │  UptimeRobot (免费)    │
                          │  HEAD / 每5分钟        │
                          │  防止15分钟自动休眠     │
                          └───────────────────────┘
```

**更新流程**：
```bash
git add . && git commit -m "更新内容" && git push
# Render 自动检测 → 3-5 分钟后上线
```

---

## 8. Git 提交历史

```
a1dcec1  fix: add HEAD request support via ASGI middleware for UptimeRobot
8adc6d2  Fix: slug自动生成+上传目录创建
6910fc0  fix: tag slug NOT NULL + uploads dir auto-create on Render
9804b8c  fix: SQLite path to /tmp on Render, local data/ dir otherwise
c0df066  Initial commit: chongyue-jianyuan v2.0.0 - FastAPI + Render-ready
```

---

## 9. 代码统计

| 类型 | 文件数 | 代码行数 |
|------|--------|---------|
| Python | 14 | 2,271 |
| HTML | 19 | 8,623 |
| JSON (种子数据) | 2 | 791 |
| **合计** | **35** | **11,685** |

> 不含二进制（图片/PDF/ZIP 等上传文件）

---

## 10. 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python unified_server.py
# → http://127.0.0.1:8888

# 或一键启动（含数学竞赛后端 + Cloudflare 隧道）
start_all.bat
```

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8888 | 监听端口（Render 自动设置） |
| `RENDER` | (空) | Render 环境检测 → DB 路径切换到 /tmp |
| `CYJY_SECRET_KEY` | 自动生成 | JWT 签名密钥 |
| `CYJY_BACKEND_URL` | http://127.0.0.1:8088 | 数学竞赛后端地址 |
| `CYJY_CORS_ORIGINS` | localhost:8888,3000,5173 | CORS 白名单 |
| `GITHUB_TOKEN` | (空) | GitHub API 认证令牌（提升 Rate Limit） |

---

## 11. 技术栈

| 层面 | 技术 | 用途 |
|------|------|------|
| 框架 | FastAPI 0.136 | Web 框架 |
| 服务器 | Uvicorn 0.46 | ASGI |
| ORM | SQLAlchemy 2.0 | 数据库 |
| 数据库 | SQLite (WAL 模式) | 存储 |
| 认证 | python-jose + passlib | JWT + bcrypt |
| 验证 | Pydantic v2 | 请求/响应模型 |
| 部署 | Render Free Tier | 云托管 |
| 保活 | UptimeRobot | 防休眠 ping |
| 前端 | 纯 HTML/CSS/JS | 19 个页面 |
| 预览 | python-pptx | PPT → HTML |

---

## 许可

本项目仅用于个人学习与交流。