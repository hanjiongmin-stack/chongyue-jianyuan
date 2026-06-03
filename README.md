# 崇岳鉴渊 - 公网部署方案

> 基于 FastAPI + Cloudflare Tunnel 的完全免费公网部署方案

---

## 项目结构

```
制作中心/
├── unified_server.py          # 核心统一入口服务器 (FastAPI)
├── start_all.bat              # 一键启动所有服务
├── install_requirements.bat   # 首次安装依赖
├── requirements.txt           # Python 依赖
├── README.md                  # 本文档
├── logs/                      # 请求/错误日志 (自动生成)
└── static/                    # 静态文件
    ├── index.html             # 首页 (原 optimus.html)
    └── assets/                # 静态资源 (图片、PDF等)
```

---

## 架构原理

```
公网用户 (任意设备)
        |
        v
https://xxx.trycloudflare.com   <- Cloudflare 提供免费 HTTPS
        |
        v
Cloudflare Tunnel (cloudflared)  <- 本地轻量隧道客户端
        |
        v
FastAPI 统一入口 (0.0.0.0:8888)  <- unified_server.py
   ├── /           -> 首页 (optimuls.html)
   ├── /assets/*   -> 静态资源
   ├── /math/*     -> 反向代理 -> 127.0.0.1:8088 (数学竞赛)
   ├── /pdf/*      -> 反向代理 -> 127.0.0.1:8088
   └── /api/*      -> 反向代理 -> 127.0.0.1:8088
```

---

## 安装步骤 (仅首次)

### 前置要求

- Windows 10/11
- Python 3.11+ (需在 PATH 中)
- 网络连接 (用于下载依赖)

### 安装依赖

双击运行:
```
install_requirements.bat
```

这会自动:
- 安装 FastAPI、uvicorn、httpx (`pip install -r requirements.txt`)
- 安装 cloudflared (`winget install Cloudflare.cloudflared`)

### 验证安装

打开终端，运行:
```bash
python --version         # 应显示 3.11+
pip list | findstr fastapi  # 应看到 fastapi
cloudflared --version    # 应显示版本号
```

---

## 启动步骤

### 一键启动 (推荐)

双击运行:
```
start_all.bat
```

### 手动分步启动

```bash
# 终端 1: 启动数学竞赛服务器
cd C:\Users\hanji\math-competition-viewer
python server.py

# 终端 2: 启动统一入口服务器
cd D:\Claude\制作中心
python unified_server.py

# 终端 3: 启动 Cloudflare Tunnel
cloudflared tunnel --url http://localhost:8888
```

---

## 获取公网链接

启动 `start_all.bat` 后，终端会显示类似:

```
INF Requesting new quick tunnel on trycloudflare.com...
INF +------------------------------------------------------------+
INF |  Your quick tunnel has been created!                       |
INF |  https://example-quick-fox.trycloudflare.com               |
INF +------------------------------------------------------------+
```

**复制这个 URL (`https://xxx.trycloudflare.com`) 分享给任何人即可访问。**

---

## 如何分享公网链接

1. 复制 cloudflared 输出的 `https://xxx.trycloudflare.com` 链接
2. 通过微信、QQ、邮件等方式发送给对方
3. 对方在任何设备 (手机/电脑/平板) 的浏览器打开即可
4. **无需安装任何软件，无需同一网络，全球可访问**

---

## 如何停止服务

- 在 `start_all.bat` 的终端窗口中按 `Ctrl+C`
- 脚本会自动关闭所有后台服务窗口

如果手动启动的:
- 在各个终端窗口分别按 `Ctrl+C`

---

## Cloudflare Tunnel 原理

```
[你的电脑] <--> [Cloudflare 全球边缘网络] <--> [公网用户]
     |                    |
     |  加密隧道           |  HTTPS (自动证书)
     |  (cloudflared)      |  DDoS 防护
     |                     |  CDN 加速
     +---------------------+
```

- **免费**: Quick Tunnel 完全免费，无需注册 Cloudflare 账号
- **HTTPS**: Cloudflare 自动提供 SSL 证书
- **无需公网 IP**: 不依赖路由器端口转发或公网 IP
- **全球加速**: 流量经 Cloudflare 全球网络优化
- **安全**: 流量全程加密，不暴露本地网络

### Quick Tunnel 说明

- 每次启动生成**随机的临时域名** (xxx.trycloudflare.com)
- 如果需要**固定域名**，可升级为 Named Tunnel (需免费 Cloudflare 账号 + 自有域名)

---

## 常见问题

### Q: 显示 "数学竞赛服务未启动"

**原因**: 数学竞赛服务器 (8088端口) 没有成功启动

**解决**:
1. 检查 `C:\Users\hanji\math-competition-viewer\server.py` 是否存在
2. 检查 PDF 目录 `D:\BaiduNetdiskDownload\...` 是否存在
3. 手动运行 `cd C:\Users\hanji\math-competition-viewer && python server.py` 查看错误

### Q: 公网链接打不开

**原因**: cloudflared 隧道未成功建立

**解决**:
1. 检查网络连接是否正常
2. 防火墙是否阻止了 cloudflared
3. 尝试 `cloudflared tunnel --url http://localhost:8888` 查看详细日志

### Q: 页面能打开但竞赛库无法加载

**原因**: 代理转发配置问题

**解决**:
1. 确认 8088 端口服务正常运行
2. 查看 `logs/` 目录下的日志文件
3. 访问 `http://127.0.0.1:8888/health` 检查服务状态

### Q: 如何获取固定域名而不是临时域名？

**方案**:
1. 注册免费 Cloudflare 账号
2. 添加你的域名到 Cloudflare
3. 创建 Named Tunnel:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create my-tunnel
   cloudflared tunnel route dns my-tunnel your-domain.com
   cloudflared tunnel run my-tunnel
   ```

### Q: 关闭后公网链接还能访问吗？

**不能**。Quick Tunnel 随 cloudflared 进程退出而销毁。
每次启动会生成新的临时域名。

---

## 后续升级建议

1. **固定域名**: 注册 Cloudflare 账号 -> 创建 Named Tunnel -> 绑定自定义域名
2. **进程守护**: 使用 NSSM 将服务注册为 Windows 服务，开机自启
3. **HTTPS 本地**: 生产环境建议 unified_server 也配置 SSL (通过 cloudflared 已自动提供)
4. **访问控制**: 可通过 Cloudflare Access 添加身份验证 (邮箱/Google/GitHub 登录)
5. **速率限制**: 通过 Cloudflare WAF 限制 API 调用频率
6. **监控**: 接入 Cloudflare Analytics 查看访问统计
7. **Docker**: 可容器化部署，便于迁移到 VPS
8. **WebSocket**: 如需实时通信，Cloudflare Tunnel 原生支持 WebSocket

---

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 高性能异步 Python Web 框架 |
| ASGI 服务器 | uvicorn | 轻量级 ASGI 服务器 |
| HTTP 代理 | httpx | 异步 HTTP 客户端，用于反向代理 |
| 隧道 | cloudflared | Cloudflare 官方隧道客户端 |
| PDF 渲染 | PyMuPDF | 数学竞赛 PDF 解析 (可选) |
| 数学公式 | KaTeX | LaTeX 数学公式前端渲染 |
| 字体 | Google Fonts | Instrument Sans/Serif, JetBrains Mono |

---

## 许可

本项目仅用于个人学习与交流。