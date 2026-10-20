from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User
from app.dependencies.auth import require_admin
from app.services.admin_analytics_service import get_admin_analytics


router = APIRouter(prefix="/api/admin", tags=["admin-analytics"])


@router.get("/analytics")
def read_admin_analytics(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return get_admin_analytics(db)
