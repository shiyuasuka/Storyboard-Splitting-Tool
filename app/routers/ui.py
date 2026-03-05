from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.config import BASE_DIR

router = APIRouter(tags=["ui"])


@router.get("/ui")
async def ui_page() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")
