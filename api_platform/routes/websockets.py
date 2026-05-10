"""
Phase 14: WebSocket real-time build progress streaming.

WS /ws/jobs/{build_id}
  - Streams progress events as JSON lines
  - Closes automatically when build completes or fails
  - Reconnect-safe: sends full history on connect
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api_platform.database import get_project, get_build_progress

router = APIRouter(tags=["websocket"])

# In-memory subscriber registry: build_id → list of (queue, loop)
# Populated by runner.py via notify_subscribers()
_subscribers: dict[str, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}

POLL_INTERVAL = 0.5    # seconds between DB polls for progress
MAX_SILENCE = 120      # close connection after N seconds without progress


def notify_subscribers(build_id: str, event: dict):
    """
    Called by runner.py whenever a build step completes.
    Thread-safe: schedules coroutine from sync thread.
    """
    import asyncio as _asyncio
    queues = _subscribers.get(build_id, [])
    for q, loop in queues:
        def _put(queue=q, ev=event):
            try:
                queue.put_nowait(ev)
            except _asyncio.QueueFull:
                pass
        
        # Schedule the _put call on the event loop that owns the queue
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(_put)


@router.websocket("/ws/jobs/{build_id}")
async def websocket_progress(websocket: WebSocket, build_id: str):
    """
    Stream build progress events for a given build_id.

    Message format:
    {
      "type": "progress" | "status_change" | "complete" | "error" | "ping",
      "build_id": "...",
      "step": 3,
      "step_name": "backend_developer",
      "status": "done",
      "timestamp": "...",
      "data": {...}        # optional extra
    }
    """
    await websocket.accept()

    # Check project exists
    project = get_project(build_id)
    if not project:
        await websocket.send_json({
            "type": "error",
            "build_id": build_id,
            "message": f"Project {build_id} not found",
        })
        await websocket.close(code=4004)
        return

    # If already finished, send history and close
    if project["status"] in ("done", "failed", "cancelled"):
        await _send_full_history(websocket, build_id, project)
        await websocket.send_json({
            "type": "complete",
            "build_id": build_id,
            "status": project["status"],
            "duration_seconds": project.get("duration_seconds"),
        })
        await websocket.close()
        return

    # Register as subscriber
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()
    _subscribers.setdefault(build_id, []).append((queue, loop))

    # Send history so far immediately on connect
    await _send_full_history(websocket, build_id, project)

    silence_seconds = 0

    try:
        while True:
            # Drain any events from runner
            try:
                while True:
                    event = queue.get_nowait()
                    await websocket.send_json(event)
                    silence_seconds = 0
            except asyncio.QueueEmpty:
                pass

            # Poll DB for status change
            project = get_project(build_id)
            if not project:
                await websocket.send_json({"type": "error", "message": "Project disappeared"})
                break

            if project["status"] in ("done", "failed", "cancelled"):
                # Drain any final queued events
                try:
                    while True:
                        event = queue.get_nowait()
                        await websocket.send_json(event)
                except asyncio.QueueEmpty:
                    pass

                await websocket.send_json({
                    "type": "complete",
                    "build_id": build_id,
                    "status": project["status"],
                    "duration_seconds": project.get("duration_seconds"),
                    "review_score": project.get("review_score"),
                })
                break

            # Keepalive ping every 10s
            silence_seconds += POLL_INTERVAL
            if silence_seconds % 10 < POLL_INTERVAL:
                await websocket.send_json({"type": "ping", "build_id": build_id})

            if silence_seconds >= MAX_SILENCE:
                await websocket.send_json({"type": "error", "message": "Build timeout"})
                break

            await asyncio.sleep(POLL_INTERVAL)

    except WebSocketDisconnect:
        pass  # client disconnected normally
    finally:
        # Unregister subscriber
        subs = _subscribers.get(build_id, [])
        subs_to_keep = [s for s in subs if s[0] != queue]
        if subs_to_keep:
            _subscribers[build_id] = subs_to_keep
        else:
            _subscribers.pop(build_id, None)

    await websocket.close()


async def _send_full_history(websocket: WebSocket, build_id: str, project: dict):
    """Send all progress steps recorded so far."""
    await websocket.send_json({
        "type": "status_change",
        "build_id": build_id,
        "status": project["status"],
        "app_name": project.get("app_name"),
        "app_type": project.get("app_type"),
    })

    steps = get_build_progress(build_id)
    for step in steps:
        await websocket.send_json({
            "type": "progress",
            "build_id": build_id,
            "step": step["step"],
            "step_name": step["step_name"],
            "status": step["status"],
            "timestamp": step["timestamp"],
        })
