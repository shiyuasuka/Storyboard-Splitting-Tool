from __future__ import annotations

from fastapi import APIRouter

from app.core.container import project_manager
from app.models.schemas import Constraints, NovelIngestRequest, NovelIngestResponse, ProjectParams
from app.services.novel_service import NovelService

router = APIRouter(prefix="/novel", tags=["novel"])
novel_service = NovelService()


@router.post("/ingest_text", response_model=NovelIngestResponse)
async def ingest_novel_text(req: NovelIngestRequest) -> NovelIngestResponse:
    pid = req.project_id
    if pid:
        project = project_manager.get_project(pid)
        if project is None:
            project = project_manager.create_project(
                params=ProjectParams(topic=req.title or "未命名命题", constraints=Constraints()),
                project_id=pid,
            )
    else:
        project = project_manager.create_project(
            params=ProjectParams(topic=req.title or "未命名命题", constraints=Constraints())
        )

    novel_payload = novel_service.build_novel_payload(req.title or "未命名小说", req.content)
    project.novel = novel_payload
    project.params.topic = novel_service.topic_from_novel(novel_payload)
    project_manager.upsert(project)

    return NovelIngestResponse(
        project_id=project.project_id,
        title=novel_payload["title"],
        content_chars=novel_payload["content_chars"],
        segments_count=len(novel_payload["segments"]),
        preview=novel_payload["segments"][0][:120],
    )
