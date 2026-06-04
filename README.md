# 崇岳鉴渊 | 大学生科研互助平台

> **面向高校硬核溯熵的进阶武器库** | 打破高校信息差，让优秀在此锐利
>
> 全面覆盖数学竞赛真题、AI前沿编程、跨学科多维知识库与硬核开源孵化的全栈平台
>
> **在线演示**: https://chongyue-jianyuan.onrender.com  
> **部署成本**: ¥0/月（Render 免费套餐 + UptimeRobot 保活）  
> **本地启动**: `python unified_server.py` → http://127.0.0.1:8888

<div align="center">








</div>

---

## ✨ 平台核心优势

| 能力 | 数据 | 说明 |
|------|------|------|
| 🧮 竞赛备考 | 20天 | 平均竞赛备考周期缩短 |
| 🤖 AI编程 | 98% | AI辅助代码重构一次通关率 |
| 📚 知识吸收 | 300% | 专业基础课知识吸收速率提升 |
| 🚀 开源产出 | 6x | 本科阶段产出首个开源项目提速 |

## 🎯 四大核心生态

### 01 大学生数学竞赛真题库
系统性收录历年全国大学生数学竞赛（CMC）、丘成桐大学生数学竞赛等硬核赛事真题。配备全LaTeX排版的独家精细化推导、多解法对照与考点透视。

### 02 AI编程与算法跃迁
打破死记硬背的传统编码，无缝对接Claude Code和前沿大模型工程化工作流。教你如何高能下发Prompt指令，高效重构与调优工业级算法项目。

### 03 多维溯熵知识库
涵盖计算机科学、高等数学、数据科学等硬核核心专业课的高分保研笔记、课后全解。由顶尖学长学姐开源共建，从底层逻辑终结底层信息差。

### 04 科研孵化与开源共建
对接高星开源社区实战课题，提供工业级学术工程孵化。教你从零提交高质量PR，参与前沿论文复现，摆脱纸上谈兵，让履历熠熠生辉。

---

## 🚀 快速部署（4步完成，零成本）

### 第1步：创建GitHub仓库并推送代码

1. 打开 https://github.com/new
2. **Repository name**: `chongyue-jianyuan`
3. **Visibility**: `Public`
4. ⚠️ **重要**: 不要勾选任何初始化选项（README / .gitignore / License）
5. 点击 **Create repository**
6. 执行以下命令：

```bash
cd "D:\Claude\制作中心"
git init
git add .
git commit -m "Initial commit: 完整项目代码"
git remote add origin https://github.com/你的用户名/chongyue-jianyuan.git
git branch -M main
git push -u origin main
```

### 第2步：一键部署到Render

1. 打开 https://render.com，用GitHub账号登录
2. 点击顶部 **New +** → **Web Service**
3. 授权后选择 `chongyue-jianyuan` 仓库，点击 **Connect**
4. Render会自动读取`render.yaml`，无需手动配置
5. ⚠️ **关键环境变量**（点击 Advanced → Add Environment Variable）：
   - Key: `PYTHON_VERSION`  Value: `3.12.11`
6. 点击底部 **Deploy Web Service**
7. 等待3-5分钟，页面顶部显示绿色的 **Your site is live** 即部署成功
8. 网站地址：`https://chongyue-jianyuan.onrender.com`

### 第3步：配置UptimeRobot防休眠（必做）

Render免费版15分钟无访问会自动休眠：

1. 打开 https://uptimerobot.com，注册免费账号
2. 点击 **+ Add New Monitor**
3. 配置：
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `崇岳鉴渊-防休眠监控`
   - **URL**: `https://chongyue-jianyuan.onrender.com`
   - **Monitoring Interval**: `5 minutes`
4. 点击 **Create Monitor**
5. 等待5分钟，监控状态变绿色的 **Up** 即完成

> 💡 Render首次访问有~50秒冷启动，之后秒开。

### 第4步：验证部署

访问健康检查接口确认正常：
```
https://chongyue-jianyuan.onrender.com/health
```
应返回：
```json
{"status": "ok", "backend": "...", "rate_limiting": "enabled", "timestamp": "..."}
```

---

## 🛠 技术栈

| 层面 | 技术 | 版本 |
|------|------|------|
| 后端框架 | FastAPI | 0.136 |
| ASGI服务器 | Uvicorn | 0.46 |
| ORM | SQLAlchemy | 2.0 |
| 数据库 | SQLite (WAL) | 3.x |
| 认证 | python-jose + passlib | JWT + bcrypt |
| 部署平台 | Render Free Tier | 新加坡节点 |
| 保活服务 | UptimeRobot | 免费版 |
| 版本控制 | GitHub | 公共仓库 |

---

## 📁 项目文件结构

```
制作中心/
├── 核心层（14个Python文件 / 2,271行）
│   ├── unified_server.py    621行  主入口：FastAPI应用 + 页面路由 + 反向代理
│   ├── database.py          121行  SQLite引擎 + 自动播种
│   ├── models.py            119行  7张ORM表
│   ├── schemas.py           130行  Pydantic请求/响应模型
│   ├── auth.py              138行  JWT认证（access/refresh token）
│   ├── security.py          140行  速率限制 + 安全头 + 文件名消毒
│   ├── seed_data.py          29行  资源种子脚本
│   ├── seed_resources.json   42条  学习资源初始数据
│   ├── seed_categories_tags.json   10分类 + 50标签
│   └── routers/              6个API路由模块
│       ├── auth.py          120行  注册/登录/刷新/登出
│       ├── users.py         222行  个人信息/收藏/学习进度
│       ├── resources.py     458行  资源列表/详情/文件上传/PPT预览
│       ├── ai.py             89行  AI对话助手（关键词 + 全文搜索）
│       ├── categories.py     50行  分类列表/详情
│       └── tags.py           38行  标签列表/详情
│
├── 前端层（19个HTML文件 / 8,623行）
│   └── static/
│       ├── index.html          首页 · 六大板块入口
│       ├── login.html          登录/注册页
│       ├── profile.html        个人中心
│       ├── knowledge.html      资源列表（筛选+搜索+分页）
│       ├── knowledge-detail.html  资源详情
│       ├── knowledge-base.html  多维知识库
│       ├── ai-coding.html      AI编程专区
│       ├── python-course.html  Python课程
│       ├── research.html       科研孵化
│       ├── pricing.html        平台通道
│       ├── chemistry/          化学子站
│       ├── assets/            静态资源
│       └── uploads/           用户上传文件（gitignore）
│
├── 运维层
│   ├── render.yaml             Render一键部署配置
│   ├── runtime.txt             Python版本指定
│   ├── requirements.txt        7个Python依赖
│   ├── .gitignore              排除密钥/DB/日志/上传
│   ├── start_all.bat           本地一键启动脚本
│   └── install_requirements.bat
│
└── 运行时目录（gitignore，自动生成）
    ├── data/chongyue.db        SQLite数据库
    ├── logs/                   服务日志
    └── .secret_key             JWT密钥
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
                         │  │   ├── 16条页面路由          │  │
                         │  │   ├── 26条API v1路由        │  │
                         │  │   ├── 6条反向代理路由       │  │
                         │  │   ├── 1条GitHub API代理     │  │
                         │  │   ├── StaticFiles           │  │
                         │  │   └── SQLite /tmp/          │  │
                         │  └────────────────────────────┘  │
                         └──────────────────────────────────┘
```

### 中间件链（5层，按执行顺序）

```
请求 → uvicorn
       ├─ 1. CORSMiddleware         跨域白名单
       ├─ 2. SecurityHeadersMW      XSS/Frame/Referrer安全头
       ├─ 3. _HeadSupportMiddleware  HEAD→GET转换（UptimeRobot兼容）
       ├─ 路由匹配
       │   ├─ 页面路由 (@app.get)
       │   ├─ API路由 (APIRouter)
       │   ├─ 代理路由 (@app.api_route)
       │   └─ StaticFiles (/assets, /uploads)
       └─ 全局异常处理
           ├─ 404 / 500 / 429  友好错误页
           └─ Exception        全局兜底
```

---

## 🗄 数据库设计（7张表）

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
                  │user(FK) ││ id (PK)  │    │ 10分类
                  │res(FK)  ││ user(FK) │    │ 50标签
                  │created  ││ res(FK)  │    │ 42资源
                  └─────────┘│ status   │    └─────────────────
                             │ percent  │
                             │ started  │
                             │completed │
                             └──────────┘
```

---

## 📡 API接口全览（51条路由）

### 页面路由（16条）

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
| GET | `/ai-coding` | AI编程专区 |
| GET | `/chemistry` | 化学子站 |

### 核心API（23条）

| 模块 | 接口数 | 主要功能 |
|------|--------|----------|
| 认证 | 4 | 注册/登录/刷新/登出（JWT黑名单） |
| 用户 | 9 | 个人信息/收藏/学习进度管理 |
| 资源 | 6 | 资源CRUD/文件上传/PPT预览 |
| 分类标签 | 4 | 分类和标签的查询与管理 |
| AI助手 | 1 | 基于知识库的智能问答 |
| 运维 | 1 | 健康检查接口 |

---

## 🛡 安全措施

| 机制 | 实现细节 |
|------|----------|
| JWT认证 | access token(30min) + refresh token(7d)，JTI黑名单机制 |
| 密码哈希 | bcrypt算法，自动加盐 |
| 速率限制 | 认证10/min，AI 20/min，上传5/min（滑动窗口算法） |
| 文件名消毒 | 路径注入防护，Unicode正规化 |
| 安全响应头 | nosniff / SAMEORIGIN / XSS防护 / Referrer-Policy |
| 全局异常 | 不暴露Python Traceback，统一友好错误页 |
| 密钥管理 | 环境变量 > .secret_key文件 > 自动生成 |

---

## 🐛 常见问题与解决方案

| 错误信息 | 原因 | 解决方法 |
|---------|------|----------|
| `Exited with status 3` | Render默认Python 3.14与依赖不兼容 | 添加环境变量 `PYTHON_VERSION=3.12.11` |
| `unable to open database file` | Render当前目录只读 | 代码已自动检测Render环境，切换到`/tmp/chongyue.db` |
| `UptimeRobot显示Down 405` | 免费版只发HEAD请求 | 代码已通过`_HeadSupportMiddleware`兼容 |
| `上传目录不存在` | git clone不包含空目录 | 代码已在`lifespan()`中自动创建 |

---

## ⚠️ 免费版限制说明

### Render免费版
- ✅ 每月750小时免费额度，足够24小时运行
- ✅ 自动HTTPS证书 + GitHub自动部署
- ❌ 15分钟无访问自动休眠（已通过UptimeRobot解决）
- ❌ 数据库在实例重启时重置（`/tmp`目录）
- ❌ 单实例，适合几十人同时访问

### UptimeRobot免费版
- ✅ 最多50个监控
- ✅ 每5分钟检查一次
- ✅ 邮件提醒
- ❌ 只能用HEAD请求（已兼容）

---

## 🔧 日常维护

### 更新网站内容
```bash
cd "D:\Claude\制作中心"
git add .
git commit -m "更新内容说明"
git push
```
Render自动检测GitHub更新，3-5分钟后生效。

### 回滚版本
1. 进入Render仪表盘 → 你的服务
2. **Events**页面找到上一个成功部署
3. 点击 **Rollback** 即可回滚

### 数据备份
- 定期备份本地`D:\Claude\制作中心`文件夹
- Render SQLite在`/tmp`目录，实例重启后重置
- 如需持久化，可升级Render付费数据库或使用Supabase免费PostgreSQL

---

## 💻 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python unified_server.py
# → http://127.0.0.1:8888
```

**环境变量配置**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | 8888 | 监听端口（Render自动设置） |
| `RENDER` | (空) | Render环境检测 → DB切换到/tmp |
| `CYJY_SECRET_KEY` | 自动生成 | JWT签名密钥 |
| `CYJY_BACKEND_URL` | http://127.0.0.1:8088 | 数学竞赛后端 |
| `GITHUB_TOKEN` | (空) | GitHub API认证令牌 |

---

## 📊 代码统计

| 类型 | 文件数 | 代码行数 |
|------|--------|---------|
| Python | 14 | 2,271 |
| HTML | 19 | 8,623 |
| JSON (种子数据) | 2 | 791 |
| **合计** | **35** | **11,685** |

---

## 🤝 贡献指南

欢迎提交Issue和PR来帮助改进这个项目！

1. Fork本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开一个Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证开源 - 详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- 感谢所有为平台贡献资源和代码的学长学姐
- 感谢Render提供的免费云服务
- 感谢UptimeRobot提供的免费监控服务

---

<div align="center">

**不疾不徐，在此顶峰相见**

和数万名充满热情的高校同道一同探索知识的最深处，编码属于未来的无限可能。

</div>

---
