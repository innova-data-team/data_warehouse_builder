"""FastAPI routers. One module per resource."""

from fastapi import APIRouter

from .approval_routes import router as approval_router
from .export_routes import router as export_router
from .pipeline_routes import router as pipeline_router
from .relationship_routes import router as relationship_router
from .report_routes import router as report_router
from .upload_routes import router as upload_router

api_router = APIRouter()
api_router.include_router(upload_router)
api_router.include_router(pipeline_router)
api_router.include_router(relationship_router)
api_router.include_router(approval_router)
api_router.include_router(report_router)
api_router.include_router(export_router)

__all__ = ["api_router"]
