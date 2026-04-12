"""FastAPI WebSocket + REST router for Kairos companion agent."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from companion.chat import ChatEngine
from companion.dispatch import DispatchManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])

# Module-level singletons — populated by init_router()
_chat_engine: Optional[ChatEngine] = None
_dispatch_manager: Optional[DispatchManager] = None


def init_router(
    chat_engine: ChatEngine,
    dispatch_manager: DispatchManager,
    event_publisher: Optional[object] = None,
    metrics: Optional[object] = None,
    cost_tracker: Optional[object] = None,
) -> None:
    """
    Inject dependencies into the router module.

    Call this from the orchestrator lifespan before the router handles requests.
    Optionally pass event_publisher, metrics, and cost_tracker for observability.
    """
    global _chat_engine, _dispatch_manager
    # Wire observability into the chat engine if provided
    if event_publisher is not None:
        chat_engine.event_publisher = event_publisher
    if metrics is not None:
        chat_engine.metrics = metrics
    if cost_tracker is not None:
        chat_engine.cost_tracker = cost_tracker
    _chat_engine = chat_engine
    _dispatch_manager = dispatch_manager
    logger.info("companion_router_initialized")


def _get_chat_engine() -> ChatEngine:
    if _chat_engine is None:
        raise HTTPException(
            status_code=503, detail="Companion chat engine not initialized"
        )
    return _chat_engine


def _get_dispatch_manager() -> DispatchManager:
    if _dispatch_manager is None:
        raise HTTPException(
            status_code=503, detail="Companion dispatch manager not initialized"
        )
    return _dispatch_manager


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    user_id: str
    title: Optional[str] = None


class SyncChatRequest(BaseModel):
    user_id: str
    message: str


class CreateDispatchRequest(BaseModel):
    session_id: str
    prompt: str
    branch: Optional[str] = None


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict:
    """Create a new companion session."""
    engine = _get_chat_engine()
    session_id = await engine.memory.create_session(
        user_id=body.user_id,
        title=body.title,
    )
    session = await engine.memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create session")
    return {
        "session_id": session["id"],
        "created_at": session["created_at"],
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """Get session info."""
    engine = _get_chat_engine()
    session = await engine.memory.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 20) -> dict:
    """Get message history for a session."""
    engine = _get_chat_engine()
    messages = await engine.memory.get_recent_messages(session_id, limit=limit)
    return {"messages": messages, "session_id": session_id}


@router.post("/sessions/{session_id}/chat")
async def sync_chat(session_id: str, body: SyncChatRequest) -> dict:
    """
    Synchronous (non-streaming) chat.

    Runs the full ReAct loop and returns the final assistant response plus all
    intermediate events.
    """
    engine = _get_chat_engine()

    events = []
    final_response = ""
    tokens_used = 0

    try:
        async for event in engine.chat(
            session_id=session_id,
            user_id=body.user_id,
            user_message=body.message,
        ):
            events.append(event)
            if event.get("type") == "message":
                final_response = event.get("content", "")
            elif event.get("type") == "done":
                tokens_used = event.get("tokens_used", 0)
            elif event.get("type") == "error":
                raise HTTPException(
                    status_code=500,
                    detail=event.get("message", "Chat engine error"),
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sync_chat_error", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "response": final_response,
        "session_id": session_id,
        "tokens_used": tokens_used,
        "events": events,
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """
    Streaming chat over WebSocket.

    Client sends:  {"type": "message", "content": "...", "user_id": "..."}
    Server emits:  event dicts from ChatEngine.chat() as JSON lines

    Client can also send: {"type": "approve", "tool_call_id": "..."}
    (tool approval flow — reserved for future use; currently auto-approved)
    """
    await websocket.accept()
    engine = _chat_engine

    if engine is None:
        await websocket.send_json(
            {"type": "error", "message": "Companion not initialized"}
        )
        await websocket.close()
        return

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.info("websocket_disconnected", session_id=session_id)
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "message":
                user_id = msg.get("user_id", "default")
                content = msg.get("content", "")

                if not content:
                    await websocket.send_json(
                        {"type": "error", "message": "Empty message content"}
                    )
                    continue

                try:
                    async for event in engine.chat(
                        session_id=session_id,
                        user_id=user_id,
                        user_message=content,
                    ):
                        await websocket.send_json(event)
                except Exception as exc:
                    logger.error(
                        "websocket_chat_error",
                        session_id=session_id,
                        error=str(exc),
                    )
                    await websocket.send_json({"type": "error", "message": str(exc)})

            elif msg_type == "approve":
                # Reserved for future tool approval flow
                logger.debug(
                    "approve_event_received",
                    session_id=session_id,
                    tool_call_id=msg.get("tool_call_id"),
                )

            else:
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )

    except WebSocketDisconnect:
        logger.info("websocket_closed", session_id=session_id)
    except Exception as exc:
        logger.error("websocket_error", session_id=session_id, error=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dispatch endpoints
# ---------------------------------------------------------------------------


@router.post("/dispatch")
async def create_dispatch(body: CreateDispatchRequest) -> dict:
    """Queue a Claude Code dispatch."""
    manager = _get_dispatch_manager()
    dispatch_id = await manager.create_dispatch(
        session_id=body.session_id,
        prompt_excerpt=body.prompt,
        branch=body.branch,
    )
    return {"dispatch_id": dispatch_id, "status": "pending"}


@router.get("/dispatch/{dispatch_id}")
async def get_dispatch(dispatch_id: str) -> dict:
    """Get dispatch status by ID."""
    manager = _get_dispatch_manager()
    dispatch = await manager.get_dispatch(dispatch_id)
    if not dispatch:
        raise HTTPException(status_code=404, detail="Dispatch not found")
    return dispatch


@router.get("/sessions/{session_id}/dispatches")
async def list_dispatches(session_id: str) -> dict:
    """List all dispatches for a session."""
    manager = _get_dispatch_manager()
    dispatches = await manager.list_dispatches(session_id)
    return {"dispatches": dispatches, "session_id": session_id}
