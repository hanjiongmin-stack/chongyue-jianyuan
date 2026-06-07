"""AI chat assistant — Doubao LLM + RAG knowledge retrieval + SSE streaming."""

import os, json, logging
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from security import ai_limiter
from pydantic import BaseModel
import httpx

from database import SessionLocal
from models import Resource

logger = logging.getLogger("ai_router")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# ═══════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════

DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_ENDPOINT_ID = os.environ.get("DOUBAO_ENDPOINT_ID", "")
DOUBAO_BASE = "https://ark.cn-beijing.volces.com/api/v3"

# ═══════════════════════════════════════════════════════════
#  System Prompt
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT = """你是"崇岳鉴渊"的 AI 智能助手（豆包大模型驱动）。崇岳鉴渊是一个面向大学生的科研互助与学习资源共享平台。

## 平台核心板块
- 🧮 **数学竞赛真题库** (/math)：CMC、美赛 MCM/ICM 历年真题与 LaTeX 精细化推导
- 💻 **AI 编程专区** (/ai-coding)：Claude Code 工作流、Cursor 前端实战、Prompt 工程教学
- 📚 **多维溯熵知识库** (/knowledge-base)：CS / 数学 / 数据科学等专业核心课高分笔记
- 📖 **学习资源** (/knowledge)：分类浏览、标签筛选、全文搜索、PPT 在线预览
- 🚀 **科研孵化** (/research)：开源项目共建、PR 贡献指南、论文复现、实验室对接
- ⚗️ **高等化学资料站** (/chemistry)

## 平台页面路由
| 路径 | 功能 |
|------|------|
| / | 首页，六大板块入口 |
| /knowledge | 学习资源列表（筛选 + 搜索 + 分页）|
| /knowledge/{id} | 资源详情页（文件预览、收藏、进度标记）|
| /login | 登录 / 注册 |
| /profile | 个人中心（收藏、进度、资料编辑）|
| /pricing | 平台通道（免费 / 进阶 / 精英）|
| /ai-coding | AI 编程专区 |
| /research | 科研孵化 |
| /knowledge-base | 多维知识库 |
| /math | 数学竞赛真题库 |

## 回答规则
1. 用**专业、友好、简洁**的中文回答，适当使用 emoji 增加亲和力
2. 如果系统提供了「知识库检索结果」，**必须引用**其中的资源，引用格式：`[资源名](/knowledge/{id})`
3. 数学公式用 `$$...$$`（块级）或 `$...$`（行内）包裹
4. 默认回答控制在 200-400 字；用户明确要求详细时再展开
5. 如果问题完全超出平台范围，礼貌说明后提供力所能及的通用帮助
6. 绝对不要编造不存在的资源链接或功能"""

# ═══════════════════════════════════════════════════════════
#  Fallback KB (when LLM unavailable)
# ═══════════════════════════════════════════════════════════

FALLBACK_KB = {
    "首页": "首页（/）是平台入口，展示六大核心板块：数学竞赛真题库、AI编程、多维知识库、科研孵化。登录后可使用收藏和学习进度。",
    "数学竞赛": "数学竞赛真题库（/math）收录全国大学生数学竞赛（CMC）、美赛（MCM/ICM）等历年真题，配备LaTeX精细化推导与多解法对照。",
    "学习资源": "学习资源（/knowledge）按分类浏览：公共基础课、专业核心课、学科竞赛、论文写作、升学备考、工具素材。支持标签筛选和关键词搜索。",
    "AI编程": "AI编程专区（/ai-coding）提供Claude Code工作流教程、Cursor前端实战、脚手架代码示例（含语法高亮），助你从使用AI到驾驭AI。",
    "知识库": "多维溯熵知识库（/knowledge-base）按学科维度（CS/数学/数据科学/工具链）组织，由顶尖学长学姐开源共建。",
    "科研孵化": "科研孵化（/research）展示开源项目、PR贡献指南、论文复现、实验室入门等方向，从零产出高质量开源贡献。",
    "登录": "登录页（/login）支持注册新账户和登录。登录后可使用收藏资源、标记学习进度、编辑个人资料。",
    "个人中心": "个人中心（/profile）可编辑显示名称、查看收藏资源、管理学习进度、退出登录。",
    "收藏": "登录后在资源详情页可点击收藏按钮，所有收藏在个人中心查看。",
    "学习进度": "登录后在资源详情页可标记学习进度（未开始/学习中/已完成），拖动滑块调整完成百分比。",
    "搜索": "学习资源列表页支持按标题/描述搜索，可组合分类、标签、难度筛选。",
    "美赛": "美赛特等奖论文汇编收录2006-2025年MCM/ICM O奖论文共294篇，按年份分目录，支持PDF在线预览。",
    "注册": "在登录页切换到注册Tab，填写用户名、邮箱、密码即可创建账户。注册后自动登录并跳转知识库。",
    "暗色模式": "所有页面右上角有☀/☾按钮，点击切换深色/亮色模式，偏好自动保存到localStorage。",
    "化学": "高等化学资料站（/chemistry）提供物理化学、有机化学、无机化学等专业课程的学习资料。",
}

GREETINGS = ["你好", "嗨", "hello", "hi", "在吗", "你是谁", "介绍", "你好吗", "你能做什么"]
FAREWELLS = ["谢谢", "感谢", "bye", "再见", "拜拜", "3q", "thanks", "thank"]


class ChatRequest(BaseModel):
    message: str
    search_files: bool = False


# ═══════════════════════════════════════════════════════════
#  Knowledge Retrieval
# ═══════════════════════════════════════════════════════════

def _search_db(query: str, limit: int = 6) -> list[dict]:
    """Search published resources in local SQLite DB."""
    db = SessionLocal()
    try:
        like = f"%{query}%"
        from sqlalchemy import or_
        rows = (
            db.query(Resource)
            .filter(
                Resource.status == "published",
                or_(
                    Resource.title.ilike(like),
                    Resource.description.ilike(like),
                    Resource.content.ilike(like),
                    Resource.author.ilike(like),
                ),
            )
            .limit(limit)
            .all()
        )
        results = []
        for r in rows:
            results.append({
                "id": r.id,
                "title": r.title,
                "category": r.category.name if r.category else "未分类",
                "description": (r.description or "")[:200],
                "difficulty": r.difficulty or 1,
            })
        return results
    finally:
        db.close()


def _build_context(results: list[dict]) -> str:
    """Format search results as LLM system context."""
    if not results:
        return ""
    lines = ["\n【知识库检索结果 — 请在回答中引用以下资源】"]
    for r in results:
        stars = "★" * r["difficulty"] + "☆" * (5 - r["difficulty"])
        lines.append(
            f"- [ID:{r['id']}]《{r['title']}》\n"
            f"  分类：{r['category']} | 难度：{stars}\n"
            f"  简介：{r['description']}\n"
            f"  链接：/knowledge/{r['id']}"
        )
    return "\n".join(lines)


def _format_results_html(results: list[dict]) -> str:
    """Format search results as HTML for fallback (non-LLM) mode."""
    if not results:
        return ""
    lines = ['<div style="font-weight:600;margin-bottom:.35rem">🔍 找到以下相关资源：</div>']
    for r in results:
        lines.append(
            f'<div style="margin:.25rem 0">'
            f'<a href="/knowledge/{r["id"]}" target="_blank" '
            f'style="color:var(--accent);text-decoration:underline;font-weight:500">'
            f'{r["title"]}</a>'
            f' <span style="color:var(--muted);font-size:.6875rem">[{r["category"]}]</span>'
            f'</div>'
        )
    return "".join(lines)


def _keyword_match(msg: str) -> str:
    """Simple keyword match against fallback KB."""
    low = msg.lower()
    for kw, answer in FALLBACK_KB.items():
        if kw.lower() in low:
            return answer
    return ""


# ═══════════════════════════════════════════════════════════
#  Doubao LLM Streaming
# ═══════════════════════════════════════════════════════════

async def _stream_doubao(messages: list[dict]):
    """Stream tokens from Doubao (Volcengine Ark) as SSE events.

    Yields SSE-formatted strings:
        data: {"t":"<token>","f":"<full text so far>"}
        data: [DONE]
    On error:
        data: {"error":"<message>"}
        data: [DONE]
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)) as client:
        try:
            async with client.stream(
                "POST",
                f"{DOUBAO_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DOUBAO_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DOUBAO_ENDPOINT_ID,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    logger.error(
                        "Doubao API error %s: %s", resp.status_code, body[:500]
                    )
                    yield f"data: {json.dumps({'error': f'AI 服务暂时不可用（{resp.status_code}），请稍后重试'})}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                full = ""
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        obj = json.loads(payload)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            full += content
                            yield f"data: {json.dumps({'t': content, 'f': full})}\n\n"
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except httpx.ConnectError:
            logger.warning("Doubao connection refused")
            yield f"data: {json.dumps({'error': '无法连接到 AI 服务，请稍后重试'})}\n\n"
            yield "data: [DONE]\n\n"
        except httpx.ReadTimeout:
            logger.warning("Doubao read timeout")
            yield f"data: {json.dumps({'error': 'AI 响应超时，请简化问题后重试'})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Stream exception: %s", e)
            yield f"data: {json.dumps({'error': 'AI 服务异常，请稍后重试'})}\n\n"
            yield "data: [DONE]\n\n"


# ═══════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════

@router.post("/chat")
async def chat(request: Request, req: ChatRequest):
    """AI chat endpoint.

    - When Doubao API key is configured: returns SSE streaming response
    - Otherwise: falls back to keyword matching + DB search
    """
    ai_limiter.limit(request)

    msg = req.message.strip()
    if not msg:
        return {"reply": "请输入问题，我会尽力解答。"}

    # ── Fast path: greetings ─────────────────────────
    if any(g in msg.lower() for g in GREETINGS):
        return {
            "reply": (
                "你好！👋 我是崇岳鉴渊的 <b>AI 智能助手</b>，由豆包大模型驱动。<br><br>"
                "我可以帮你：<br>"
                "🔍 <b>搜索学习资源</b>——试试问我「线性代数有什么资料」<br>"
                "📖 <b>解答平台使用</b>——「怎么收藏资源？」<br>"
                "🧮 <b>数学竞赛</b>——「CMC 数学类考什么？」<br>"
                "💻 <b>AI 编程指导</b>——「Claude Code 怎么用？」<br><br>"
                "直接提问即可，勾选 ☑️<b>搜文件</b>可检索知识库！"
            )
        }

    if any(f in msg.lower() for f in FAREWELLS):
        return {"reply": "不客气！有问题随时找我，祝你学习顺利！🚀"}

    # ── Build messages for LLM ───────────────────────
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # RAG: search local DB for knowledge context
    if req.search_files:
        results = _search_db(msg, limit=6)
        if results:
            context = _build_context(results)
            messages.append({"role": "system", "content": context})

    messages.append({"role": "user", "content": msg})

    # ── Try streaming LLM ────────────────────────────
    if DOUBAO_API_KEY and DOUBAO_ENDPOINT_ID:
        return StreamingResponse(
            _stream_doubao(messages),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Fallback: keyword match + DB search ──────────
    kw = _keyword_match(msg)
    if kw:
        return {"reply": kw}

    if req.search_files:
        results = _search_db(msg, limit=5)
        if results:
            return {"reply": _format_results_html(results)}
        return {"reply": "未找到匹配的学习资源，试试其他关键词？"}

    return {
        "reply": (
            "我主要解答关于崇岳鉴渊平台的问题。<br><br>"
            "你可以问我：<br>"
            "• 平台有哪些功能？<br>"
            "• 数学竞赛题库怎么用？<br>"
            "• AI 编程专区有什么内容？<br>"
            "• 如何收藏和标记学习进度？<br><br>"
            "或者勾选 ☑️ <b>搜文件</b> 来查找具体的学习资源。"
        )
    }
