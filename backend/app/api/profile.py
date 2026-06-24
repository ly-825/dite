from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.profile import RecipeFeedbackCreate, RecipeFeedbackResponse, UserProfileResponse, UserProfileUpdate
from app.services.profile_service import profile_service

router = APIRouter(prefix="/api/profile", tags=["C端个人档案"])


@router.get("", response_model=UserProfileResponse)
def get_profile_bundle(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.get_profile_bundle(db=db, user_id=current_user.id)


@router.put("", response_model=UserProfileResponse)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.update_profile(db=db, user_id=current_user.id, payload=payload)


@router.post("/memories/{memory_id}/confirm", response_model=UserProfileResponse)
def confirm_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.confirm_memory(db=db, user_id=current_user.id, memory_id=memory_id)


@router.post("/memories/{memory_id}/reject", response_model=UserProfileResponse)
def reject_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.reject_memory(db=db, user_id=current_user.id, memory_id=memory_id)


@router.post("/recipe-feedbacks", response_model=RecipeFeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_recipe_feedback(
    payload: RecipeFeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return profile_service.create_recipe_feedback(db=db, user_id=current_user.id, payload=payload)
