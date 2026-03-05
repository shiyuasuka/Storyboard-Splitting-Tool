from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.container import export_service, project_manager
from app.models.schemas import ExportResponse

router = APIRouter(tags=["export"])


@router.get("/export/{project_id}", response_model=ExportResponse)
async def export_project(
    project_id: str,
    format: str = Query(default="bundle", pattern="^(bundle|all|internal|internal_json|json|arena|arena_txt|txt|markdown|md)$"),
) -> ExportResponse:
    record = project_manager.get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return export_service.export_project(record, fmt=format)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
