from __future__ import annotations

import asyncio
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field


RELAY_TOKEN = os.environ.get("BOSS_HR_RELAY_TOKEN", "")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("BOSS_HR_RELAY_REQUEST_TIMEOUT", "45"))
SESSION_RE = re.compile(r"^[A-Za-z0-9_.-]{3,80}$")


app = FastAPI(title="BOSS HR Cloud Relay", version="0.1.0")


class RpcRequest(BaseModel):
    method: str = Field(default="GET", pattern="^(GET|POST)$")
    path: str = Field(min_length=1)
    json_body: dict[str, Any] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1, le=120)


@dataclass
class RelaySession:
    session_id: str
    websocket: WebSocket
    connected_at: str
    last_seen_at: str
    pending: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


sessions: dict[str, RelaySession] = {}
sessions_lock = asyncio.Lock()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "boss-hr-cloud-relay",
        "connected_sessions": len(sessions),
    }


@app.websocket("/v1/connect/{session_id}")
async def connect(websocket: WebSocket, session_id: str) -> None:
    validate_session_id(session_id)
    token = websocket.query_params.get("token") or websocket.headers.get("x-boss-relay-token") or ""
    if not valid_token(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    connected_at = now_iso()
    relay_session = RelaySession(
        session_id=session_id,
        websocket=websocket,
        connected_at=connected_at,
        last_seen_at=connected_at,
    )

    async with sessions_lock:
        old_session = sessions.get(session_id)
        if old_session:
            fail_pending(old_session, RuntimeError("connector replaced"))
            await old_session.websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
        sessions[session_id] = relay_session

    try:
        while True:
            message = await websocket.receive_json()
            relay_session.last_seen_at = now_iso()
            request_id = str(message.get("id") or "")
            if not request_id:
                continue
            future = relay_session.pending.pop(request_id, None)
            if future and not future.done():
                future.set_result(message)
    except WebSocketDisconnect:
        pass
    finally:
        async with sessions_lock:
            current = sessions.get(session_id)
            if current is relay_session:
                sessions.pop(session_id, None)
        fail_pending(relay_session, RuntimeError("connector disconnected"))


@app.get("/v1/sessions/{session_id}/status")
async def session_status(session_id: str, x_boss_relay_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(x_boss_relay_token)
    validate_session_id(session_id)
    relay_session = await get_session(session_id)
    return {
        "connected": True,
        "session_id": session_id,
        "connected_at": relay_session.connected_at,
        "last_seen_at": relay_session.last_seen_at,
        "pending_requests": len(relay_session.pending),
    }


@app.post("/v1/sessions/{session_id}/rpc")
async def session_rpc(
    session_id: str,
    payload: RpcRequest,
    x_boss_relay_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_token(x_boss_relay_token)
    validate_session_id(session_id)
    return await send_rpc(session_id, payload)


@app.post("/v1/sessions/{session_id}/browser/start")
async def browser_start(
    session_id: str,
    payload: dict[str, Any] | None = None,
    x_boss_relay_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return await proxy_json(session_id, "POST", "/v1/browser/start", payload or {}, x_boss_relay_token)


@app.post("/v1/sessions/{session_id}/boss/login/start")
async def login_start(session_id: str, x_boss_relay_token: str | None = Header(default=None)) -> dict[str, Any]:
    return await proxy_json(session_id, "POST", "/v1/boss/login/start", {}, x_boss_relay_token)


@app.post("/v1/sessions/{session_id}/boss/login/send-code")
async def login_send_code(
    session_id: str,
    payload: dict[str, Any],
    x_boss_relay_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return await proxy_json(session_id, "POST", "/v1/boss/login/send-code", payload, x_boss_relay_token)


@app.post("/v1/sessions/{session_id}/boss/login/submit-code")
async def login_submit_code(
    session_id: str,
    payload: dict[str, Any],
    x_boss_relay_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return await proxy_json(session_id, "POST", "/v1/boss/login/submit-code", payload, x_boss_relay_token)


@app.get("/v1/sessions/{session_id}/boss/login/status")
async def login_status(session_id: str, x_boss_relay_token: str | None = Header(default=None)) -> dict[str, Any]:
    return await proxy_json(session_id, "GET", "/v1/boss/login/status", None, x_boss_relay_token)


@app.post("/v1/sessions/{session_id}/boss/navigate")
async def boss_navigate(
    session_id: str,
    payload: dict[str, Any],
    x_boss_relay_token: str | None = Header(default=None),
) -> dict[str, Any]:
    return await proxy_json(session_id, "POST", "/v1/boss/navigate", payload, x_boss_relay_token)


async def proxy_json(
    session_id: str,
    method: str,
    path: str,
    json_body: dict[str, Any] | None,
    token: str | None,
) -> dict[str, Any]:
    require_token(token)
    validate_session_id(session_id)
    rpc_response = await send_rpc(session_id, RpcRequest(method=method, path=path, json_body=json_body))
    status_code = int(rpc_response.get("status_code") or 502)
    body = rpc_response.get("body")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=body or rpc_response.get("text") or "local request failed")
    if isinstance(body, dict):
        return body
    return {"status": "ok", "body": body}


async def send_rpc(session_id: str, payload: RpcRequest) -> dict[str, Any]:
    relay_session = await get_session(session_id)
    request_id = secrets.token_hex(12)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    relay_session.pending[request_id] = future

    message = {
        "id": request_id,
        "method": payload.method,
        "path": normalize_local_path(payload.path),
        "json_body": payload.json_body,
    }

    try:
        async with relay_session.send_lock:
            await relay_session.websocket.send_json(message)
        timeout = payload.timeout_seconds or REQUEST_TIMEOUT_SECONDS
        response = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError as exc:
        relay_session.pending.pop(request_id, None)
        raise HTTPException(status_code=504, detail="local connector request timed out") from exc
    except Exception as exc:
        relay_session.pending.pop(request_id, None)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if response.get("error"):
        raise HTTPException(status_code=502, detail=response["error"])
    return dict(response.get("response") or {})


async def get_session(session_id: str) -> RelaySession:
    async with sessions_lock:
        relay_session = sessions.get(session_id)
    if not relay_session:
        raise HTTPException(status_code=404, detail=f"session not connected: {session_id}")
    return relay_session


def normalize_local_path(path: str) -> str:
    value = path.strip()
    if not value.startswith("/"):
        value = f"/{value}"
    if ".." in value:
        raise HTTPException(status_code=400, detail="invalid local path")
    return value


def validate_session_id(session_id: str) -> None:
    if not SESSION_RE.match(session_id):
        raise HTTPException(status_code=400, detail="invalid session id")


def require_token(token: str | None) -> None:
    if not valid_token(token or ""):
        raise HTTPException(status_code=401, detail="invalid relay token")


def valid_token(token: str) -> bool:
    return bool(RELAY_TOKEN) and secrets.compare_digest(token, RELAY_TOKEN)


def fail_pending(relay_session: RelaySession, exc: Exception) -> None:
    for future in relay_session.pending.values():
        if not future.done():
            future.set_exception(exc)
    relay_session.pending.clear()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
