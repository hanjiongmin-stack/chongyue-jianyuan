"""AI chat assistant with local knowledge base — instant responses."""

import re
from fastapi import APIRouter, Request
from security import ai_limiter
from pydantic import BaseModel

from database import SessionLocal
from models import Resource, Category

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

class ChatRequest(BaseModel):
    message: str
    search_files: bool = False

# ── Website knowledge base ─────────────────────────────
KNOWLEDGE = {
    "首页": "首页（/）是平台入口，展示六大核心板块：数学竞赛真题库、AI编程、多维知识库、科研孵化。登录后可使用收藏和学习进度。",
    "数学竞赛": "数学竞赛真题库（/math）收录全国大学生数学竞赛（CMC）、美赛（MCM/ICM）等历年真题，配备LaTeX解析。",
    "学习资源": "学习资源（/knowledge）按分类浏览：公共基础课、专业核心课、学科竞赛、论文写作、升学备考、工具素材。支持标签筛选和关键词搜索。",
    "AI编程": "AI编程专区（/ai-coding）提供Claude Code工作流教程、Cursor前端实战、脚手架代码示例（含语法高亮）。",
    "知识库": "多维溯熵知识库（/knowledge-base）按学科维度（CS/数学/数据科学/工具链）组织，可点击领域卡片筛选。",
    "科研孵化": "科研孵化（/research）展示开源项目、PR贡献指南、论文复现、实验室入门等方向。",
    "登录": "登录页（/login）支持注册新账户和登录。登录后可使用收藏资源、标记学习进度、编辑个人资料。",
    "个人中心": "个人中心（/profile）可编辑显示名称、查看注册信息、退出登录。",
    "权益": "平台通道（/pricing）展示三档计划：免费新手池、进阶舱（¥29/月）、科研孵化圈（审核制）。含权益对比表和FAQ。",
    "校园合伙人": "校园合伙人（/pricing/partner）面向在校学生的推广合作计划，提供品牌推广、独家资源、履历加分、收益分成。",
    "暗色模式": "所有页面右上角有☀/☾按钮，点击切换深色/亮色模式，偏好自动保存。",
    "美赛": "美赛特等奖论文汇编（/knowledge/10）收录2006-2025年MCM/ICM O奖论文共294篇，按年份分目录，支持PDF在线预览。",
    "收藏": "登录后在资源详情页可点击收藏按钮，所有收藏在个人中心查看。收藏状态自动保存。",
    "学习进度": "登录后在资源详情页可标记学习进度（未开始/学习中/已完成），拖动滑块调整完成百分比。",
    "文件上传": "资源详情页支持上传PDF、图片、PPT等文件，上传后自动显示在文件列表。",
    "搜索": "学习资源列表页支持按标题/描述搜索，可组合分类、标签、难度筛选。",
    "注册": "在登录页切换到注册Tab，填写用户名、邮箱、密码即可创建账户。注册后自动登录并跳转知识库。",
    "忘记密码": "暂不支持自助找回密码，请联系管理员。",
}

GREETINGS = ["你好", "嗨", "hello", "hi", "在吗", "你是谁", "介绍"]
FAREWELLS = ["谢谢", "感谢", "bye", "再见", "拜拜"]

def match_intent(msg: str) -> str:
    """Simple keyword matching against the knowledge base."""
    low = msg.lower()
    for kw, answer in KNOWLEDGE.items():
        if kw.lower() in low:
            return answer
    return ""

def search_resources(query: str, limit: int = 5) -> str:
    db = SessionLocal()
    try:
        like = f"%{query}%"
        from sqlalchemy import or_
        resources = db.query(Resource).filter(
            Resource.status == "published",
            or_(
                Resource.title.ilike(like),
                Resource.description.ilike(like),
                Resource.content.ilike(like),
                Resource.author.ilike(like),
            ),
        ).limit(limit).all()
        if not resources:
            return ""
        lines = ["找到以下相关资源："]
        for r in resources:
            cat = r.category.name if r.category else ""
            lines.append('- <a href="/knowledge/' + str(r.id) + '" target="_blank" style="color:var(--fg);text-decoration:underline">' + r.title + '</a> <span style="color:var(--muted);font-size:.6875rem">[' + cat + ']</span>')
        return "\n".join(lines)
    finally:
        db.close()

@router.post("/chat")
async def chat(request: Request, req: ChatRequest):
    # Rate limit
    ai_limiter.limit(request)
    msg = req.message.strip()
    if not msg:
        return {"reply": "请输入问题，我会尽力解答。"}

    # Greeting
    if any(g in msg.lower() for g in GREETINGS):
        return {"reply": "你好！我是崇岳鉴渊的智能助手。你可以问我平台功能、页面导航、学习资源的问题。<br><br>试试问：<br>- 数学竞赛在哪里？<br>- 怎么收藏资源？<br>- AI编程有什么内容？<br><br>勾选「搜文件」可搜索知识库中的文件。"}

    # Farewell
    if any(f in msg.lower() for f in FAREWELLS):
        return {"reply": "不客气！有问题随时找我。祝你学习顺利！"}

    # File search
    if req.search_files:
        result = search_resources(msg)
        if result:
            return {"reply": result}
        return {"reply": "未找到匹配的学习资源。试试其他关键词，或取消「搜」勾选用普通问答模式。"}

    # Keyword match
    answer = match_intent(msg)
    if answer:
        return {"reply": answer}

    # Fallback
    return {"reply": "我主要解答关于崇岳鉴渊平台的问题。你可以问我：\n\n- 平台有哪些功能？\n- 怎么使用数学竞赛题库？\n- AI编程专区有什么？\n- 如何收藏和标记学习进度？\n\n或者勾选「搜」按钮来查找具体的学习资源文件。"}