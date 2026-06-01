import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


@router.get("/stream")
async def stream(request: Request, once: int = 0):
    """Slice 1 스텁 — mock 하트비트. 실제 이벤트 소스는 이후 슬라이스."""

    async def event_gen():
        tick = 0
        while True:
            if await request.is_disconnected():
                break
            tick += 1
            yield {"event": "heartbeat", "data": json.dumps({"tick": tick})}
            if once:
                break
            await asyncio.sleep(2)

    return EventSourceResponse(event_gen())
