"""Elite Matrix public routes — application submission."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models import EliteApplication
from schemas import EliteApplyRequest, EliteApplicationOut, EMAIL_RE, clean_text
from security import apply_limiter

router = APIRouter(prefix="/api/v1/elite", tags=["elite"])


@router.post("/apply", response_model=EliteApplicationOut)
def submit_elite_application(
    request: Request,
    body: EliteApplyRequest,
    db: Session = Depends(get_db),
):
    """提交精英矩阵入圈申请"""
    # 无需登录的接口：限制每个 IP 的提交次数，防止被脚本灌满数据库
    apply_limiter.limit(request)

    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="请输入有效的邮箱地址")
    fields = dict(
        name=clean_text(body.name),
        school=clean_text(body.school),
        github=clean_text(body.github),
        field=clean_text(body.field),
        reason=clean_text(body.reason, multiline=True),
    )
    if not all(fields[k] for k in ("name", "school", "field", "reason")):
        raise HTTPException(status_code=422, detail="请填写完整的申请信息")

    # Check for duplicate email with pending status
    existing = db.query(EliteApplication).filter(
        EliteApplication.email == email,
        EliteApplication.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="您已有待审核的申请，请耐心等待")

    app = EliteApplication(email=email, status="pending", **fields)
    db.add(app)
    db.commit()
    db.refresh(app)
    return EliteApplicationOut.model_validate(app)
