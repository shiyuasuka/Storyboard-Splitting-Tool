from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.container import project_manager
from app.models.schemas import CreateProjectRequest, ProjectParams, ProjectRecord

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRecord)
async def create_project(req: CreateProjectRequest) -> ProjectRecord:
    params = ProjectParams(
        topic=req.topic,
        constraints=req.constraints,
        prompt_version=req.prompt_version,
        strategy_version=req.strategy_version,
    )
    return project_manager.create_project(params=params)


@router.get("", response_model=list[ProjectRecord])
async def list_projects() -> list[ProjectRecord]:
    return project_manager.list_projects()


@router.get("/{project_id}", response_model=ProjectRecord)
async def get_project(project_id: str) -> ProjectRecord:
    record = project_manager.get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    return record
