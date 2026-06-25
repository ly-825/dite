from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.meal_history import MealHistoryResponse, MealReviewResponse
from app.services.meal_history_service import meal_history_service


router = APIRouter(prefix="/api/meals", tags=["C端餐食历史"])


@router.get("/records", response_model=MealHistoryResponse)
def list_meal_records(
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return meal_history_service.list_records(db=db, user_id=current_user.id, days=days)


@router.get("/review", response_model=MealReviewResponse)
def get_meal_review(
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return meal_history_service.build_review(db=db, user_id=current_user.id, days=days)


@router.delete("/records/{record_id}", response_model=MealHistoryResponse)
def delete_meal_record(
    record_id: int,
    days: int = Query(default=7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = meal_history_service.delete_record(db=db, user_id=current_user.id, record_id=record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="餐食记录不存在")
    return meal_history_service.list_records(db=db, user_id=current_user.id, days=days)
