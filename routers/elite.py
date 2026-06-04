"""Elite Matrix public routes — application submission."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import EliteApplication
from schemas import EliteApplyRequest, EliteApplicationOut

router = APIRouter(prefix="/api/v1/elite", tags=["elite"])


@router.post("/apply", response_model=EliteApplicationOut)
def submit_elite_application(
    body: EliteApplyRequest,
    db: Session = Depends(get_db),
):
    """提交精英矩阵入圈申请"""
    # Check for duplicate email with pending status
    existing = db.query(EliteApplication).filter(
        EliteApplication.email == body.email,
        EliteApplication.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="您已有待审核的申请，请耐心等待")

    app = EliteApplication(
        name=body.name,
        email=body.email,
        school=body.school,
        github=body.github,
        field=body.field,
        reason=body.reason,
        status="pending",
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return EliteApplicationOut.model_validate(app)
