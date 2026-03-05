from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.container import generation_orchestrator
from app.models.schemas import GenerateBatchRequest, GenerateBatchResponse
from app.services.llm_client import LLMClientError

router = APIRouter(tags=["generation"])


@router.post("/generate_batch", response_model=GenerateBatchResponse)
async def generate_batch(req: GenerateBatchRequest) -> GenerateBatchResponse:
    try:
        return await generation_orchestrator.generate_batch(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMClientError as e:
        raise HTTPException(status_code=502, detail=f"LLM API error: {e}") from e


@router.post("/generate_batch_stream")
async def generate_batch_stream(req: GenerateBatchRequest) -> StreamingResponse:
    queue: asyncio.Queue[dict] = asyncio.Queue()

    async def progress_cb(event: dict) -> None:
        await queue.put({"type": "progress", "data": event})

    async def worker() -> None:
        try:
            result = await generation_orchestrator.generate_batch_with_progress(req=req, progress_cb=progress_cb)
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except ValueError as e:
            await queue.put({"type": "error", "error": str(e), "code": 400})
        except LLMClientError as e:
            await queue.put({"type": "error", "error": f"LLM API error: {e}", "code": 502})
        except Exception as e:  # noqa: BLE001
            await queue.put({"type": "error", "error": f"unexpected error: {e}", "code": 500})
        finally:
            await queue.put({"type": "end"})

    asyncio.create_task(worker())

    async def event_stream():
        while True:
            item = await queue.get()
            yield json.dumps(item, ensure_ascii=False) + "\n"
            if item.get("type") == "end":
                break

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
